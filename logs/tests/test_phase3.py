import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.gemini_agent import strip_json_fences, gemini_agent

def test_phase3():
    print("Testing Phase 3: Gemini Agent & Defensive Parsers...")

    # 1. Test markdown json strip
    raw_markdown = "```json\n{\n  \"category\": \"urgent\",\n  \"priority_score\": 9,\n  \"summary\": \"Production database CPU is at 99%.\"\n}\n```"
    cleaned = strip_json_fences(raw_markdown)
    assert "\"category\": \"urgent\"" in cleaned
    assert not cleaned.startswith("```")
    print("  [x] Markdown fence stripper verified.")

    # 2. Test fallback behavior when no API key is provided
    # Classification fallback
    res = gemini_agent.classify_email("Urgent Bug", "App crashing on checkout")
    assert "category" in res
    assert "priority_score" in res
    assert "summary" in res
    assert 1 <= res["priority_score"] <= 10
    print("  [x] Classification fallback robustness verified.")

    # Meeting extraction fallback
    meeting_res = gemini_agent.extract_meeting_details("Team Catchup", "Let us sync next month sometime")
    assert "is_meeting" in meeting_res
    assert isinstance(meeting_res["attendees"], list)
    print("  [x] Meeting extraction fallback verified.")

    # Ghostwriter reply fallback
    reply = gemini_agent.generate_reply("Can you send the report?", "short_direct")
    assert isinstance(reply, str) and len(reply) > 0
    print("  [x] Ghostwriter fallback verified.")

    # Chat with inbox empty context
    chat_empty = gemini_agent.chat_with_inbox("When is the meeting?", [])
    assert "couldn't find" in chat_empty.lower() or "nahi mili" in chat_empty.lower()
    print("  [x] Chat With Inbox empty context verified.")

    # 3. Test compose_new_email and detect_compose_intent
    from backend.services.gemini_agent import compose_new_email
    draft = compose_new_email(
        recipient="partner@corp.com",
        context="Let them know Q4 financial reports are ready for review.",
        tone="professional"
    )
    assert "subject" in draft and len(draft["subject"]) > 0
    assert "body" in draft and len(draft["body"]) > 0
    print("  [x] compose_new_email top-level & method verified.")

    # Intent detection: compose vs search vs reply
    compose_intent = gemini_agent.detect_compose_intent("Send an email to john@example.com telling him the meeting is delayed")
    assert compose_intent is not None
    assert compose_intent["is_compose"] is True
    assert compose_intent["recipient"] == "john@example.com"
    print("  [x] Compose intent detection (English) verified.")

    urdu_compose_intent = gemini_agent.detect_compose_intent("ali@example.com ko email likho ke kal meeting 3 baje hogi")
    assert urdu_compose_intent is not None
    assert urdu_compose_intent["is_compose"] is True
    assert urdu_compose_intent["recipient"] == "ali@example.com"
    print("  [x] Compose intent detection (Urdu) verified.")

    search_intent = gemini_agent.detect_compose_intent("What did Sarah say in her email?")
    assert search_intent is None or search_intent.get("is_compose") is False
    print("  [x] Non-compose search intent separation verified.")

    print("Phase 3 verified successfully!")

if __name__ == "__main__":
    test_phase3()
