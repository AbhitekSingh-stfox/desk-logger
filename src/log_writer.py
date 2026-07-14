import os
import json
import uuid
import time
import logging
from datetime import datetime, timezone
from tzlocal import get_localzone

logger = logging.getLogger("AIActivityLogger.LogWriter")

# Default log file path resolved under the project root, structured per OS user
import getpass
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USERNAME = getpass.getuser()
DEFAULT_LOG_DIR = os.path.join(PROJECT_ROOT, "logs", USERNAME)
DEFAULT_LOG_FILE = os.path.join(DEFAULT_LOG_DIR, "logs.jsonl")

import threading
import re

_write_lock = threading.Lock()

# Redaction patterns for credential protection
SENSITIVE_PATTERNS = [
    re.compile(r"\b(sk-[a-zA-Z0-9]{48})\b"),                   # OpenAI API keys
    re.compile(r"\b(gsk-[a-zA-Z0-9]{48})\b"),                  # Groq API keys
    re.compile(r"\b(password|passwd|secret|api_key|token)\s*[:=]\s*['\"][a-zA-Z0-9_\-\.\~]{8,}['\"]", re.IGNORECASE) # credentials
]

def redact_sensitive_data(text: str) -> str:
    """Redacts API keys and obvious credentials to prevent security leaks in logs."""
    if not text:
        return text
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED_SENSITIVE_DATA]", redacted)
    return redacted

def clean_text_for_logging(text: str) -> str:
    """Cleans up text for logs: redacts secrets, replaces newlines with space, and collapses whitespace."""
    if not text:
        return text
    redacted = redact_sensitive_data(text)
    # Replace all newlines and carriage returns with a space
    cleaned = redacted.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    # Collapse multiple consecutive spaces
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()

def get_iana_timezone() -> str:
    """Returns the current IANA timezone name."""
    try:
        tz = get_localzone()
        if hasattr(tz, "key") and tz.key:
            return tz.key
        return str(tz)
    except Exception as e:
        logger.warning(f"Error detecting timezone: {e}")
        return "UTC"

def write_log_entry(source: str, conversation_id: str, role: str, content: str, log_file_path: str = DEFAULT_LOG_FILE) -> bool:
    """
    Constructs a schema-compliant log entry and appends it to the logs.jsonl file safely.
    Uses owner-only file permissions on creation.
    """
    content = clean_text_for_logging(content)
    
    # 1. Prepare timestamp data
    now_utc = datetime.now(timezone.utc)
    try:
        local_tz = get_localzone()
        now_local = datetime.now(local_tz)
    except Exception:
        now_local = datetime.now()
        
    entry = {
        "id": str(uuid.uuid4()),
        "source": source.lower().replace(".exe", ""),
        "conversation_id": conversation_id,
        "role": role.strip().lower(),
        "content": content,
        "timestamp_utc": now_utc.isoformat().replace("+00:00", "Z"),
        "timezone": get_iana_timezone(),
        "timestamp_local": now_local.isoformat()
    }

    if entry["role"] not in ("user", "assistant"):
        logger.error(f"Invalid role: {entry['role']}")
        return False

    # 2. Append to log file safely
    log_dir = os.path.dirname(log_file_path)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create directory {log_dir}: {e}")
        return False

    line = json.dumps(entry, ensure_ascii=False) + "\n"
    
    retries = 3
    success = False
    for attempt in range(retries):
        with _write_lock:
            try:
                file_existed = os.path.exists(log_file_path)
                with open(log_file_path, "a", encoding="utf-8") as f:
                    f.write(line)
                if not file_existed:
                    try:
                        os.chmod(log_file_path, 0o600)
                    except Exception:
                        pass
                success = True
                break
            except Exception as e:
                logger.warning(f"Append attempt {attempt + 1} failed: {e}")
                time.sleep(0.1)
                
    return success

def write_combined_log_entry(source: str, conversation_id: str, user_content: str, assistant_content: str, log_file_path: str = DEFAULT_LOG_FILE) -> bool:
    """
    Constructs a combined chat-turn log entry (User prompt + Assistant response)
    and appends it to the logs.jsonl file safely.
    Uses owner-only file permissions on creation.
    """
    user_content = clean_text_for_logging(user_content)
    assistant_content = clean_text_for_logging(assistant_content)

    # 1. Prepare timestamp data
    now_utc = datetime.now(timezone.utc)
    try:
        local_tz = get_localzone()
        now_local = datetime.now(local_tz)
    except Exception:
        now_local = datetime.now()
        
    entry = {
        "id": str(uuid.uuid4()),
        "source": source.lower().replace(".exe", ""),
        "conversation_id": conversation_id,
        "user_content": user_content,
        "assistant_content": assistant_content,
        "timestamp_utc": now_utc.isoformat().replace("+00:00", "Z"),
        "timezone": get_iana_timezone(),
        "timestamp_local": now_local.isoformat()
    }

    # 2. Append to log file safely
    log_dir = os.path.dirname(log_file_path)
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create directory {log_dir}: {e}")
        return False

    line = json.dumps(entry, ensure_ascii=False) + "\n"
    
    retries = 3
    success = False
    for attempt in range(retries):
        with _write_lock:
            try:
                file_existed = os.path.exists(log_file_path)
                with open(log_file_path, "a", encoding="utf-8") as f:
                    f.write(line)
                if not file_existed:
                    try:
                        os.chmod(log_file_path, 0o600)
                    except Exception:
                        pass
                success = True
                break
            except Exception as e:
                logger.warning(f"Append attempt {attempt + 1} failed: {e}")
                time.sleep(0.1)
                
    return success
