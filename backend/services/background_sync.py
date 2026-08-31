import asyncio
from datetime import datetime
from typing import Dict, Any

from backend.config import settings, logger
from backend.database import get_db
from backend.services.email_client import email_client
from backend.services.gemini_agent import gemini_agent
from backend.services.calendar_service import calendar_service

class BackgroundSyncService:
    """Async background worker orchestrating periodic IMAP fetch, AI triage, and calendar processing."""

    def __init__(self):
        self._is_running = False
        self._task: asyncio.Task = None
        self._lock = asyncio.Lock()

    async def run_sync_cycle(self) -> Dict[str, Any]:
        """Executes a single sync and triage cycle with locking to prevent overlapping executions."""
        async with self._lock:
            if not settings.is_configured:
                logger.info("Background sync skipped: Credentials not fully configured in settings.")
                return {"status": "unconfigured", "emails_fetched": 0, "classified": 0, "meetings": 0}

            logger.info("Starting background sync cycle...")
            
            # 1. Fetch new emails in thread pool to prevent blocking event loop
            loop = asyncio.get_event_loop()
            fetched = await loop.run_in_executor(None, email_client.fetch_new_emails, 20)

            # 2. Process all unclassified emails
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, subject, body FROM emails WHERE is_processed = 0")
                unprocessed = [dict(r) for r in cursor.fetchall()]

            classified_count = 0
            meetings_count = 0

            for em in unprocessed:
                e_id = em["id"]
                subj = em["subject"]
                body = em["body"]

                # Triage
                triage = await loop.run_in_executor(None, gemini_agent.classify_email, subj, body)
                cat = triage.get("category", "business")
                pri = triage.get("priority_score", 5)
                summary = triage.get("summary", "")

                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE emails
                        SET category = ?, priority_score = ?, summary = ?, is_processed = 1
                        WHERE id = ?
                    """, (cat, pri, summary, e_id))
                classified_count += 1

                # Meeting extraction if category is meeting
                if cat == "meeting":
                    meeting_data = await loop.run_in_executor(None, gemini_agent.extract_meeting_details, subj, body)
                    if meeting_data.get("is_meeting"):
                        ev = await loop.run_in_executor(None, calendar_service.generate_ics_event, meeting_data, e_id)
                        if ev:
                            meetings_count += 1

                # Yield control briefly to avoid burst rate limiting
                await asyncio.sleep(0.3)

            summary_result = {
                "status": "success",
                "emails_fetched": len(fetched),
                "classified": classified_count,
                "meetings": meetings_count,
                "timestamp": datetime.now().isoformat()
            }
            logger.info(
                f"Background sync cycle finished: {len(fetched)} emails fetched, "
                f"{classified_count} classified, {meetings_count} calendar events created."
            )
            return summary_result

    async def _loop(self):
        """Infinite async background worker loop."""
        logger.info(f"Background sync worker started (interval: {settings.sync_interval_minutes} mins).")
        while self._is_running:
            try:
                await self.run_sync_cycle()
            except asyncio.CancelledError:
                logger.info("Background sync task cancelled.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in background sync loop: {e}", exc_info=True)

            interval_seconds = max(30, settings.sync_interval_minutes * 60)
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    def start(self):
        """Starts background worker if not already running."""
        if not self._is_running:
            self._is_running = True
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._loop())
            except RuntimeError:
                # No active event loop in current thread (e.g., during synchronous tests)
                self._task = None

    def stop(self):
        """Stops background worker gracefully."""
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def restart(self):
        """Restarts background worker loop to immediately pick up updated settings/intervals."""
        logger.info("Restarting background sync worker with new settings...")
        self.stop()
        self.start()

background_sync = BackgroundSyncService()
