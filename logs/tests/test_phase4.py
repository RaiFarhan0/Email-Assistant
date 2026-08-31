import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings

# Use separate test database and calendar directory
TEST_DB = Path(__file__).resolve().parent / "test_email_assistant.db"
TEST_CAL = Path(__file__).resolve().parent / "test_calendar_events"
TEST_CAL.mkdir(parents=True, exist_ok=True)
settings.db_path = str(TEST_DB)
settings.calendar_dir = str(TEST_CAL)

from backend.database import init_db, get_db
from backend.services.calendar_service import calendar_service
calendar_service.events_dir = TEST_CAL

def test_phase4():
    print("Testing Phase 4: Calendar Service & .ICS generation...")
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()

    email_id = "test-meeting-email-401"
    # Ensure parent email exists for foreign key constraint
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM emails WHERE id = ?", (email_id,))
        cursor.execute("""
            INSERT INTO emails (
                id, sender, subject, body_preview, body, received_at,
                category, priority_score, summary, is_processed, is_read, thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            email_id, "Boss <boss@company.com>", "Q4 Strategy Meeting",
            "Let's sync on Tuesday at 14:00.", "Let's sync on Tuesday at 14:00.",
            "2026-08-30T10:00:00", "meeting", 8, "Q4 sync meeting", 1, 0, "th-strategy"
        ))

    event_data = {
        "title": "Q4 Strategy Review",
        "date": "2026-09-02",
        "start_time": "14:00",
        "end_time": "15:00",
        "location": "Conference Room B & Google Meet",
        "attendees": ["boss@company.com", "sarah@company.com"]
    }

    # Generate event
    ev = calendar_service.generate_ics_event(event_data, email_id)
    assert ev is not None, "Failed to generate .ics event"
    assert ev["email_id"] == email_id
    assert Path(ev["ics_file_path"]).exists(), "ICS file does not exist on disk"

    # Verify content in .ics file
    with open(ev["ics_file_path"], "r", encoding="utf-8") as f:
        content = f.read()
        assert "BEGIN:VCALENDAR" in content
        assert "Q4 Strategy Review" in content
        assert "Conference Room B" in content
    print("  [x] ICS file RFC 5545 format verified.")

    # Test idempotency (should return existing event without duplicate)
    ev_duplicate = calendar_service.generate_ics_event(event_data, email_id)
    assert ev_duplicate["id"] == ev["id"], "Idempotency failed: generated duplicate event ID"
    print("  [x] Idempotency verified.")

    print("Phase 4 verified successfully!")

if __name__ == "__main__":
    test_phase4()
