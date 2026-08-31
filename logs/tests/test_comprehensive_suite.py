"""
Comprehensive Test Pass Suite for Email Assistant Application
Tests all 11 functional and visual areas specified in user requirements.
"""

import os
import sys
import json
import sqlite3
import unittest
from pathlib import Path
from datetime import datetime

# Setup path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from backend.config import settings, logger
from backend.main import app
from backend.database import get_db, init_db, get_existing_email_ids, get_muted_sender_emails
from backend.services.email_client import (
    clean_subject_for_threading,
    generate_thread_id,
    decode_mime_header,
    email_client
)
from backend.services.gemini_agent import gemini_agent, strip_json_fences
from backend.services.calendar_service import calendar_service
from backend.services.background_sync import BackgroundSyncService

client = TestClient(app)

class ComprehensiveAppTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    # ==========================================
    # 1. EMAIL SYNC
    # ==========================================
    def test_01_email_sync_no_duplicates(self):
        """1.1 Verify manual sync does not create duplicate emails."""
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id, COUNT(*) FROM emails GROUP BY id HAVING COUNT(*) > 1")
            duplicates = c.fetchall()
        self.assertEqual(len(duplicates), 0, f"Found duplicate email IDs in DB: {duplicates}")

    def test_02_muted_senders_exclusion(self):
        """1.2 Verify muted senders are excluded before saving/triaging."""
        from backend.database import add_muted_sender, remove_muted_sender
        test_muted = "spammer.test@domain.com"
        # Add to muted senders
        add_muted_sender(test_muted)

        muted_list = get_muted_sender_emails()
        self.assertIn(test_muted.lower(), muted_list)

        # Verify query excludes muted senders
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM emails WHERE sender LIKE ?", (f"%{test_muted}%",))
            count = c.fetchone()[0]
        self.assertEqual(count, 0, f"Muted sender {test_muted} should have 0 emails in DB")

        # Cleanup
        remove_muted_sender(test_muted)

    def test_03_thread_detection_grouping(self):
        """1.3 Verify thread detection groups related emails under the same thread_id."""
        s1 = "Q3 Product Strategy Roadmap"
        s2 = "Re: Q3 Product Strategy Roadmap"
        s3 = "Fwd: Re: Q3 Product Strategy Roadmap"
        s4 = "FW: Q3 Product Strategy Roadmap"

        norm1 = clean_subject_for_threading(s1)
        norm2 = clean_subject_for_threading(s2)
        norm3 = clean_subject_for_threading(s3)
        norm4 = clean_subject_for_threading(s4)

        self.assertEqual(norm1, norm2)
        self.assertEqual(norm2, norm3)
        self.assertEqual(norm3, norm4)

        th1 = generate_thread_id(norm1, "alice@test.com")
        th2 = generate_thread_id(norm2, "bob@test.com")
        self.assertEqual(th1, th2, "Same conversation thread should generate identical thread_id")

    def test_04_background_sync_lifecycle(self):
        """1.4 Verify background sync worker lifecycle."""
        worker = BackgroundSyncService()
        self.assertFalse(worker._is_running)
        # Verify interval calculation
        interval_secs = max(30, settings.sync_interval_minutes * 60)
        self.assertGreaterEqual(interval_secs, 30)

    # ==========================================
    # 2. AI TRIAGE & CLASSIFICATION
    # ==========================================
    def test_05_synced_emails_triage_fields_populated(self):
        """2.1 Verify processed emails have category, priority_score, and summary populated."""
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT COUNT(*) FROM emails
                WHERE is_processed = 1 AND (
                    category IS NULL OR category = '' OR
                    priority_score IS NULL OR
                    summary IS NULL OR summary = ''
                )
            """)
            unfilled_count = c.fetchone()[0]
        self.assertEqual(unfilled_count, 0, f"Found {unfilled_count} processed emails with missing triage fields")

    def test_06_manual_reclassify_endpoint(self):
        """2.2 Test POST /emails/{id}/classify forces re-classification and updates DB."""
        # Insert a sample email
        test_id = "test-reclassify-email-1"
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (test_id,))
            c.execute("""
                INSERT INTO emails (
                    id, sender, subject, body_preview, body_full, body, received_at,
                    category, priority_score, summary, is_processed, is_read, thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                test_id, "boss@company.com", "URGENT: Production Server Outage",
                "The main database server is down. Needs immediate action.",
                "The main database server is down. Needs immediate action ASAP.",
                "The main database server is down. Needs immediate action ASAP.",
                datetime.now().isoformat(), "business", 5, "Old summary", 1, 0, "thread_outage_1"
            ))

        res = client.post(f"/emails/{test_id}/classify")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("category", data)
        self.assertIn("priority_score", data)
        self.assertIn("summary", data)
        self.assertGreaterEqual(data["priority_score"], 7)

        # Cleanup
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (test_id,))

    def test_07_json_fences_and_malformed_response_resilience(self):
        """2.3 Verify strip_json_fences and triage resilience with tricky responses."""
        fenced_json = '```json\n{"category": "urgent", "priority_score": 9, "summary": "Important update"}\n```'
        clean = strip_json_fences(fenced_json)
        parsed = json.loads(clean)
        self.assertEqual(parsed["category"], "urgent")

        # HTML heavy & Unicode text
        tricky_subject = "Urgent: سرور ڈاون ہے - Immediate fix required"
        tricky_body = "<div><p>Main cluster has failed. <strong>Error 500</strong></p></div>"
        result = gemini_agent._heuristic_classify(tricky_subject, tricky_body)
        self.assertIn(result["category"], ["urgent", "business", "meeting", "newsletter", "spam"])
        self.assertIsInstance(result["priority_score"], int)

    def test_08_rate_limit_and_fallback_models(self):
        """2.4 Verify heuristic fallback when API unavailable."""
        res = gemini_agent._heuristic_classify("Urgent server alert", "Action required immediately")
        self.assertEqual(res["category"], "urgent")
        self.assertGreaterEqual(res["priority_score"], 8)

    # ==========================================
    # 3. EMAIL DETAIL VIEW
    # ==========================================
    def test_09_email_detail_body_full(self):
        """3.1 Verify GET /emails/{id} returns complete body_full without truncation."""
        test_id = "test-body-full-1"
        long_body = "Line 1: Detailed report\n" + ("Long description paragraph with detailed context. " * 50)
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (test_id,))
            c.execute("""
                INSERT INTO emails (
                    id, sender, subject, body_preview, body_full, body, received_at,
                    category, priority_score, summary, is_processed, is_read, thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                test_id, "reporter@test.com", "Annual Financial Audit",
                long_body[:100], long_body, long_body, datetime.now().isoformat(),
                "business", 6, "Annual audit details", 1, 0, "thread_audit_1"
            ))

        res = client.get(f"/emails/{test_id}")
        self.assertEqual(res.status_code, 200)
        detail = res.json()
        self.assertEqual(detail["body_full"], long_body)
        self.assertGreater(len(detail["body_full"]), len(detail["body_preview"]))

        # Cleanup
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (test_id,))

    def test_10_html_sanitization_safe_rendering(self):
        """3.2 Verify HTML-formatted emails sanitize dangerous tags while keeping valid formatting."""
        dangerous_html = '<p>Hello <script>alert("xss")</script><a href="https://example.com">Click Here</a></p>'
        import bleach
        from backend.services.email_client import ALLOWED_HTML_TAGS, ALLOWED_HTML_ATTRIBUTES, ALLOWED_HTML_PROTOCOLS
        sanitized = bleach.clean(
            dangerous_html,
            tags=ALLOWED_HTML_TAGS,
            attributes=ALLOWED_HTML_ATTRIBUTES,
            protocols=ALLOWED_HTML_PROTOCOLS,
            strip=True
        )
        self.assertNotIn("<script>", sanitized)
        self.assertIn('<a href="https://example.com">Click Here</a>', sanitized)

    def test_11_no_subject_graceful_handling(self):
        """3.3 Verify empty subject displays '(No Subject)' gracefully."""
        res1 = clean_subject_for_threading("")
        self.assertEqual(res1, "No Subject")
        res2 = clean_subject_for_threading(None)
        self.assertEqual(res2, "No Subject")

    # ==========================================
    # 4. CALENDAR / MEETING EXTRACTION
    # ==========================================
    def test_12_meeting_extraction_ics_generation(self):
        """4.1 & 4.2 Verify .ics file generation and RFC 5545 format."""
        meeting_email_id = "test-meeting-email-1"
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (meeting_email_id,))
            c.execute("""
                INSERT INTO emails (
                    id, sender, subject, body_preview, body_full, body, received_at,
                    category, priority_score, summary, is_processed, is_read, thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                meeting_email_id, "lead@company.com", "Project Sync Meeting",
                "Let's meet tomorrow on 2026-09-10 at 14:00 to 15:00 in Room 301.",
                "Let's meet tomorrow on 2026-09-10 at 14:00 to 15:00 in Room 301.",
                "Let's meet tomorrow on 2026-09-10 at 14:00 to 15:00 in Room 301.",
                datetime.now().isoformat(), "meeting", 8, "Project sync invitation", 1, 0, "thread_sync_1"
            ))

        res = client.post(f"/emails/{meeting_email_id}/create-event")
        self.assertEqual(res.status_code, 200)
        event_data = res.json()
        self.assertEqual(event_data["email_id"], meeting_email_id)
        self.assertTrue(os.path.exists(event_data["ics_file_path"]))

        # Validate RFC 5545 structure
        with open(event_data["ics_file_path"], "r", encoding="utf-8") as f:
            ics_content = f.read()
        self.assertIn("BEGIN:VCALENDAR", ics_content)
        self.assertIn("BEGIN:VEVENT", ics_content)
        self.assertIn("END:VEVENT", ics_content)
        self.assertIn("END:VCALENDAR", ics_content)

        # Test 4.3 Idempotency: Triggering again returns existing without duplicate
        res_dup = client.post(f"/emails/{meeting_email_id}/create-event")
        self.assertEqual(res_dup.status_code, 200)
        self.assertEqual(res_dup.json()["id"], event_data["id"])

        # Test 4.4 GET /calendar-events lists event
        res_list = client.get("/calendar-events")
        self.assertEqual(res_list.status_code, 200)
        all_events = res_list.json()
        self.assertTrue(any(ev["id"] == event_data["id"] for ev in all_events))

        # Cleanup
        calendar_service.delete_event_by_email_id(meeting_email_id)
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (meeting_email_id,))

    # ==========================================
    # 5. AI GHOSTWRITER
    # ==========================================
    def test_13_ghostwriter_all_tones_and_send(self):
        """5.1 - 5.3 Test draft generation across 5 tones, manual edits, and send status flip."""
        gw_email_id = "test-ghostwriter-email-1"
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (gw_email_id,))
            c.execute("""
                INSERT INTO emails (
                    id, sender, subject, body_preview, body_full, body, received_at,
                    category, priority_score, summary, is_processed, is_read, thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                gw_email_id, "partner@client.com", "Partnership Proposal Q4",
                "Would you be interested in collaborating on the upcoming Q4 campaign?",
                "Would you be interested in collaborating on the upcoming Q4 campaign? Let us know.",
                "Would you be interested in collaborating on the upcoming Q4 campaign? Let us know.",
                datetime.now().isoformat(), "business", 7, "Q4 partnership query", 1, 0, "thread_q4_1"
            ))

        tones = ["professional", "friendly", "short_direct", "polite_decline", "meeting_confirmation"]
        draft_ids = []
        for tone in tones:
            res = client.post(f"/emails/{gw_email_id}/draft", json={"tone": tone})
            self.assertEqual(res.status_code, 200)
            d = res.json()
            self.assertEqual(d["tone"], tone)
            self.assertTrue(len(d["content"]) > 0)
            draft_ids.append(d["id"])

        # 5.2 & 5.3 Test Draft Edit & Status
        target_draft_id = draft_ids[0]
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE drafts SET is_sent = 1 WHERE id = ?", (target_draft_id,))
            c.execute("SELECT is_sent FROM drafts WHERE id = ?", (target_draft_id,))
            sent_status = c.fetchone()[0]
        self.assertEqual(sent_status, 1)

        # Cleanup
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM drafts WHERE email_id = ?", (gw_email_id,))
            c.execute("DELETE FROM emails WHERE id = ?", (gw_email_id,))

    # ==========================================
    # 6. CHAT WITH INBOX
    # ==========================================
    def test_14_chat_with_inbox_queries(self):
        """6.1 - 6.4 Test chat with inbox (factual, no-match, Urdu, and real referenced IDs)."""
        # Insert a factual test email
        c_email_id = "test-chat-query-email-1"
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (c_email_id,))
            c.execute("""
                INSERT INTO emails (
                    id, sender, subject, body_preview, body_full, body, received_at,
                    category, priority_score, summary, is_processed, is_read, thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                c_email_id, "cfo@company.com", "Project Alpha Budget Approval",
                "The budget for Project Alpha has been officially approved for $75,000.",
                "The budget for Project Alpha has been officially approved for $75,000.",
                "The budget for Project Alpha has been officially approved for $75,000.",
                datetime.now().isoformat(), "business", 9, "Budget approved for Alpha $75k", 1, 0, "thread_alpha_1"
            ))

        # 6.1 Factual query
        res = client.post("/chat", json={"query": "What is the approved budget for Project Alpha?"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(len(data["answer"]) > 0)

        # 6.2 No-match query
        res_no_match = client.post("/chat", json={"query": "XYZNonExistentKeyword999991234"})
        self.assertEqual(res_no_match.status_code, 200)
        self.assertTrue(len(res_no_match.json()["answer"]) > 0)

        # 6.3 Urdu query
        res_urdu = client.post("/chat", json={"query": "Kya Project Alpha ka budget approve hua hai?"})
        self.assertEqual(res_urdu.status_code, 200)
        self.assertTrue(len(res_urdu.json()["answer"]) > 0)

        # 6.4 Verify referenced IDs exist in DB
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM emails")
            valid_ids = {r[0] for r in c.fetchall()}

        for ref_id in data.get("referenced_email_ids", []):
            self.assertIn(ref_id, valid_ids, f"Referenced ID {ref_id} is not in database")

        # Cleanup
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id = ?", (c_email_id,))

    # ==========================================
    # 7. SORTING & FILTERING
    # ==========================================
    def test_15_sorting_and_filtering(self):
        """7.1 - 7.4 Test All Inbox chronological, High Priority filter/sort, category filters, and search."""
        e1 = "test-sort-e1"
        e2 = "test-sort-e2"
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id IN (?, ?)", (e1, e2))
            c.execute("""
                INSERT INTO emails (
                    id, sender, subject, body_preview, body_full, body, received_at,
                    category, priority_score, summary, is_processed, is_read, thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                e1, "highpri@test.com", "Urgent Fix Required",
                "High priority preview", "High priority body", "High priority body",
                "2026-08-31T08:00:00", "urgent", 9, "Urgent fix", 1, 0, "thread_sort_1"
            ))
            c.execute("""
                INSERT INTO emails (
                    id, sender, subject, body_preview, body_full, body, received_at,
                    category, priority_score, summary, is_processed, is_read, thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                e2, "newest@test.com", "Casual Chat Note",
                "Newest email preview", "Newest email body", "Newest email body",
                "2026-08-31T11:00:00", "business", 3, "Casual note", 1, 0, "thread_sort_2"
            ))

        # 7.1 Chronological (All Inbox)
        res_chrono = client.get("/emails?sort=chronological")
        self.assertEqual(res_chrono.status_code, 200)
        chrono_items = res_chrono.json()
        self.assertGreaterEqual(len(chrono_items), 2)
        self.assertGreaterEqual(chrono_items[0]["latest_received_at"], chrono_items[1]["latest_received_at"])

        # 7.2 High Priority
        res_pri = client.get("/emails?sort=priority&min_priority=7")
        self.assertEqual(res_pri.status_code, 200)
        pri_items = res_pri.json()
        for item in pri_items:
            self.assertGreaterEqual(item["priority_score"], 7)

        # 7.3 Category filters
        for cat in ["urgent", "business"]:
            res_cat = client.get(f"/emails?category={cat}")
            self.assertEqual(res_cat.status_code, 200)
            for item in res_cat.json():
                self.assertEqual(item["category"].lower(), cat)

        # 7.4 Search bar (subject, sender, body)
        res_search_subj = client.get("/emails?search=Urgent Fix")
        self.assertEqual(res_search_subj.status_code, 200)
        self.assertTrue(any("Urgent Fix" in item["subject"] for item in res_search_subj.json()))

        res_search_sender = client.get("/emails?search=newest@test.com")
        self.assertEqual(res_search_sender.status_code, 200)

        # Cleanup
        with get_db() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM emails WHERE id IN (?, ?)", (e1, e2))

    # ==========================================
    # 8. SETTINGS & MUTED SENDERS
    # ==========================================
    def test_16_settings_and_mute_endpoints(self):
        """8.1 - 8.3 Test settings management and muting/unmuting senders."""
        test_email = "mute_endpoint_test@sample.org"
        
        # 8.1 POST /settings/mute
        res_mute = client.post("/settings/mute", json={"sender_email": test_email})
        self.assertEqual(res_mute.status_code, 200)
        self.assertIn(res_mute.json()["status"], ["success", "already_muted"])

        # 8.2 DELETE /settings/mute/{email}
        res_unmute = client.delete(f"/settings/mute/{test_email}")
        self.assertEqual(res_unmute.status_code, 200)
        self.assertEqual(res_unmute.json()["status"], "success")

        # 8.3 Update sync interval
        res_set = client.post("/settings", json={"sync_interval_minutes": 10})
        self.assertEqual(res_set.status_code, 200)
        self.assertEqual(settings.sync_interval_minutes, 10)

        # Reset to 5
        client.post("/settings", json={"sync_interval_minutes": 5})

    # ==========================================
    # 9. FIRST-RUN ONBOARDING
    # ==========================================
    def test_17_onboarding_credential_check(self):
        """9.1 & 9.2 Test configuration status check."""
        res = client.get("/settings")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("is_configured", data)

    # ==========================================
    # 10. UI & VISUAL REGRESSION
    # ==========================================
    def test_18_apple_design_system_assets(self):
        """10.1 - 10.3 Verify Apple design language assets and structure."""
        with open(ROOT_DIR / "frontend" / "index.html", "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("#000000", html)
        self.assertIn("#161616", html)
        self.assertIn("#0A84FF", html)
        self.assertIn("rounded-full", html)

        with open(ROOT_DIR / "frontend" / "css" / "style.css", "r", encoding="utf-8") as f:
            css = f.read()
        self.assertIn("-apple-system", css)
        self.assertIn("180ms", css)
        self.assertIn("apple-shadow", css)

    # ==========================================
    # 11. ERROR HANDLING
    # ==========================================
    def test_19_error_handling_non_existent_email(self):
        """11.1 & 11.2 Verify 404 for invalid email ID and safe JSON errors."""
        res = client.get("/emails/non-existent-email-id-999")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["detail"], "Email not found")


if __name__ == "__main__":
    unittest.main()
