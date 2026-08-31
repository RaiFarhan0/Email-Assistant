import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from email.utils import parseaddr

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from backend.config import logger
from backend.database import get_db
from backend.models import (
    ClassifyResponse,
    CalendarEventResponse,
    CalendarEventWithEmailResponse,
    GenerateDraftRequest,
    DraftResponse,
    SendDraftRequest,
    ChatRequest,
    ChatResponse,
    EmailDraftPayload,
    SendEmailRequest
)
from backend.services.gemini_agent import gemini_agent
from backend.services.calendar_service import calendar_service
from backend.services.email_client import email_client

router = APIRouter(tags=["AI Services"])

@router.post("/emails/{email_id}/classify", response_model=ClassifyResponse)
def force_reclassify_email(email_id: str):
    """Forces Gemini re-classification for a specific email."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, subject, body FROM emails WHERE id = ?", (email_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Email not found")
        
        email_data = dict(row)

    res = gemini_agent.classify_email(email_data["subject"], email_data["body"])
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE emails
            SET category = ?, priority_score = ?, summary = ?, is_processed = 1
            WHERE id = ?
        """, (res["category"], res["priority_score"], res["summary"], email_id))

    logger.info(f"Re-classified email {email_id}: {res['category']} (score: {res['priority_score']})")
    return res

@router.post("/emails/{email_id}/create-event", response_model=CalendarEventResponse)
def create_calendar_event(email_id: str):
    """Extracts meeting details from email and generates local .ics event."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, subject, body FROM emails WHERE id = ?", (email_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Email not found")
        
        email_data = dict(row)

    # Check if event already exists
    existing = calendar_service.get_event_by_email_id(email_id)
    if existing:
        return existing

    meeting_data = gemini_agent.extract_meeting_details(email_data["subject"], email_data["body"])
    if not meeting_data.get("is_meeting"):
        raise HTTPException(
            status_code=400,
            detail="Could not extract meeting details with confident date/time from this email."
        )

    event_record = calendar_service.generate_ics_event(meeting_data, email_id)
    if not event_record:
        raise HTTPException(status_code=500, detail="Failed to create .ics calendar file.")

    return event_record

@router.get("/calendar-events", response_model=List[CalendarEventWithEmailResponse])
def list_calendar_events():
    """
    Returns all rows from calendar_events joined with parent email subject and sender,
    sorted by date ASC and start_time ASC (upcoming first).
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                c.id, c.email_id, c.title, c.date, c.start_time, c.end_time,
                c.location, c.attendees, c.ics_file_path, c.created_at,
                e.subject AS email_subject, e.sender AS email_sender
            FROM calendar_events c
            LEFT JOIN emails e ON c.email_id = e.id
            ORDER BY c.date ASC, c.start_time ASC
        """)
        rows = cursor.fetchall()
        events = []
        for r in rows:
            cd = dict(r)
            try:
                if isinstance(cd["attendees"], str):
                    cd["attendees"] = json.loads(cd["attendees"])
                elif not cd["attendees"]:
                    cd["attendees"] = []
            except Exception:
                cd["attendees"] = []
            events.append(cd)
    return events

@router.get("/calendar-events/{event_id}/download")
def download_calendar_event(event_id: int):
    """Serves the .ics calendar file as an attachment download."""
    event_record = calendar_service.get_event_by_id(event_id)
    if not event_record:
        raise HTTPException(status_code=404, detail="Calendar event not found")

    file_path = Path(event_record["ics_file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Calendar .ics file not found on disk")

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', event_record['title'])[:40] or "event"
    return FileResponse(
        path=file_path,
        filename=f"{safe_title}.ics",
        media_type="text/calendar"
    )

@router.post("/emails/{email_id}/draft", response_model=DraftResponse)
def generate_draft_reply(email_id: str, payload: GenerateDraftRequest):
    """Generates an AI reply draft with the requested tone and stores it in drafts table."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, sender, subject, body FROM emails WHERE id = ?", (email_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Email not found")
        
        email_data = dict(row)

    draft_content = gemini_agent.generate_reply(
        email_content=email_data["body"],
        tone=payload.tone,
        sender=email_data["sender"],
        subject=email_data["subject"]
    )

    now_iso = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO drafts (email_id, tone, content, created_at, is_sent)
            VALUES (?, ?, ?, ?, 0)
        """, (email_id, payload.tone, draft_content, now_iso))
        draft_id = cursor.lastrowid

    logger.info(f"Generated AI draft #{draft_id} ({payload.tone}) for email {email_id}")

    return {
        "id": draft_id,
        "email_id": email_id,
        "tone": payload.tone,
        "content": draft_content,
        "created_at": now_iso,
        "is_sent": False
    }

@router.post("/drafts/{draft_id}/send")
def send_draft_reply(draft_id: int, payload: SendDraftRequest):
    """Sends the (possibly edited) draft via SMTP and marks is_sent = true."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.id, d.email_id, d.content, d.is_sent, e.sender, e.subject
            FROM drafts d
            JOIN emails e ON d.email_id = e.id
            WHERE d.id = ?
        """, (draft_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found")

        draft_data = dict(row)

    content_to_send = payload.content if payload.content is not None else draft_data["content"]
    
    # Extract recipient email
    _, to_email = parseaddr(draft_data["sender"])
    if not to_email:
        to_email = draft_data["sender"].strip()

    subject_to_send = draft_data["subject"]
    if not subject_to_send.lower().startswith("re:"):
        subject_to_send = f"Re: {subject_to_send}"

    success = email_client.send_email(
        to_email=to_email,
        subject=subject_to_send,
        body=content_to_send
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to send email via SMTP. Please check your email credentials and connection."
        )

    # Mark as sent
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE drafts
            SET is_sent = 1, content = ?
            WHERE id = ?
        """, (content_to_send, draft_id))

    logger.info(f"Draft #{draft_id} sent successfully to {to_email}")
    return {"status": "success", "draft_id": draft_id, "sent_to": to_email}

@router.post("/chat", response_model=ChatResponse)
def chat_with_inbox(payload: ChatRequest):
    """
    RAG-lite endpoint for natural language queries across the inbox and compose new email intents.
    Supports English & Urdu queries.
    """
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # 1. Check for intent to compose/write/send a NEW email
    compose_intent = gemini_agent.detect_compose_intent(query)
    if compose_intent and compose_intent.get("is_compose"):
        recipient = compose_intent.get("recipient", "")
        context = compose_intent.get("context", query)
        tone = compose_intent.get("tone", "professional")

        draft_res = gemini_agent.compose_new_email(recipient=recipient, context=context, tone=tone)

        recipient_display = f"**{recipient}**" if recipient else "the recipient"
        answer_text = (
            f"I have prepared an email draft for {recipient_display}. "
            "Please review the preview below, make any edits if needed, and confirm before sending:"
        )

        return {
            "query": query,
            "answer": answer_text,
            "referenced_email_ids": [],
            "draft": {
                "recipient": recipient,
                "subject": draft_res.get("subject", "New Message"),
                "body": draft_res.get("body", ""),
                "tone": tone
            },
            "is_compose": True
        }

    # 2. RAG-lite inbox search
    # Comprehensive stopwords list for English and Roman Urdu
    stopwords = {
        'the', 'is', 'at', 'which', 'on', 'a', 'an', 'and', 'or', 'in', 'to', 'for', 'of', 'with',
        'did', 'do', 'does', 'you', 'i', 'my', 'any', 'from', 'what', 'when', 'how', 'who', 'where', 'why',
        'about', 'have', 'has', 'had', 'been', 'there', 'here', 'all', 'some', 'check', 'show', 'tell',
        'ka', 'ki', 'ke', 'ko', 'se', 'me', 'mein', 'par', 'pe', 'kya', 'koi', 'hai', 'hain', 'tha',
        'thi', 'the', 'aya', 'ayi', 'aye', 'hua', 'hui', 'hue', 'karein', 'karo', 'bhi', 'aur',
        'ha', 'he', 'hn', 'batao', 'bataiye', 'kiska', 'kiski', 'konsa', 'konsi', 'mujhe', 'mera',
        'meri', 'mere', 'aap', 'apka', 'apki', 'apke', 'kahan', 'kab', 'wala', 'wali', 'wale',
        'email', 'emails', 'mail', 'mails', 'message', 'messages', 'inbox'
    }

    raw_words = [w.lower() for w in re.split(r'\W+', query) if len(w) >= 2]
    meaningful_keywords = [w for w in raw_words if w not in stopwords]
    keywords_to_search = meaningful_keywords if meaningful_keywords else raw_words

    lower_query = query.lower()

    with get_db() as conn:
        cursor = conn.cursor()
        matched_emails = []

        # Intent detection for meetings or urgency
        if any(w in lower_query for w in ["meeting", "meetings", "schedule", "event", "call", "appointment"]):
            cursor.execute("""
                SELECT id, sender, subject, body_preview, body, received_at, category, priority_score, summary 
                FROM emails 
                WHERE category = 'meeting' OR lower(subject) LIKE '%meeting%' OR lower(subject) LIKE '%call%'
                ORDER BY received_at DESC LIMIT 6
            """)
            matched_emails = [dict(r) for r in cursor.fetchall()]

        elif any(w in lower_query for w in ["urgent", "priority", "important", "critical", "action"]):
            cursor.execute("""
                SELECT id, sender, subject, body_preview, body, received_at, category, priority_score, summary 
                FROM emails 
                WHERE category = 'urgent' OR priority_score >= 7
                ORDER BY priority_score DESC, received_at DESC LIMIT 6
            """)
            matched_emails = [dict(r) for r in cursor.fetchall()]

        # Keyword-based search
        if not matched_emails and keywords_to_search:
            conditions = []
            params = []
            for kw in keywords_to_search[:4]:
                term = f"%{kw}%"
                conditions.append("(lower(subject) LIKE ? OR lower(sender) LIKE ? OR lower(body_preview) LIKE ? OR lower(body) LIKE ?)")
                params.extend([term, term, term, term])

            top_term = f"%{keywords_to_search[0]}%"
            sql = f"""
                SELECT id, sender, subject, body_preview, body, received_at, category, priority_score, summary 
                FROM emails 
                WHERE {' OR '.join(conditions)} 
                ORDER BY 
                    CASE 
                        WHEN lower(sender) LIKE ? OR lower(subject) LIKE ? THEN 1
                        ELSE 2
                    END,
                    received_at DESC 
                LIMIT 6
            """
            cursor.execute(sql, params + [top_term, top_term])
            matched_emails = [dict(r) for r in cursor.fetchall()]

        # Fallback to recent emails if nothing matched specific filters
        if not matched_emails:
            cursor.execute("""
                SELECT id, sender, subject, body_preview, body, received_at, category, priority_score, summary 
                FROM emails 
                ORDER BY received_at DESC LIMIT 6
            """)
            matched_emails = [dict(r) for r in cursor.fetchall()]

    answer = gemini_agent.chat_with_inbox(query, matched_emails)
    referenced_ids = [m["id"] for m in matched_emails]

    return {
        "query": query,
        "answer": answer,
        "referenced_email_ids": referenced_ids,
        "draft": None,
        "is_compose": False
    }

@router.post("/chat/send-email")
def send_chat_email(payload: SendEmailRequest):
    """
    Sends a composed email via SMTP after explicit user confirmation in Chat With Inbox.
    """
    to_email = payload.to_email.strip()
    if not to_email or "@" not in to_email:
        raise HTTPException(status_code=400, detail="A valid recipient email address is required.")

    if not payload.body or not payload.body.strip():
        raise HTTPException(status_code=400, detail="Email body cannot be empty.")

    subject = payload.subject.strip() if payload.subject else "No Subject"

    success = email_client.send_email(
        to_email=to_email,
        subject=subject,
        body=payload.body,
        in_reply_to=payload.in_reply_to
    )

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to send email via SMTP. Please verify your email credentials in Settings."
        )

    logger.info(f"Chat-composed email sent successfully to {to_email} with subject: '{subject}'")
    return {
        "status": "success",
        "sent_to": to_email,
        "subject": subject,
        "sent_at": datetime.now().isoformat()
    }
