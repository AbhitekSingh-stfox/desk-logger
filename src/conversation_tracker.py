import uuid
import time
import logging

logger = logging.getLogger("AIActivityLogger.ConversationTracker")

class ConversationTracker:
    def __init__(self, idle_timeout_minutes: float = 30.0):
        self.idle_timeout_seconds = idle_timeout_minutes * 60.0
        # Structure: { (process_name, pid): { "conversation_id": str, "last_title": str, "last_activity_time": float } }
        self.sessions = {}

    def get_conversation_id(self, process_name: str, pid: int, window_title: str) -> str:
        """
        Retrieves or generates a unique conversation_id for the target process.
        Resets the conversation_id if:
        1. The window title changes (indicating a different chat session or tab).
        2. The idle period expires (no new activity recorded).
        """
        key = (process_name, pid)
        now = time.time()
        
        # Normalize title to avoid minor spacing variations causing resets
        normalized_title = (window_title or "").strip()

        if key not in self.sessions:
            # First time seeing this process instance
            conv_id = str(uuid.uuid4())
            self.sessions[key] = {
                "conversation_id": conv_id,
                "last_title": normalized_title,
                "last_activity_time": now
            }
            logger.info(f"Initialized conversation session for {process_name} (PID: {pid}): ID={conv_id}")
            return conv_id

        session = self.sessions[key]
        conv_id = session["conversation_id"]
        title_changed = session["last_title"] != normalized_title
        idle_expired = (now - session["last_activity_time"]) > self.idle_timeout_seconds

        if title_changed or idle_expired:
            new_conv_id = str(uuid.uuid4())
            reason = "title change" if title_changed else "idle timeout"
            logger.info(
                f"Resetting conversation session for {process_name} (PID: {pid}) due to {reason}. "
                f"Old ID={conv_id}, New ID={new_conv_id}"
            )
            session["conversation_id"] = new_conv_id
            session["last_title"] = normalized_title
            session["last_activity_time"] = now
            return new_conv_id

        return conv_id

    def update_activity(self, process_name: str, pid: int):
        """Updates the last activity timestamp for a active conversation session."""
        key = (process_name, pid)
        if key in self.sessions:
            self.sessions[key]["last_activity_time"] = time.time()
            logger.debug(f"Updated activity timestamp for {process_name} (PID: {pid})")
            
    def remove_session(self, process_name: str, pid: int):
        """Cleans up session information when a process terminates."""
        key = (process_name, pid)
        if key in self.sessions:
            del self.sessions[key]
            logger.info(f"Removed session tracker for terminated process {process_name} (PID: {pid})")
