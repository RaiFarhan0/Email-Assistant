from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

# --- Email Models ---
CategoryType = Literal["urgent", "business", "meeting", "newsletter", "spam"]
ToneType = Literal["professional", "friendly", "short_direct", "polite_decline", "meeting_confirmation"]

class EmailBase(BaseModel):
    id: str
    sender: str
    subject: str
    body_preview: str
    body_full: Optional[str] = None
    body_html: Optional[str] = None
    received_at: datetime
    category: Optional[str] = None
    priority_score: Optional[int] = None
    summary: Optional[str] = None
    is_processed: bool = False
    is_read: bool = False
    thread_id: Optional[str] = None

class EmailResponse(EmailBase):
    pass

class CalendarEventResponse(BaseModel):
    id: int
    email_id: str
    title: str
    date: str
    start_time: str
    end_time: str
    location: Optional[str] = None
    attendees: List[str] = []
    ics_file_path: str
    created_at: datetime

class CalendarEventWithEmailResponse(CalendarEventResponse):
    email_subject: Optional[str] = None
    email_sender: Optional[str] = None

class DraftResponse(BaseModel):
    id: int
    email_id: str
    tone: str
    content: str
    created_at: datetime
    is_sent: bool = False

class EmailDetailResponse(EmailBase):
    body: str
    body_full: Optional[str] = None
    body_html: Optional[str] = None
    thread_emails: List[EmailResponse] = []
    calendar_events: List[CalendarEventResponse] = []
    drafts: List[DraftResponse] = []

class EmailThreadResponse(BaseModel):
    thread_id: str
    subject: str
    category: Optional[str] = None
    priority_score: Optional[int] = None
    latest_received_at: datetime
    emails: List[EmailResponse] = []
    unread_count: int = 0

# --- AI Models ---
class ClassifyResponse(BaseModel):
    category: CategoryType
    priority_score: int = Field(ge=1, le=10)
    summary: str

class MeetingExtractionResponse(BaseModel):
    is_meeting: bool
    title: Optional[str] = ""
    date: Optional[str] = ""
    start_time: Optional[str] = ""
    end_time: Optional[str] = ""
    location: Optional[str] = ""
    attendees: List[str] = []

class GenerateDraftRequest(BaseModel):
    tone: ToneType = "professional"

class SendDraftRequest(BaseModel):
    content: Optional[str] = None

class EmailDraftPayload(BaseModel):
    recipient: str = ""
    subject: str = ""
    body: str = ""
    tone: str = "professional"

class SendEmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    in_reply_to: Optional[str] = None

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    query: str
    answer: str
    referenced_email_ids: List[str] = []
    draft: Optional[EmailDraftPayload] = None
    is_compose: bool = False

# --- Settings & Muted Senders Models ---
class SettingsResponse(BaseModel):
    is_configured: bool
    email_address: str
    imap_server: str
    smtp_server: str
    imap_port: int
    smtp_port: int
    gemini_model: str
    sync_interval_minutes: int
    muted_senders_count: int
    has_app_password: bool
    has_gemini_api_key: bool

class SettingsUpdateRequest(BaseModel):
    email_address: Optional[str] = None
    app_password: Optional[str] = None
    imap_server: Optional[str] = None
    smtp_server: Optional[str] = None
    imap_port: Optional[int] = None
    smtp_port: Optional[int] = None
    gemini_api_key: Optional[str] = None
    sync_interval_minutes: Optional[int] = None

class MuteSenderRequest(BaseModel):
    sender_email: str

class MutedSenderResponse(BaseModel):
    id: int
    sender_email: str
    muted_at: datetime
