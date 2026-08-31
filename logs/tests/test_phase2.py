import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings

# Use separate test database
TEST_DB = Path(__file__).resolve().parent / "test_email_assistant.db"
settings.db_path = str(TEST_DB)

from backend.database import init_db, get_db, add_muted_sender, get_muted_sender_emails
from backend.services.email_client import (
    clean_subject_for_threading,
    generate_thread_id,
    parse_raw_email
)

def test_phase2():
    print("Testing Phase 2: Email Client & Threading Engine...")
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()

    # 1. Test subject cleaning & threading
    s1 = "Re: Project Launch Q3"
    s2 = "Fwd: RE: Project Launch Q3"
    s3 = "Project Launch Q3"
    assert clean_subject_for_threading(s1) == "Project Launch Q3"
    assert clean_subject_for_threading(s2) == "Project Launch Q3"
    assert clean_subject_for_threading(s3) == "Project Launch Q3"

    th1 = generate_thread_id("Project Launch Q3", "alice@example.com")
    th2 = generate_thread_id("Project Launch Q3", "bob@example.com")
    assert th1 == th2, "Thread IDs for the same conversation subject should match"
    print("  [x] Subject cleaning & Thread ID consistency verified.")

    # 2. Test raw email parsing with HTML and multipart
    msg = MIMEMultipart("alternative")
    msg["From"] = "Sarah Connor <sarah@skynet-resistance.org>"
    msg["To"] = "John Connor <john@skynet-resistance.org>"
    msg["Subject"] = "Re: Tactical briefing on Monday"
    msg["Date"] = "Mon, 30 Aug 2026 10:00:00 +0000"

    html_content = "<html><body><h2>Urgent Briefing</h2><p>Please meet me at the bunker at 14:00.</p></body></html>"
    msg.attach(MIMEText("Please meet me at the bunker at 14:00.", "plain"))
    msg.attach(MIMEText(html_content, "html"))

    raw_bytes = msg.as_bytes()
    parsed = parse_raw_email("test-uid-101", raw_bytes)

    assert parsed is not None
    assert parsed["id"] == "test-uid-101"
    assert "Sarah Connor" in parsed["sender"]
    assert parsed["sender_email"] == "sarah@skynet-resistance.org"
    assert "14:00" in parsed["body"]
    assert "14:00" in parsed["body_full"]
    assert parsed["body_html"] is not None and "Urgent Briefing" in parsed["body_html"]
    assert parsed["is_processed"] == 0
    print("  [x] Raw MIME message parsing with full body and HTML verified.")

    # 3. Test Muted Sender Filtering
    add_muted_sender("spammer@newsletter-spam.com")
    muted_set = get_muted_sender_emails()
    assert "spammer@newsletter-spam.com" in muted_set

    spam_msg = MIMEText("Buy cheap stuff now!")
    spam_msg["From"] = "Spammer <spammer@newsletter-spam.com>"
    spam_msg["Subject"] = "Special discounts"
    spam_parsed = parse_raw_email("spam-uid-102", spam_msg.as_bytes())

    assert spam_parsed["sender_email"] in muted_set, "Spam sender should be matched in muted list"
    print("  [x] Muted sender filter verified.")

    # 4. Insert test parsed emails into DB
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM emails WHERE id LIKE 'test-uid-%'")
        cursor.execute("""
            INSERT INTO emails (
                id, sender, subject, body_preview, body_full, body_html, body, received_at,
                category, priority_score, summary, is_processed, is_read, thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            parsed["id"],
            parsed["sender"],
            parsed["subject"],
            parsed["body_preview"],
            parsed["body_full"],
            parsed["body_html"],
            parsed["body"],
            parsed["received_at"],
            parsed["category"],
            parsed["priority_score"],
            parsed["summary"],
            parsed["is_processed"],
            parsed["is_read"],
            parsed["thread_id"]
        ))
        
        # Verify fetch from DB
        cursor.execute("SELECT * FROM emails WHERE id = ?", (parsed["id"],))
        row = cursor.fetchone()
        assert row is not None
        assert row["id"] == "test-uid-101"
        assert row["body_full"] is not None and "14:00" in row["body_full"]
        assert row["body_html"] is not None and "Urgent Briefing" in row["body_html"]
        assert row["is_processed"] == 0

    print("Phase 2 verified successfully!")

if __name__ == "__main__":
    test_phase2()
