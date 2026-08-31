import os
import sys
import sqlite3
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings, logger

def cleanup_test_data(db_path: str = None) -> dict:
    """
    Deletes any row in emails (and cascades to calendar_events/drafts)
    where the id starts with test- or spam- or matches known test patterns.
    Also removes corresponding .ics files on disk.
    """
    target_db = db_path or settings.db_path
    if not Path(target_db).exists():
        logger.info(f"Target DB {target_db} does not exist. Skipping cleanup.")
        return {"deleted_emails": 0, "deleted_events": 0, "deleted_drafts": 0, "deleted_ics_files": 0}

    deleted_emails = 0
    deleted_events = 0
    deleted_drafts = 0
    deleted_ics = 0

    conn = sqlite3.connect(target_db, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        cursor = conn.cursor()

        # 1. Find test calendar events and delete their .ics files
        cursor.execute("""
            SELECT id, email_id, ics_file_path 
            FROM calendar_events 
            WHERE email_id LIKE 'test-%' OR email_id LIKE 'spam-%' OR email_id LIKE 'test_uid_%'
        """)
        events_to_delete = cursor.fetchall()
        for ev in events_to_delete:
            ics_path = ev["ics_file_path"]
            if ics_path and Path(ics_path).exists():
                try:
                    os.remove(ics_path)
                    deleted_ics += 1
                except Exception as e:
                    logger.warning(f"Failed to remove test .ics file {ics_path}: {e}")

        # Delete calendar events
        cursor.execute("""
            DELETE FROM calendar_events 
            WHERE email_id LIKE 'test-%' OR email_id LIKE 'spam-%' OR email_id LIKE 'test_uid_%'
        """)
        deleted_events = cursor.rowcount

        # 2. Delete test drafts
        cursor.execute("""
            DELETE FROM drafts 
            WHERE email_id LIKE 'test-%' OR email_id LIKE 'spam-%' OR email_id LIKE 'test_uid_%'
        """)
        deleted_drafts = cursor.rowcount

        # 3. Delete test emails
        cursor.execute("""
            DELETE FROM emails 
            WHERE id LIKE 'test-%' OR id LIKE 'spam-%' OR id LIKE 'test_uid_%'
        """)
        deleted_emails = cursor.rowcount

        conn.commit()
        logger.info(
            f"Test data cleanup complete for {target_db}: "
            f"{deleted_emails} emails, {deleted_events} events, {deleted_drafts} drafts, {deleted_ics} .ics files removed."
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Error during test data cleanup on {target_db}: {e}")
        raise
    finally:
        conn.close()

    return {
        "deleted_emails": deleted_emails,
        "deleted_events": deleted_events,
        "deleted_drafts": deleted_drafts,
        "deleted_ics_files": deleted_ics
    }

if __name__ == "__main__":
    result = cleanup_test_data()
    print("Cleanup Result:", result)
