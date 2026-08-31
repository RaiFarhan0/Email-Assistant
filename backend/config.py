import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
LOGS_DIR = BASE_DIR / "logs"
CALENDAR_DIR = BASE_DIR / "calendar_events"
DB_PATH = BASE_DIR / "email_assistant.db"

# Ensure runtime directories exist
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CALENDAR_DIR.mkdir(parents=True, exist_ok=True)

# Load environment variables
load_dotenv(dotenv_path=ENV_FILE)

class Settings:
    def __init__(self):
        self.reload()

    def reload(self):
        load_dotenv(dotenv_path=ENV_FILE, override=True)
        self.email_address = os.getenv("EMAIL_ADDRESS", "").strip()
        self.app_password = os.getenv("APP_PASSWORD", "").strip().replace(" ", "")
        self.imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com").strip()
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
        self.gemini_fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite").strip()
        self.sync_interval_minutes = int(os.getenv("SYNC_INTERVAL_MINUTES", "5"))
        custom_db = os.getenv("EMAIL_ASSISTANT_DB") or os.getenv("TEST_DB_PATH")
        self.db_path = str(Path(custom_db).resolve()) if custom_db else str(DB_PATH)
        custom_cal = os.getenv("CALENDAR_DIR")
        self.calendar_dir = str(Path(custom_cal).resolve()) if custom_cal else str(CALENDAR_DIR)
        self.logs_dir = str(LOGS_DIR)

    @property
    def is_configured(self) -> bool:
        """Returns True if essential email and AI credentials are present."""
        return bool(self.email_address and self.app_password and self.gemini_api_key)

    def save_settings(self, updates: dict):
        """Updates .env file and reloads in-memory configuration."""
        current_env = {}
        if ENV_FILE.exists():
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        current_env[k.strip()] = v.strip()

        for key, val in updates.items():
            if val is not None:
                current_env[key] = str(val).strip()

        with open(ENV_FILE, "w", encoding="utf-8") as f:
            for k, v in current_env.items():
                f.write(f"{k}={v}\n")

        self.reload()

settings = Settings()

# Setup logging
logger = logging.getLogger("email_assistant")
logger.setLevel(logging.INFO)

# Avoid duplicate handlers on re-import
if not logger.handlers:
    log_file = LOGS_DIR / "app.log"
    file_handler = RotatingFileHandler(
        str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
