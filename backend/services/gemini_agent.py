import json
import re
import time
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError

from backend.config import settings, logger
from backend.database import get_db

def strip_json_fences(raw_text: str) -> str:
    """Strips markdown code fences (```json ... ```) and extracts valid JSON string."""
    if not raw_text:
        return ""
    text = raw_text.strip()
    # Remove markdown code block fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    # Extract outer JSON object if extra text exists
    match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

class GeminiAgent:
    """AI agent powering triage classification, meeting extraction, ghostwriter, and inbox RAG-lite."""

    def __init__(self):
        self._client: Optional[genai.Client] = None
        self._cached_api_key: str = ""

    def get_client(self) -> Optional[genai.Client]:
        """Returns initialized Google GenAI client or None if API key is missing."""
        api_key = settings.gemini_api_key.strip()
        if not api_key:
            return None
        if self._client is None or self._cached_api_key != api_key:
            self._client = genai.Client(api_key=api_key)
            self._cached_api_key = api_key
        return self._client

    def _call_with_retry(self, prompt: str, system_instruction: Optional[str] = None, json_mode: bool = False) -> Optional[str]:
        """
        Executes a Gemini call with backoff retry on 429/rate-limit errors
        and fallback to backup model (e.g., gemini-1.5-flash).
        """
        client = self.get_client()
        if not client:
            logger.warning("Gemini API call skipped: GEMINI_API_KEY is not configured.")
            return None

        models_to_try = [
            settings.gemini_model,
            settings.gemini_fallback_model,
            "gemini-2.5-flash"
        ]
        # Remove duplicates while preserving order
        models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))

        config_args = {"temperature": 0.2}
        if system_instruction:
            config_args["system_instruction"] = system_instruction
        if json_mode:
            config_args["response_mime_type"] = "application/json"

        config = types.GenerateContentConfig(**config_args)

        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config
                    )
                    if response and response.text:
                        return response.text.strip()
                except Exception as e:
                    err_msg = str(e).lower()
                    if ("429" in err_msg or "resource_exhausted" in err_msg or "rate limit" in err_msg) and attempt == 0:
                        logger.warning(f"Gemini rate limit hit (model={model_name}), backing off 1.5s before retry...")
                        time.sleep(1.5)
                        continue
                    logger.warning(f"Gemini API error (model={model_name}, attempt={attempt+1}): {e}")
                    break

        logger.error("Gemini API call failed after trying all fallback models.")
        return None

    def _heuristic_classify(self, subject: str, body: str) -> Dict[str, Any]:
        """Local rule-based fallback classification when AI API is unavailable."""
        text = f"{subject} {body}".lower()
        subj_clean = subject.strip() if subject else "General Email"

        if any(k in text for k in ["urgent", "action required", "asap", "immediate", "critical", "emergency", "alert"]):
            return {"category": "urgent", "priority_score": 9, "summary": subj_clean[:75]}
        if any(k in text for k in ["meeting", "zoom", "google meet", "calendar", "invite", "invitation", "reschedule", "appointment"]):
            return {"category": "meeting", "priority_score": 8, "summary": subj_clean[:75]}
        if any(k in text for k in ["newsletter", "unsubscribe", "weekly digest", "daily digest", "marketing", "promotion", "special offer", "discount"]):
            return {"category": "newsletter", "priority_score": 3, "summary": subj_clean[:75]}
        if any(k in text for k in ["order", "receipt", "confirmed", "shipping", "shipped", "invoice", "payment", "shopify", "daraz", "amazon", "tracking"]):
            return {"category": "business", "priority_score": 7, "summary": subj_clean[:75]}
        if any(k in text for k in ["congratulations", "lottery", "winner", "crypto bonus", "viagra"]):
            return {"category": "spam", "priority_score": 1, "summary": subj_clean[:75]}

        return {"category": "business", "priority_score": 5, "summary": subj_clean[:75]}

    def classify_email(self, subject: str, body: str) -> Dict[str, Any]:
        """
        Classifies email into category, priority score (1-10), and a 1-sentence summary (max 15 words).
        Returns parsed dictionary with defensive fallback.
        """
        system_prompt = (
            "You are an expert email triage assistant. Classify the given email into exactly ONE category: "
            "'urgent', 'business', 'meeting', 'newsletter', or 'spam'. "
            "Assign a priority score from 1 (lowest) to 10 (highest priority/critical). "
            "Write a single sentence summary of maximum 15 words. "
            "Output strictly valid JSON with keys: category, priority_score, summary. Do not output markdown code fences or other text."
        )

        user_content = f"Subject: {subject}\n\nBody Preview/Content:\n{body[:2000]}"

        raw_output = self._call_with_retry(
            prompt=user_content,
            system_instruction=system_prompt,
            json_mode=True
        )

        if not raw_output:
            return self._heuristic_classify(subject, body)

        try:
            cleaned = strip_json_fences(raw_output)
            data = json.loads(cleaned)

            category = str(data.get("category", "business")).lower().strip()
            if category not in ["urgent", "business", "meeting", "newsletter", "spam"]:
                category = "business"

            try:
                priority = int(data.get("priority_score", 5))
                priority = max(1, min(10, priority))
            except (ValueError, TypeError):
                priority = 5

            summary = str(data.get("summary", "No summary provided")).strip()
            # Enforce short summary constraint
            words = summary.split()
            if len(words) > 20:
                summary = " ".join(words[:15]) + "..."

            return {
                "category": category,
                "priority_score": priority,
                "summary": summary
            }
        except Exception as e:
            logger.warning(f"Failed to parse Gemini classification JSON: {e}. Raw was: {raw_output}")
            return self._heuristic_classify(subject, body)

    def extract_meeting_details(self, subject: str, body: str) -> Dict[str, Any]:
        """
        Extracts structured meeting details if a meeting is confirmed/scheduled.
        Returns:
        {
          "is_meeting": bool,
          "title": str,
          "date": "YYYY-MM-DD",
          "start_time": "HH:MM",
          "end_time": "HH:MM",
          "location": str,
          "attendees": list[str]
        }
        """
        fallback = {
            "is_meeting": False,
            "title": "",
            "date": "",
            "start_time": "",
            "end_time": "",
            "location": "",
            "attendees": []
        }

        system_prompt = (
            "You are a calendar scheduling assistant. Analyze the email subject and body to determine if a specific meeting, event, or appointment with a date and time is proposed or scheduled. "
            "If the email specifies or proposes a clear date and start time, set is_meeting to true and extract title, date (YYYY-MM-DD), start_time (HH:MM in 24h format), end_time (HH:MM in 24h format, or 1 hour after start if not specified), location (or 'Virtual/Online' if none specified), and attendees (list of email addresses or names). "
            "CRITICAL: If you cannot confidently extract a specific date and time, set is_meeting to false. Do not guess or hallucinate. "
            "Output strictly valid JSON with keys: is_meeting, title, date, start_time, end_time, location, attendees."
        )

        user_content = f"Subject: {subject}\n\nEmail Content:\n{body[:2500]}"

        raw_output = self._call_with_retry(
            prompt=user_content,
            system_instruction=system_prompt,
            json_mode=True
        )

        if not raw_output:
            return fallback

        try:
            cleaned = strip_json_fences(raw_output)
            data = json.loads(cleaned)

            is_meeting = bool(data.get("is_meeting", False))
            date_str = str(data.get("date", "")).strip()
            start_time = str(data.get("start_time", "")).strip()
            end_time = str(data.get("end_time", "")).strip()

            # Validate date format YYYY-MM-DD
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                is_meeting = False

            # Validate time format HH:MM
            if not re.match(r"^\d{1,2}:\d{2}$", start_time):
                is_meeting = False

            if not is_meeting:
                return fallback

            # Normalize start_time and end_time
            if len(start_time) == 4:  # H:MM -> 0H:MM
                start_time = f"0{start_time}"
            if not end_time or not re.match(r"^\d{1,2}:\d{2}$", end_time):
                try:
                    sh, sm = map(int, start_time.split(":"))
                    eh = (sh + 1) % 24
                    end_time = f"{eh:02d}:{sm:02d}"
                except Exception:
                    end_time = "10:00"

            attendees = data.get("attendees", [])
            if isinstance(attendees, str):
                attendees = [attendees]
            elif not isinstance(attendees, list):
                attendees = []

            return {
                "is_meeting": True,
                "title": str(data.get("title") or subject).strip(),
                "date": date_str,
                "start_time": start_time,
                "end_time": end_time,
                "location": str(data.get("location") or "Virtual / Video Call").strip(),
                "attendees": attendees
            }
        except Exception as e:
            logger.warning(f"Failed to parse meeting details JSON: {e}")
            return fallback

    def generate_reply(self, email_content: str, tone: str, sender: str = "", subject: str = "") -> str:
        """
        Generates an email response draft using baked prompt templates for 5 tones:
        - professional
        - friendly
        - short_direct
        - polite_decline
        - meeting_confirmation
        """
        tone_templates = {
            "professional": (
                "Write a professional, polished, and courteous email response. "
                "Maintain clear communication, structured paragraphs, appropriate business salutations, and a formal closing."
            ),
            "friendly": (
                "Write a warm, engaging, and friendly email reply. "
                "Be approachable, conversational, supportive, and cheerful while staying helpful and clear."
            ),
            "short_direct": (
                "Write an ultra-concise, direct, and actionable email response. "
                "Get straight to the point in 2-3 sentences or bullet points without fluff or unnecessary filler."
            ),
            "polite_decline": (
                "Write a polite, appreciative, and firm decline to the request, invitation, or proposal. "
                "Express gratitude for the opportunity, explain that you are unable to proceed at this time, and wish them the best."
            ),
            "meeting_confirmation": (
                "Write an email acknowledging and confirming the proposed meeting or call. "
                "Confirm that the time works, express looking forward to discussing the topics, and ask if any preparation materials are required."
            )
        }

        instructions = tone_templates.get(tone, tone_templates["professional"])
        system_prompt = (
            f"You are an executive AI email ghostwriter. {instructions} "
            "Do not include placeholder brackets like '[Your Name]' or '[Company]' — write naturally. "
            "Output only the body of the reply email ready to send."
        )

        user_content = (
            f"Original Sender: {sender}\n"
            f"Original Subject: {subject}\n\n"
            f"Original Email:\n{email_content}"
        )

        raw_output = self._call_with_retry(
            prompt=user_content,
            system_instruction=system_prompt,
            json_mode=False
        )

        if not raw_output:
            return "Thank you for your email. I have received your message and will get back to you shortly."

        return raw_output.strip()

    def compose_new_email(self, recipient: str, context: str, tone: str = "professional") -> Dict[str, str]:
        """
        Generates a new email draft (subject + body) based on user instructions and desired tone.
        Returns {"subject": str, "body": str}.
        """
        first_line = context.strip().split("\n")[0] if context else "Follow-up"
        fallback_subject = re.sub(r'^(about|regarding|re:|for|to|that)\s+', '', first_line, flags=re.IGNORECASE).strip()
        fallback_subject = fallback_subject[:60].capitalize() if fallback_subject else "New Message"
        
        recipient_salutation = recipient.split('@')[0].replace('.', ' ').title() if '@' in recipient else (recipient or "there")
        fallback_body = f"Hi {recipient_salutation},\n\n{context}\n\nBest regards,"

        tone_instructions = {
            "professional": "Write in a polished, courteous, and professional business tone with clear paragraphs and a formal closing.",
            "friendly": "Write in a warm, friendly, conversational, and encouraging tone.",
            "short_direct": "Write in an ultra-concise, direct, and actionable tone in 2-3 clear sentences.",
            "polite_decline": "Write in a polite, respectful, and appreciative decline tone.",
            "meeting_confirmation": "Write in a clear, constructive meeting confirmation tone."
        }.get(tone, "Write in a professional, courteous business tone.")

        system_prompt = (
            f"You are an executive AI email assistant. The user wants to compose a brand new email.\n"
            f"Tone: {tone_instructions}\n"
            "Generate a concise, natural email subject line and the complete email body.\n"
            "Return valid JSON only with exactly two keys: 'subject' (a clear subject line) and 'body' (the complete email body ready to send).\n"
            "Do not include placeholder brackets like '[Your Name]' or '[Company]' — write naturally and ready to send."
        )

        user_prompt = (
            f"Recipient: {recipient or 'Not specified'}\n"
            f"Context / Message details:\n{context}\n"
            f"Tone: {tone}"
        )

        raw_output = self._call_with_retry(
            prompt=user_prompt,
            system_instruction=system_prompt,
            json_mode=True
        )

        if not raw_output:
            return {"subject": fallback_subject, "body": fallback_body}

        try:
            cleaned = strip_json_fences(raw_output)
            data = json.loads(cleaned)
            subject = str(data.get("subject") or fallback_subject).strip()
            body = str(data.get("body") or fallback_body).strip()
            return {"subject": subject, "body": body}
        except Exception as e:
            logger.warning(f"Failed to parse compose_new_email output: {e}")
            return {"subject": fallback_subject, "body": fallback_body}

    def _local_rag_fallback(self, query: str, emails_context: List[Dict[str, Any]]) -> str:
        """Local RAG synthesizer when Gemini API quota is temporarily exhausted or network is offline."""
        if not emails_context:
            return "Aap ke inbox mein is hawale se koi email nahi mili. (No matching emails found in your inbox.)"

        urdu_tokens = {
            'kya', 'koi', 'hai', 'hain', 'tha', 'thi', 'the', 'aya', 'ayi', 'aye', 'hua', 'karein',
            'karo', 'batao', 'ha', 'mein', 'ka', 'ki', 'ke', 'mujhe', 'mera', 'meri', 'kahan', 'kab'
        }
        words = set(re.findall(r'\w+', query.lower()))
        is_urdu = bool(words & urdu_tokens)

        lines = []
        if is_urdu:
            lines.append(f"Aap ke sawal ke mutabiq inbox mein **{len(emails_context)}** email(s) mili hain:\n")
            for em in emails_context[:5]:
                subj = em.get('subject', 'No Subject')
                sender = em.get('sender', 'Unknown')
                summary = em.get('summary') or em.get('body_preview', '')[:120]
                lines.append(f"• **{subj}**\n  - **Sender:** `{sender}`\n  - **Details:** {summary}")
        else:
            lines.append(f"Found **{len(emails_context)}** relevant email(s) in your inbox:\n")
            for em in emails_context[:5]:
                subj = em.get('subject', 'No Subject')
                sender = em.get('sender', 'Unknown')
                summary = em.get('summary') or em.get('body_preview', '')[:120]
                lines.append(f"• **{subj}**\n  - **Sender:** `{sender}`\n  - **Details:** {summary}")

        return "\n".join(lines)

    def _heuristic_detect_compose_intent(self, query: str) -> Optional[Dict[str, Any]]:
        """Rule-based heuristic detection for compose new email intent."""
        q_lower = query.lower().strip()
        
        # Exclude queries asking to search, list, or inspect existing inbox emails
        if any(q_lower.startswith(w) for w in ["what", "did", "show", "find", "search", "check", "summarize", "list", "read", "kya", "konsi", "kiska", "kaun"]):
            if not any(k in q_lower for k in ["draft", "compose", "write an email", "send an email", "email likho", "email draft", "email bhejo"]):
                return None

        # Exclude reply to existing thread
        if re.search(r'\breply\b|\bjawab\b', q_lower):
            return None

        compose_patterns = [
            r'\b(?:compose|draft|write|send|prepare)\s+(?:an?\s+)?(?:new\s+)?(?:email|mail|message)\b',
            r'\b(?:email|mail)\s+(?:to\s+[\w\.-]+@|[\w\.-]+@)',
            r'\b(?:email|mail)\s+(?:draft|likho|bhejo|banao|send)\b',
            r'[\w\.-]+@[\w\.-]+\.\w+.*?\b(?:ko\s+email|ko\s+mail)\b',
            r'\b(?:send\s+email|send\s+mail)\b'
        ]

        has_compose_intent = any(re.search(p, q_lower) for p in compose_patterns)
        if not has_compose_intent:
            return None

        # Extract tone
        tone = "professional"
        if "friendly" in q_lower or "warm" in q_lower:
            tone = "friendly"
        elif any(t in q_lower for t in ["short", "direct", "concise", "brief"]):
            tone = "short_direct"
        elif any(t in q_lower for t in ["polite decline", "decline", "reject"]):
            tone = "polite_decline"
        elif any(t in q_lower for t in ["meeting confirmation", "confirm meeting", "confirming"]):
            tone = "meeting_confirmation"
        elif "formal" in q_lower or "professional" in q_lower:
            tone = "professional"

        # Extract recipient email or name
        email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', query)
        recipient = email_match.group(1) if email_match else ""

        if not recipient:
            name_match = re.search(r'\b(?:to|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', query)
            if name_match:
                recipient = name_match.group(1)
            else:
                urdu_name_match = re.search(r'([A-Z][a-z]+)\s+ko\b', query)
                if urdu_name_match:
                    recipient = urdu_name_match.group(1)

        # Clean context
        cleaned_context = re.sub(
            r'^(?:please\s+)?(?:can\s+you\s+)?(?:compose|draft|write|send|prepare)\s+(?:an?\s+)?(?:new\s+)?(?:email|mail)?\s*(?:to\s+[^\s,]+)?\s*(?:with\s+tone\s+\w+)?\s*(?:about|telling|saying|regarding|that|for|asking|with)?\s*',
            '',
            query,
            flags=re.IGNORECASE
        ).strip()

        if not cleaned_context:
            cleaned_context = query

        return {
            "is_compose": True,
            "recipient": recipient,
            "context": cleaned_context,
            "tone": tone
        }

    def detect_compose_intent(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Determines whether the chat query expresses intent to compose/write/send a NEW email.
        Returns parsed dict with {is_compose, recipient, context, tone} or None.
        """
        system_prompt = (
            "You are an intent classifier for an email assistant chat.\n"
            "Determine if the user is instructing to compose, draft, write, or send a NEW email (NOT replying to an existing email, and NOT asking questions to search the inbox).\n"
            "If it is intent to compose a new email, output JSON:\n"
            "{\n"
            '  "is_compose": true,\n'
            '  "recipient": "extracted email or name or empty string",\n'
            '  "context": "the message instruction or what the email should be about",\n'
            '  "tone": "professional" | "friendly" | "short_direct" | "polite_decline" | "meeting_confirmation"\n'
            "}\n"
            "If it is NOT composing a new email, output JSON:\n"
            '{"is_compose": false}\n'
            "Output strictly valid JSON with no markdown."
        )

        raw_output = self._call_with_retry(
            prompt=f"User query: {query}",
            system_instruction=system_prompt,
            json_mode=True
        )

        if not raw_output:
            return self._heuristic_detect_compose_intent(query)

        try:
            cleaned = strip_json_fences(raw_output)
            data = json.loads(cleaned)
            if data.get("is_compose"):
                recipient = str(data.get("recipient") or "").strip()
                # If Gemini missed extracting recipient, try regex
                if not recipient:
                    email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', query)
                    if email_match:
                        recipient = email_match.group(1)
                
                tone = str(data.get("tone") or "professional").strip()
                if tone not in ["professional", "friendly", "short_direct", "polite_decline", "meeting_confirmation"]:
                    tone = "professional"

                context = str(data.get("context") or query).strip()
                return {
                    "is_compose": True,
                    "recipient": recipient,
                    "context": context,
                    "tone": tone
                }
            return None
        except Exception as e:
            logger.warning(f"Error parsing compose intent JSON: {e}")
            return self._heuristic_detect_compose_intent(query)

    def chat_with_inbox(self, query: str, emails_context: List[Dict[str, Any]]) -> str:
        """
        RAG-lite synthesis for Chat With Inbox. Supports English and Urdu natural language queries.
        Uses retrieved email snippets as grounded context.
        """
        if not emails_context:
            return "I couldn't find any relevant emails in your inbox matching your inquiry. (Aap ke inbox mein is hawale se koi email nahi mili)."

        context_blocks = []
        for idx, em in enumerate(emails_context, start=1):
            context_blocks.append(
                f"[Email {idx}]\n"
                f"ID: {em.get('id')}\n"
                f"Sender: {em.get('sender')}\n"
                f"Subject: {em.get('subject')}\n"
                f"Date: {em.get('received_at')}\n"
                f"Category: {em.get('category')}\n"
                f"Summary: {em.get('summary')}\n"
                f"Content:\n{em.get('body', em.get('body_preview', ''))[:1000]}\n"
            )

        full_context = "\n---\n".join(context_blocks)

        system_prompt = (
            "You are an AI inbox assistant. Answer the user's question accurately using ONLY the provided email records below. "
            "You support English and Urdu (including Roman Urdu / mixed languages). Respond naturally in the language or style used by the user. "
            "If the information is not present in the provided emails, explicitly state that the inbox does not contain this information — do NOT hallucinate. "
            "Cite relevant email subjects or senders when answering."
        )

        user_prompt = f"User Question: {query}\n\nEmails Context:\n{full_context}"

        raw_output = self._call_with_retry(
            prompt=user_prompt,
            system_instruction=system_prompt,
            json_mode=False
        )

        if not raw_output:
            return self._local_rag_fallback(query, emails_context)

        return raw_output.strip()

gemini_agent = GeminiAgent()

def compose_new_email(recipient: str, context: str, tone: str = "professional") -> Dict[str, str]:
    """
    Top-level helper function to generate a new email draft (subject + body).
    """
    return gemini_agent.compose_new_email(recipient=recipient, context=context, tone=tone)

