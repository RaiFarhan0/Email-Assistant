import re
import email
import hashlib
import smtplib
import socket
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr, parsedate_to_datetime
from typing import List, Dict, Any, Optional, Tuple
import bleach
from bs4 import BeautifulSoup
from imapclient import IMAPClient

from backend.config import settings, logger
from backend.database import get_db, get_existing_email_ids, get_muted_sender_emails

ALLOWED_HTML_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li', 'ol',
    'strong', 'ul', 'p', 'br', 'span', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'hr', 'pre', 'img', 'sub', 'sup',
    'font', 'center', 'small'
]

ALLOWED_HTML_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    '*': ['class', 'color', 'align', 'valign', 'dir', 'lang']
}

ALLOWED_HTML_PROTOCOLS = ['http', 'https', 'mailto', 'data', 'cid']

def clean_subject_for_threading(subject: str) -> str:
    """Removes Re:, Fwd:, FW:, etc. prefixes and normalizes whitespace."""
    if not subject:
        return "No Subject"
    cleaned = subject.strip()
    pattern = re.compile(r'^(re|fwd|fw|aw|antw|wg)\s*:\s*', re.IGNORECASE)
    while pattern.match(cleaned):
        cleaned = pattern.sub('', cleaned).strip()
    return cleaned if cleaned else "No Subject"

def generate_thread_id(normalized_subject: str, sender_email: str) -> str:
    """Generates a stable thread_id based on normalized subject."""
    # Grouping by normalized subject provides standard conversational thread grouping
    key = normalized_subject.lower().strip()
    return f"thread_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"

def decode_mime_header(header_value: Optional[str]) -> str:
    """Decodes MIME encoded header strings into unicode."""
    if not header_value:
        return ""
    decoded_fragments = []
    try:
        for text, encoding in decode_header(header_value):
            if isinstance(text, bytes):
                try:
                    decoded_fragments.append(text.decode(encoding or "utf-8", errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    decoded_fragments.append(text.decode("latin1", errors="replace"))
            else:
                decoded_fragments.append(str(text))
    except Exception as e:
        logger.warning(f"Error decoding header '{header_value}': {e}")
        return str(header_value)
    return "".join(decoded_fragments).strip()

def extract_email_body(msg: email.message.Message) -> Tuple[str, str, Optional[str]]:
    """
    Extracts plain text full body, preview, and sanitized HTML body from email message.
    Returns (body_full, body_preview, body_html).
    """
    plain_text_parts = []
    html_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Skip attachments
            if "attachment" in content_disposition:
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                payload = part.get_payload()

            if not payload:
                continue

            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("latin1", errors="replace")
            elif isinstance(payload, str):
                text = payload
            else:
                continue

            if content_type == "text/plain":
                plain_text_parts.append(text)
            elif content_type == "text/html":
                html_parts.append(text)
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload is None:
            payload = msg.get_payload()

        if payload:
            if isinstance(payload, bytes):
                charset = msg.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("latin1", errors="replace")
            elif isinstance(payload, str):
                text = payload
            else:
                text = str(payload)
                
            if content_type == "text/html":
                html_parts.append(text)
            else:
                plain_text_parts.append(text)

    body_html: Optional[str] = None
    if html_parts:
        raw_html = "\n\n".join(html_parts)
        try:
            # Decompose script and style tags so executable/style content does not leak into body
            soup_pre = BeautifulSoup(raw_html, "html.parser")
            for elem in soup_pre(["script", "style", "head", "title", "meta"]):
                elem.decompose()
            cleaned_pre = str(soup_pre)

            # Sanitize HTML with bleach
            sanitized = bleach.clean(
                cleaned_pre,
                tags=ALLOWED_HTML_TAGS,
                attributes=ALLOWED_HTML_ATTRIBUTES,
                protocols=ALLOWED_HTML_PROTOCOLS,
                strip=True
            )
            # Ensure links have target="_blank" and rel="noopener noreferrer"
            soup_clean = BeautifulSoup(sanitized, "html.parser")
            for a_tag in soup_clean.find_all('a'):
                a_tag['target'] = '_blank'
                a_tag['rel'] = 'noopener noreferrer'
            body_html = str(soup_clean)
        except Exception as e:
            logger.warning(f"Failed to sanitize HTML email body with bleach: {e}")
            body_html = raw_html

    if plain_text_parts:
        body_full = "\n\n".join(plain_text_parts).strip()
    elif html_parts:
        # Strip HTML to readable plain text
        try:
            soup = BeautifulSoup("\n\n".join(html_parts), "html.parser")
            # Remove scripts and styles
            for elem in soup(["script", "style", "head", "title", "meta", "[document]"]):
                elem.extract()
            body_full = soup.get_text(separator="\n").strip()
            # Collapse excessive empty lines
            body_full = re.sub(r'\n\s*\n', '\n\n', body_full)
        except Exception as e:
            logger.warning(f"Failed to parse HTML email body: {e}")
            body_full = re.sub(r'<[^>]+>', ' ', "\n\n".join(html_parts)).strip()
    else:
        body_full = "(Empty email body)"

    body_preview = body_full[:500].strip()
    return body_full, body_preview, body_html

def parse_raw_email(uid: str, raw_bytes: bytes, existing_thread_lookup: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Parses raw email bytes into an email record dictionary."""
    try:
        msg = email.message_from_bytes(raw_bytes)
        
        # Sender
        raw_from = decode_mime_header(msg.get("From", ""))
        sender_name, sender_email = parseaddr(raw_from)
        sender_display = f"{sender_name} <{sender_email}>" if sender_name else (sender_email or "Unknown Sender")
        
        # Subject
        raw_subject = decode_mime_header(msg.get("Subject", "(No Subject)"))
        clean_subject = clean_subject_for_threading(raw_subject)
        
        # Date
        date_header = msg.get("Date")
        if date_header:
            try:
                received_dt = parsedate_to_datetime(date_header)
                if received_dt.tzinfo is None:
                    received_dt = received_dt.replace(tzinfo=timezone.utc)
            except Exception:
                received_dt = datetime.now(timezone.utc)
        else:
            received_dt = datetime.now(timezone.utc)
            
        received_at_iso = received_dt.isoformat()

        # Body
        body_full, body_preview, body_html = extract_email_body(msg)

        # Threading
        thread_id = generate_thread_id(clean_subject, sender_email)

        return {
            "id": str(uid),
            "sender": sender_display,
            "sender_email": sender_email.lower().strip(),
            "subject": raw_subject,
            "body_preview": body_preview,
            "body_full": body_full,
            "body_html": body_html,
            "body": body_full,
            "received_at": received_at_iso,
            "thread_id": thread_id,
            "category": None,
            "priority_score": None,
            "summary": None,
            "is_processed": 0,
            "is_read": 0
        }
    except Exception as e:
        logger.error(f"Error parsing email UID {uid}: {e}")
        return None

class EmailClient:
    """IMAP & SMTP Client for Email Assistant."""

    def __init__(self):
        self.last_error: Optional[str] = None

    def _connect_imap(self) -> Optional[IMAPClient]:
        """Connects to IMAP server with 1 retry on failure."""
        self.last_error = None
        if not settings.email_address or not settings.app_password:
            self.last_error = "Email credentials (EMAIL_ADDRESS or APP_PASSWORD) not configured."
            logger.warning(f"IMAP sync skipped: {self.last_error}")
            return None

        for attempt in range(2):
            try:
                server = IMAPClient(
                    settings.imap_server,
                    port=settings.imap_port,
                    ssl=True,
                    timeout=20.0
                )
                server.login(settings.email_address, settings.app_password)
                return server
            except Exception as e:
                self.last_error = str(e)
                logger.warning(f"IMAP connection attempt {attempt + 1} failed: {e}")
                if attempt == 1:
                    logger.error(f"Failed to connect to IMAP server {settings.imap_server} after 2 attempts: {e}")
                    return None
        return None

    def test_connection(self) -> Dict[str, Any]:
        """Tests IMAP and SMTP login credentials without performing email sync."""
        if not settings.email_address or not settings.app_password:
            return {"success": False, "imap_ok": False, "smtp_ok": False, "error": "Email address or App Password is missing."}

        imap_ok = False
        smtp_ok = False
        errors = []

        # 1. Test IMAP
        try:
            server = IMAPClient(
                settings.imap_server,
                port=settings.imap_port,
                ssl=True,
                timeout=15.0
            )
            server.login(settings.email_address, settings.app_password)
            server.logout()
            imap_ok = True
        except Exception as e:
            errors.append(f"IMAP Error: {e}")

        # 2. Test SMTP
        try:
            if settings.smtp_port == 465:
                with smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=15.0) as smtp:
                    smtp.login(settings.email_address, settings.app_password)
            else:
                with smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=15.0) as smtp:
                    smtp.starttls()
                    smtp.login(settings.email_address, settings.app_password)
            smtp_ok = True
        except Exception as e:
            errors.append(f"SMTP Error: {e}")

        success = imap_ok and smtp_ok
        return {
            "success": success,
            "imap_ok": imap_ok,
            "smtp_ok": smtp_ok,
            "error": "; ".join(errors) if errors else None
        }

    def fetch_new_emails(self, limit: int = 20, raise_on_error: bool = False) -> List[Dict[str, Any]]:
        """
        Fetches unread + last 24h emails, skipping existing UIDs and muted senders.
        Inserts new emails into SQLite with is_processed = 0.
        """
        if not settings.email_address or not settings.app_password:
            msg = "Email credentials not set. Skipping fetch."
            logger.info(msg)
            if raise_on_error:
                raise RuntimeError(msg)
            return []

        server = self._connect_imap()
        if not server:
            if raise_on_error:
                raise RuntimeError(self.last_error or f"Failed to authenticate with IMAP server {settings.imap_server}.")
            return []

        new_emails_inserted = []
        try:
            server.select_folder("INBOX", readonly=True)
            
            # Fetch existing IDs & muted senders from DB to avoid redundant processing
            existing_ids = get_existing_email_ids()
            muted_senders = get_muted_sender_emails()

            # Search: UNSEEN or SINCE last 24h
            since_date = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
            try:
                unread_uids = server.search(["UNSEEN"])
            except Exception:
                unread_uids = []

            try:
                recent_uids = server.search(["SINCE", since_date])
            except Exception:
                recent_uids = []

            all_target_uids = list(dict.fromkeys(unread_uids + recent_uids))
            
            # Filter out already fetched UIDs
            unfetched_uids = [uid for uid in all_target_uids if str(uid) not in existing_ids]

            # Fetch in batches up to limit
            unfetched_uids = unfetched_uids[-limit:] if len(unfetched_uids) > limit else unfetched_uids
            
            if not unfetched_uids:
                logger.info("No new emails to fetch.")
                server.logout()
                return []

            logger.info(f"Fetching {len(unfetched_uids)} new email messages from IMAP...")
            messages = server.fetch(unfetched_uids, ["RFC822"])

            for uid, msg_data in messages.items():
                raw_bytes = msg_data.get(b"RFC822")
                if not raw_bytes:
                    continue

                parsed = parse_raw_email(str(uid), raw_bytes)
                if not parsed:
                    continue

                # Filter out muted senders before DB insert and AI quota usage
                if parsed["sender_email"] in muted_senders:
                    logger.info(f"Skipping email UID {uid} from muted sender: {parsed['sender_email']}")
                    continue

            # Insert into DB
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR IGNORE INTO emails (
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
                new_emails_inserted.append(parsed)

            logger.info(f"Successfully fetched and stored {len(new_emails_inserted)} new emails.")

            # Backfill existing emails missing body_full or body_html if available on IMAP
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM emails WHERE body_full IS NULL OR body_full = '' OR body_html IS NULL")
                missing_body_rows = cursor.fetchall()
                missing_uids = [int(r["id"]) for r in missing_body_rows if str(r["id"]).isdigit()]

            if missing_uids:
                try:
                    logger.info(f"Backfilling {len(missing_uids)} existing emails missing full body / HTML...")
                    backfill_msgs = server.fetch(missing_uids[:20], ["RFC822"])
                    with get_db() as conn:
                        cursor = conn.cursor()
                        for b_uid, b_data in backfill_msgs.items():
                            b_raw = b_data.get(b"RFC822")
                            if b_raw:
                                b_parsed = parse_raw_email(str(b_uid), b_raw)
                                if b_parsed:
                                    cursor.execute("""
                                        UPDATE emails
                                        SET body_full = ?, body_html = ?, body = ?
                                        WHERE id = ?
                                    """, (b_parsed["body_full"], b_parsed["body_html"], b_parsed["body"], str(b_uid)))
                    logger.info("Backfill of existing emails completed.")
                except Exception as b_err:
                    logger.warning(f"Error during email body backfill: {b_err}")
        except Exception as e:
            logger.error(f"Error during email fetch: {e}")
        finally:
            try:
                server.logout()
            except Exception:
                pass

        return new_emails_inserted

    def send_email(self, to_email: str, subject: str, body: str, in_reply_to: Optional[str] = None) -> bool:
        """
        Sends an email using SMTP SSL (or STARTTLS) with 1 retry on connection failure.
        """
        if not settings.email_address or not settings.app_password:
            logger.error("SMTP error: Email credentials not configured.")
            return False

        msg = MIMEMultipart("alternative")
        msg["From"] = settings.email_address
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        msg.attach(MIMEText(body, "plain", "utf-8"))

        for attempt in range(2):
            try:
                if settings.smtp_port == 465:
                    with smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=20.0) as smtp:
                        smtp.login(settings.email_address, settings.app_password)
                        smtp.sendmail(settings.email_address, [to_email], msg.as_string())
                else:
                    with smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=20.0) as smtp:
                        smtp.starttls()
                        smtp.login(settings.email_address, settings.app_password)
                        smtp.sendmail(settings.email_address, [to_email], msg.as_string())

                logger.info(f"Successfully sent email to {to_email} (Subject: {subject})")
                return True
            except Exception as e:
                logger.warning(f"SMTP send attempt {attempt + 1} failed: {e}")
                if attempt == 1:
                    logger.error(f"Failed to send email to {to_email} after 2 attempts: {e}")
                    return False
        return False

email_client = EmailClient()
