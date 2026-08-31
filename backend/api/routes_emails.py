import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from backend.config import logger
from backend.database import get_db
from backend.models import EmailResponse, EmailDetailResponse, CalendarEventResponse, DraftResponse
from backend.services.email_client import email_client
from backend.services.gemini_agent import gemini_agent
from backend.services.calendar_service import calendar_service

router = APIRouter(prefix="/emails", tags=["Emails"])

@router.get("", response_model=List[Dict[str, Any]])
def list_emails(
    category: Optional[str] = Query(None, description="Filter by category (urgent, business, meeting, newsletter, spam)"),
    min_priority: Optional[int] = Query(None, ge=1, le=10, description="Filter by minimum priority score (1-10)"),
    search: Optional[str] = Query(None, description="Keyword search in subject, sender, or body"),
    thread_grouped: bool = Query(True, description="Whether to group emails by thread_id"),
    sort: str = Query("chronological", description="Sort order: 'chronological' (received_at DESC) or 'priority' (priority_score DESC, received_at DESC)")
):
    """
    Lists emails, filterable by category, min_priority, and search query.
    Sorted by received_at DESC for chronological (default) or priority_score DESC, received_at DESC for priority.
    """
    query_parts = ["SELECT * FROM emails WHERE 1=1"]
    params = []

    if category:
        query_parts.append("AND lower(category) = ?")
        params.append(category.lower().strip())

    if min_priority is not None:
        query_parts.append("AND priority_score >= ?")
        params.append(min_priority)

    if search:
        query_parts.append("AND (subject LIKE ? OR sender LIKE ? OR body_preview LIKE ? OR body_full LIKE ? OR body LIKE ?)")
        term = f"%{search.strip()}%"
        params.extend([term, term, term, term, term])

    # Dynamic sorting based on sort query parameter
    if sort.lower() == "priority":
        query_parts.append("ORDER BY CASE WHEN priority_score IS NULL THEN 0 ELSE 1 END DESC, priority_score DESC, received_at DESC")
    else:
        query_parts.append("ORDER BY received_at DESC")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(" ".join(query_parts), params)
        rows = [dict(row) for row in cursor.fetchall()]

    if not thread_grouped:
        return rows

    # Group by thread_id while preserving the highest priority / latest order of threads
    threads_dict: Dict[str, Dict[str, Any]] = {}
    thread_order = []

    for email_row in rows:
        th_id = email_row.get("thread_id") or f"single_{email_row['id']}"
        if th_id not in threads_dict:
            thread_order.append(th_id)
            threads_dict[th_id] = {
                "thread_id": th_id,
                "subject": email_row["subject"],
                "category": email_row["category"],
                "priority_score": email_row["priority_score"],
                "summary": email_row["summary"],
                "latest_received_at": email_row["received_at"],
                "unread_count": 0,
                "emails": []
            }
        
        # Track unread count
        if not email_row["is_read"]:
            threads_dict[th_id]["unread_count"] += 1

        # Keep highest priority score on thread
        current_pri = threads_dict[th_id]["priority_score"]
        new_pri = email_row["priority_score"]
        if new_pri is not None and (current_pri is None or new_pri > current_pri):
            threads_dict[th_id]["priority_score"] = new_pri
            threads_dict[th_id]["category"] = email_row["category"]
            threads_dict[th_id]["summary"] = email_row["summary"]

        threads_dict[th_id]["emails"].append(email_row)

    return [threads_dict[th_id] for th_id in thread_order]

@router.get("/{email_id}", response_model=EmailDetailResponse)
def get_email_detail(email_id: str):
    """
    Returns full email detail including body, thread sibling emails,
    associated calendar events, and drafts.
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM emails WHERE id = ?", (email_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Email not found")
        
        email_data = dict(row)
        if not email_data.get("body_full"):
            email_data["body_full"] = email_data.get("body") or email_data.get("body_preview") or ""

        thread_id = email_data.get("thread_id")

        # Fetch sibling emails in thread
        thread_emails = []
        if thread_id:
            cursor.execute(
                "SELECT * FROM emails WHERE thread_id = ? ORDER BY received_at ASC",
                (thread_id,)
            )
            thread_emails = [dict(r) for r in cursor.fetchall()]
            for te in thread_emails:
                if not te.get("body_full"):
                    te["body_full"] = te.get("body") or te.get("body_preview") or ""
        else:
            thread_emails = [email_data]

        # Fetch calendar events
        cursor.execute("SELECT * FROM calendar_events WHERE email_id = ?", (email_id,))
        cal_rows = cursor.fetchall()
        calendar_events = []
        for c in cal_rows:
            cd = dict(c)
            try:
                cd["attendees"] = json.loads(cd["attendees"])
            except Exception:
                cd["attendees"] = []
            calendar_events.append(cd)

        # Fetch drafts
        cursor.execute("SELECT * FROM drafts WHERE email_id = ? ORDER BY created_at DESC", (email_id,))
        drafts = [dict(d) for d in cursor.fetchall()]

    email_data["thread_emails"] = thread_emails
    email_data["calendar_events"] = calendar_events
    email_data["drafts"] = drafts

    return email_data

@router.post("/sync")
def trigger_sync():
    """
    Manually triggers an email sync cycle:
    1. Fetches new emails from IMAP
    2. Runs AI triage on unclassified emails
    3. Runs meeting extraction on meeting-tagged emails
    """
    from backend.config import settings
    if not settings.is_configured:
        raise HTTPException(
            status_code=400,
            detail="Email and AI credentials are not fully configured in Settings."
        )

    try:
        fetched = email_client.fetch_new_emails(limit=20, raise_on_error=True)
    except Exception as e:
        logger.error(f"Manual sync failed: {e}")
        raise HTTPException(status_code=502, detail=f"Sync failed: {e}")
    
    # Process unclassified emails
    classified_count = 0
    meetings_count = 0

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, subject, body FROM emails WHERE is_processed = 0")
        unprocessed = cursor.fetchall()

    for item in unprocessed:
        e_id = item["id"]
        subj = item["subject"]
        body = item["body"]

        # Triage classification
        triage = gemini_agent.classify_email(subj, body)
        category = triage["category"]
        priority = triage["priority_score"]
        summary = triage["summary"]

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE emails
                SET category = ?, priority_score = ?, summary = ?, is_processed = 1
                WHERE id = ?
            """, (category, priority, summary, e_id))
        classified_count += 1

        # Check if meeting
        if category == "meeting":
            meeting_details = gemini_agent.extract_meeting_details(subj, body)
            if meeting_details.get("is_meeting"):
                ev = calendar_service.generate_ics_event(meeting_details, e_id)
                if ev:
                    meetings_count += 1

    logger.info(f"Manual sync completed: {len(fetched)} fetched, {classified_count} classified, {meetings_count} meetings created.")

    return {
        "status": "success",
        "emails_fetched": len(fetched),
        "emails_classified": classified_count,
        "meetings_created": meetings_count
    }

@router.patch("/{email_id}/read")
def toggle_read_status(email_id: str, is_read: bool = True):
    """Marks an email as read or unread."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE emails SET is_read = ? WHERE id = ?", (1 if is_read else 0, email_id))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Email not found")

    return {"status": "success", "id": email_id, "is_read": is_read}
