import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from ics import Calendar, Event

from backend.config import settings, logger
from backend.database import get_db

class CalendarService:
    """Service for building and managing local .ics calendar events."""

    def __init__(self):
        self.events_dir = Path(settings.calendar_dir)
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def get_event_by_email_id(self, email_id: str) -> Optional[Dict[str, Any]]:
        """Checks if a calendar event already exists for the given email_id."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM calendar_events WHERE email_id = ?", (str(email_id),))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                try:
                    d["attendees"] = json.loads(d["attendees"])
                except Exception:
                    d["attendees"] = []
                return d
        return None

    def get_event_by_id(self, event_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a calendar event by its primary key ID."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                try:
                    d["attendees"] = json.loads(d["attendees"])
                except Exception:
                    d["attendees"] = []
                return d
        return None

    def generate_ics_event(self, event_data: Dict[str, Any], email_id: str) -> Optional[Dict[str, Any]]:
        """
        Builds a valid .ics calendar event file and records it in calendar_events table.
        Skips generation if a calendar event already exists for this email_id.
        """
        # Idempotency check
        existing = self.get_event_by_email_id(email_id)
        if existing:
            logger.info(f"Calendar event already exists for email_id {email_id}. Skipping regeneration.")
            return existing

        title = event_data.get("title") or "Meeting"
        date_str = event_data.get("date")  # YYYY-MM-DD
        start_time = event_data.get("start_time", "09:00")  # HH:MM
        end_time = event_data.get("end_time", "10:00")  # HH:MM
        location = event_data.get("location", "Virtual / Video Call")
        attendees = event_data.get("attendees", [])
        if isinstance(attendees, str):
            attendees = [attendees]

        if not date_str:
            logger.warning("Cannot generate .ics: date is missing.")
            return None

        # Build ICS object
        cal = Calendar()
        event = Event()
        event.name = title
        event.location = location

        attendees_str = ", ".join(attendees) if attendees else "None listed"
        event.description = f"Email Assistant Scheduled Meeting\nAttendees: {attendees_str}"

        # Construct datetime strings
        try:
            begin_str = f"{date_str} {start_time}:00"
            end_str = f"{date_str} {end_time}:00"
            event.begin = begin_str
            event.end = end_str
        except Exception as e:
            logger.error(f"Failed to set event time begin='{begin_str}' end='{end_str}': {e}")
            event.begin = f"{date_str} 09:00:00"
            event.end = f"{date_str} 10:00:00"

        cal.events.add(event)

        # Generate unique filename
        filename = f"{uuid.uuid4().hex}.ics"
        file_path = self.events_dir / filename

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(cal.serialize_iter())
        except Exception as e:
            logger.error(f"Error writing .ics file {file_path}: {e}")
            return None

        # Store in database
        now_iso = datetime.now().isoformat()
        attendees_json = json.dumps(attendees)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO calendar_events (
                    email_id, title, date, start_time, end_time, location, attendees, ics_file_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(email_id),
                title,
                date_str,
                start_time,
                end_time,
                location,
                attendees_json,
                str(file_path),
                now_iso
            ))
            event_id = cursor.lastrowid

        logger.info(f"Generated .ics calendar event #{event_id} at {file_path} for email {email_id}")

        return {
            "id": event_id,
            "email_id": str(email_id),
            "title": title,
            "date": date_str,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
            "attendees": attendees,
            "ics_file_path": str(file_path),
            "created_at": now_iso
        }

    def delete_event_by_email_id(self, email_id: str) -> bool:
        """Deletes calendar event and associated .ics file for an email ID."""
        event = self.get_event_by_email_id(email_id)
        if not event:
            return False
        
        ics_path = event.get("ics_file_path")
        if ics_path and Path(ics_path).exists():
            try:
                os.remove(ics_path)
            except Exception as e:
                logger.warning(f"Failed to delete .ics file {ics_path}: {e}")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM calendar_events WHERE email_id = ?", (str(email_id),))
            return cursor.rowcount > 0

    def delete_event(self, event_id: int) -> bool:
        """Deletes calendar event and associated .ics file by primary key ID."""
        event = self.get_event_by_id(event_id)
        if not event:
            return False

        ics_path = event.get("ics_file_path")
        if ics_path and Path(ics_path).exists():
            try:
                os.remove(ics_path)
            except Exception as e:
                logger.warning(f"Failed to delete .ics file {ics_path}: {e}")

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
            return cursor.rowcount > 0

calendar_service = CalendarService()
