from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException

from backend.config import settings, logger
from backend.database import (
    get_muted_senders,
    add_muted_sender,
    remove_muted_sender
)
from backend.models import (
    SettingsResponse,
    SettingsUpdateRequest,
    MuteSenderRequest,
    MutedSenderResponse
)

from backend.services.background_sync import background_sync
from backend.services.email_client import email_client

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("", response_model=Dict[str, Any])
def get_settings():
    """Returns current configuration status, connection settings, and muted senders."""
    muted = get_muted_senders()
    return {
        "is_configured": settings.is_configured,
        "email_address": settings.email_address,
        "imap_server": settings.imap_server,
        "smtp_server": settings.smtp_server,
        "imap_port": settings.imap_port,
        "smtp_port": settings.smtp_port,
        "gemini_model": settings.gemini_model,
        "sync_interval_minutes": settings.sync_interval_minutes,
        "has_app_password": bool(settings.app_password),
        "has_gemini_api_key": bool(settings.gemini_api_key),
        "muted_senders": muted
    }

@router.post("")
def update_settings(payload: SettingsUpdateRequest):
    """Updates settings and writes them to .env, reloading in-memory config."""
    updates = {}
    if payload.email_address is not None:
        updates["EMAIL_ADDRESS"] = payload.email_address.strip()
    if payload.app_password is not None and payload.app_password != "":
        updates["APP_PASSWORD"] = payload.app_password.strip()
    if payload.imap_server is not None:
        updates["IMAP_SERVER"] = payload.imap_server.strip()
    if payload.smtp_server is not None:
        updates["SMTP_SERVER"] = payload.smtp_server.strip()
    if payload.imap_port is not None:
        updates["IMAP_PORT"] = payload.imap_port
    if payload.smtp_port is not None:
        updates["SMTP_PORT"] = payload.smtp_port
    if payload.gemini_api_key is not None and payload.gemini_api_key != "":
        updates["GEMINI_API_KEY"] = payload.gemini_api_key.strip()
    if payload.sync_interval_minutes is not None:
        updates["SYNC_INTERVAL_MINUTES"] = payload.sync_interval_minutes

    settings.save_settings(updates)
    logger.info("Settings updated and saved to .env")

    # Restart background worker so new interval takes effect immediately
    try:
        background_sync.restart()
    except Exception as e:
        logger.warning(f"Could not restart background sync worker: {e}")

    return {
        "status": "success",
        "is_configured": settings.is_configured,
        "message": "Settings updated successfully."
    }

@router.post("/test-connection")
def test_email_connection():
    """Tests IMAP and SMTP login credentials with clear diagnostics."""
    result = email_client.test_connection()
    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error") or "Authentication failed. Please verify email address and App Password."
        )
    return result

@router.post("/mute", response_model=Dict[str, Any])
def mute_sender(payload: MuteSenderRequest):
    """Adds a sender email address to muted_senders."""
    email_clean = payload.sender_email.strip().lower()
    if not email_clean or "@" not in email_clean:
        raise HTTPException(status_code=400, detail="Invalid email address")

    added = add_muted_sender(email_clean)
    if not added:
        return {"status": "already_muted", "sender_email": email_clean}

    logger.info(f"Muted sender: {email_clean}")
    return {"status": "success", "sender_email": email_clean}

@router.delete("/mute/{sender_email}")
def unmute_sender(sender_email: str):
    """Removes a sender email address from muted_senders."""
    email_clean = sender_email.strip().lower()
    removed = remove_muted_sender(email_clean)
    if not removed:
        raise HTTPException(status_code=404, detail="Muted sender not found")

    logger.info(f"Unmuted sender: {email_clean}")
    return {"status": "success", "sender_email": email_clean}
