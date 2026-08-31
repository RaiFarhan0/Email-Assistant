import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings, logger

# Use separate test database
TEST_DB = Path(__file__).resolve().parent / "test_email_assistant.db"
settings.db_path = str(TEST_DB)

from backend.database import init_db, get_db, add_muted_sender, get_muted_senders, remove_muted_sender
from backend.models import EmailResponse, ClassifyResponse, DraftResponse

def test_phase1():
    print("Testing Phase 1: Database and Models...")
    if TEST_DB.exists():
        TEST_DB.unlink()
    init_db()
    
    # Test muted_senders CRUD
    test_email = "spammer@example.com"
    added = add_muted_sender(test_email)
    assert added is True, "Failed to add muted sender"
    
    muted_list = get_muted_senders()
    assert any(m["sender_email"] == test_email for m in muted_list), "Muted sender not found in list"
    
    removed = remove_muted_sender(test_email)
    assert removed is True, "Failed to remove muted sender"
    
    # Test Pydantic model serialization
    classify_obj = ClassifyResponse(
        category="urgent",
        priority_score=9,
        summary="Server alert critical outage detected."
    )
    assert classify_obj.category == "urgent"
    assert classify_obj.priority_score == 9
    
    print("Phase 1 verified successfully!")

if __name__ == "__main__":
    test_phase1()
