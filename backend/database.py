import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, List, Optional, Dict, Any
from backend.config import settings, logger

def get_db_path() -> str:
    return settings.db_path

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite database connections."""
    conn = sqlite3.connect(get_db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initializes SQLite database tables and indices."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Emails Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                body_preview TEXT NOT NULL,
                body_full TEXT,
                body_html TEXT,
                body TEXT NOT NULL,
                received_at DATETIME NOT NULL,
                category TEXT,
                priority_score INTEGER,
                summary TEXT,
                is_processed BOOLEAN DEFAULT 0,
                is_read BOOLEAN DEFAULT 0,
                thread_id TEXT
            );
        """)

        # Migrations: Ensure body_full and body_html exist for existing databases
        cursor.execute("PRAGMA table_info(emails)")
        columns = [row["name"] for row in cursor.fetchall()]

        if "body_full" not in columns:
            cursor.execute("ALTER TABLE emails ADD COLUMN body_full TEXT")
            cursor.execute("UPDATE emails SET body_full = body WHERE body_full IS NULL OR body_full = ''")
            logger.info("Migrated emails table: Added body_full column.")

        if "body_html" not in columns:
            cursor.execute("ALTER TABLE emails ADD COLUMN body_html TEXT")
            cursor.execute("UPDATE emails SET body_html = body WHERE body_html IS NULL OR body_html = ''")
            logger.info("Migrated emails table: Added body_html column.")

        # Backfill any null body_full with body
        cursor.execute("UPDATE emails SET body_full = body WHERE body_full IS NULL OR body_full = ''")

        # Calendar Events Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id TEXT NOT NULL,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                location TEXT,
                attendees TEXT NOT NULL,
                ics_file_path TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
            );
        """)

        # Drafts Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id TEXT NOT NULL,
                tone TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME NOT NULL,
                is_sent BOOLEAN DEFAULT 0,
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
            );
        """)

        # Muted Senders Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS muted_senders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_email TEXT UNIQUE NOT NULL,
                muted_at DATETIME NOT NULL
            );
        """)

        # Indices for high performance queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_priority ON emails(priority_score);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_is_processed ON emails(is_processed);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_received_at ON emails(received_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_email_id ON calendar_events(email_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_drafts_email_id ON drafts(email_id);")

        logger.info("Database initialized successfully.")

    # Automatically purge test data from production DB on startup
    if not ("test" in get_db_path().lower() and "assistant.db" not in get_db_path().lower()):
        try:
            from backend.cleanup_test_data import cleanup_test_data
            cleanup_test_data(get_db_path())
        except Exception as e:
            logger.warning(f"Auto-cleanup of test data failed: {e}")

# Helper queries
def get_existing_email_ids() -> set:
    """Returns set of all existing email IDs."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM emails")
        return {row["id"] for row in cursor.fetchall()}

def get_muted_senders() -> List[Dict[str, Any]]:
    """Returns list of muted senders."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, sender_email, muted_at FROM muted_senders ORDER BY muted_at DESC")
        return [dict(row) for row in cursor.fetchall()]

def get_muted_sender_emails() -> set:
    """Returns set of lowercased muted sender emails."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT sender_email FROM muted_senders")
        return {row["sender_email"].lower().strip() for row in cursor.fetchall()}

def add_muted_sender(sender_email: str) -> bool:
    """Adds email to muted_senders table."""
    sender_email = sender_email.lower().strip()
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO muted_senders (sender_email, muted_at) VALUES (?, ?)",
                (sender_email, datetime.now().isoformat())
            )
            return True
        except sqlite3.IntegrityError:
            return False

def remove_muted_sender(sender_email: str) -> bool:
    """Removes email from muted_senders table."""
    sender_email = sender_email.lower().strip()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM muted_senders WHERE lower(sender_email) = ?", (sender_email,))
        return cursor.rowcount > 0
