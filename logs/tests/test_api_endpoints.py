import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings

# Use separate test database and calendar directory
TEST_DB = Path(__file__).resolve().parent / "test_email_assistant.db"
TEST_CAL = Path(__file__).resolve().parent / "test_calendar_events"
TEST_CAL.mkdir(parents=True, exist_ok=True)
settings.db_path = str(TEST_DB)
settings.calendar_dir = str(TEST_CAL)

from backend.main import app
from backend.database import init_db, get_db
from backend.services.calendar_service import calendar_service
calendar_service.events_dir = TEST_CAL

client = TestClient(app)

def test_full_api():
    print("Testing Full API Endpoints...")
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()

    # 1. Test Settings Endpoints
    res = client.get("/settings")
    assert res.status_code == 200, f"GET /settings failed: {res.text}"
    settings_data = res.json()
    assert "is_configured" in settings_data
    assert "muted_senders" in settings_data
    print("  [x] GET /settings passed.")

    res = client.post("/settings/mute", json={"sender_email": "annoying_newsletter@domain.com"})
    assert res.status_code == 200
    assert res.json()["status"] in ["success", "already_muted"]
    print("  [x] POST /settings/mute passed.")

    res = client.delete("/settings/mute/annoying_newsletter@domain.com")
    assert res.status_code == 200
    print("  [x] DELETE /settings/mute passed.")

    # 2. Insert sample emails for testing endpoints
    email_1 = "test-api-e1"
    email_2 = "test-api-e2"
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM emails WHERE id IN (?, ?)", (email_1, email_2))
        cursor.execute("""
            INSERT INTO emails (
                id, sender, subject, body_preview, body_full, body_html, body, received_at,
                category, priority_score, summary, is_processed, is_read, thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            email_1, "Alice Smith <alice@example.com>", "Product Strategy Review",
            "Can we meet on 2026-09-05 at 11:00 to review the deck?",
            "Hi team,\n\nCan we meet on 2026-09-05 at 11:00 to review the deck?\n\nBest,\nAlice",
            "<p>Hi team,</p><p>Can we meet on 2026-09-05 at 11:00 to review the deck?</p><p>Best,<br>Alice</p>",
            "Hi team,\n\nCan we meet on 2026-09-05 at 11:00 to review the deck?\n\nBest,\nAlice",
            "2026-08-30T11:00:00", "meeting", 8, "Meeting request for strategy review", 1, 0, "thread_strat_1"
        ))
        cursor.execute("""
            INSERT INTO emails (
                id, sender, subject, body_preview, body_full, body_html, body, received_at,
                category, priority_score, summary, is_processed, is_read, thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            email_2, "Bob Jones <bob@example.com>", "Weekly Engineering Digest",
            "Here is the engineering newsletter for this week.",
            "Here is the engineering newsletter for this week. Multiple features were deployed.",
            "<p>Here is the engineering newsletter for this week. Multiple features were deployed.</p>",
            "Here is the engineering newsletter for this week. Multiple features were deployed.",
            "2026-08-30T09:00:00", "newsletter", 3, "Weekly digest of features", 1, 1, "thread_digest_2"
        ))

    # 3. Test GET /emails (Default Chronological vs Priority)
    res = client.get("/emails")
    assert res.status_code == 200
    emails_list = res.json()
    assert len(emails_list) >= 2
    # Chronological sort (default): email_1 (11:00) should be before email_2 (09:00)
    assert emails_list[0]["latest_received_at"] >= emails_list[1]["latest_received_at"]
    print("  [x] GET /emails (default chronological) passed.")

    res = client.get("/emails?sort=priority")
    assert res.status_code == 200
    pri_list = res.json()
    assert len(pri_list) >= 2
    # Priority sort: email_1 (score 8) should be before email_2 (score 3)
    assert pri_list[0]["priority_score"] >= pri_list[1]["priority_score"]
    print("  [x] GET /emails?sort=priority passed.")

    res = client.get("/emails?sort=priority&min_priority=7")
    assert res.status_code == 200
    high_pri_list = res.json()
    assert len(high_pri_list) == 1
    assert high_pri_list[0]["priority_score"] >= 7
    print("  [x] GET /emails?sort=priority&min_priority=7 passed.")

    res = client.get("/emails?category=meeting")
    assert res.status_code == 200
    assert any(th["category"] == "meeting" for th in res.json())
    print("  [x] GET /emails?category=meeting passed.")

    res = client.get(f"/emails/{email_1}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["id"] == email_1
    assert "body_full" in detail
    assert "body_preview" in detail
    assert "thread_emails" in detail
    assert "drafts" in detail
    print("  [x] GET /emails/{id} with body_full verified.")

    # 4. Test Calendar Event Creation & GET /calendar-events
    res = client.post(f"/emails/{email_1}/create-event")
    assert res.status_code == 200, f"Create event failed: {res.text}"
    event_obj = res.json()
    assert event_obj["email_id"] == email_1
    assert event_obj["date"] != ""
    cal_event_id = event_obj["id"]
    print("  [x] POST /emails/{id}/create-event passed.")

    res = client.get("/calendar-events")
    assert res.status_code == 200
    all_events = res.json()
    assert len(all_events) >= 1
    matching_ev = next((ev for ev in all_events if ev["id"] == cal_event_id), None)
    assert matching_ev is not None
    assert matching_ev["email_subject"] == "Product Strategy Review"
    assert "Alice Smith" in matching_ev["email_sender"]
    print("  [x] GET /calendar-events (joined with email details) passed.")

    res = client.get(f"/calendar-events/{cal_event_id}/download")
    assert res.status_code == 200
    assert "text/calendar" in res.headers.get("content-type", "")
    print("  [x] GET /calendar-events/{id}/download passed.")

    # 5. Test AI Classify Endpoint
    res = client.post(f"/emails/{email_1}/classify")
    assert res.status_code == 200
    classify_result = res.json()
    assert "category" in classify_result
    assert "priority_score" in classify_result
    print("  [x] POST /emails/{id}/classify passed.")

    # 6. Test AI Draft Endpoint
    res = client.post(f"/emails/{email_1}/draft", json={"tone": "friendly"})
    assert res.status_code == 200
    draft_result = res.json()
    assert draft_result["email_id"] == email_1
    assert draft_result["tone"] == "friendly"
    assert len(draft_result["content"]) > 0
    draft_id = draft_result["id"]
    print("  [x] POST /emails/{id}/draft passed.")

    # 7. Test Chat Endpoint (RAG-lite & Compose)
    res = client.post("/chat", json={"query": "What is the product strategy meeting about?"})
    assert res.status_code == 200
    chat_result = res.json()
    assert "answer" in chat_result
    assert len(chat_result["answer"]) > 0
    assert chat_result.get("is_compose") is False
    print("  [x] POST /chat (RAG search) passed.")

    # Test Chat Compose New Email Intent
    res = client.post("/chat", json={"query": "Compose a friendly email to partner@example.com about the project kickoff"})
    assert res.status_code == 200
    compose_result = res.json()
    assert compose_result.get("is_compose") is True
    assert compose_result.get("draft") is not None
    assert compose_result["draft"]["recipient"] == "partner@example.com"
    assert len(compose_result["draft"]["subject"]) > 0
    assert len(compose_result["draft"]["body"]) > 0
    print("  [x] POST /chat (Compose New Email Intent) passed.")

    # 8. Test POST /chat/send-email Endpoint
    from unittest.mock import patch
    with patch("backend.api.routes_ai.email_client.send_email", return_value=True):
        res = client.post("/chat/send-email", json={
            "to_email": "partner@example.com",
            "subject": "Kickoff Meeting",
            "body": "Hi partner,\n\nLooking forward to working together."
        })
        assert res.status_code == 200
        send_res = res.json()
        assert send_res["status"] == "success"
        assert send_res["sent_to"] == "partner@example.com"
    print("  [x] POST /chat/send-email passed.")

    # 9. Test PATCH /emails/{id}/read
    res = client.patch(f"/emails/{email_1}/read?is_read=true")
    assert res.status_code == 200
    assert res.json()["is_read"] is True
    print("  [x] PATCH /emails/{id}/read passed.")

    # 10. Test Manual Sync Endpoint
    res = client.post("/emails/sync")
    assert res.status_code == 200
    assert "emails_fetched" in res.json()
    print("  [x] POST /emails/sync passed.")

    print("All backend API endpoints verified successfully!")

if __name__ == "__main__":
    test_full_api()
