import hashlib
import logging
import threading

logger = logging.getLogger("AIActivityLogger.Deduplicator")

class MessageDeduplicator:
    def __init__(self):
        # Structure: { conversation_id: set(sha1_hex_strings) }
        self._conversation_hashes = {}
        # Structure: { source: last_conversation_id_str }
        self._last_conversation_id = {}
        self._lock = threading.Lock()

    def load_existing_hashes(self, log_file_path: str):
        """Loads already logged message hashes from the logs.jsonl file into memory on startup."""
        import os
        import json
        
        if not os.path.exists(log_file_path):
            return

        try:
            count = 0
            with open(log_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        conv_id = record.get("conversation_id")
                        source = record.get("source")
                        user_content = record.get("user_content")
                        assistant_content = record.get("assistant_content")
                        content = record.get("content")  # fallback for old simple format
                        
                        if conv_id:
                            with self._lock:
                                if conv_id not in self._conversation_hashes:
                                    self._conversation_hashes[conv_id] = set()
                                
                                if user_content:
                                    self._conversation_hashes[conv_id].add(self._get_hash(user_content))
                                if assistant_content:
                                    self._conversation_hashes[conv_id].add(self._get_hash(assistant_content))
                                if content:
                                    self._conversation_hashes[conv_id].add(self._get_hash(content))
                                    
                                if source:
                                    self._last_conversation_id[source] = conv_id
                            count += 1
                    except Exception:
                        continue
            logger.info(f"Loaded {count} existing message hashes from {log_file_path} on startup.")
        except Exception as e:
            logger.warning(f"Failed to load existing hashes from log file: {e}")

    def _get_hash(self, content: str) -> str:
        """Computes the SHA-1 hash of the normalized (trimmed) content."""
        normalized = content.strip()
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

    def is_duplicate(self, conversation_id: str, content: str, source: str = None) -> bool:
        """
        Checks if the message text hash has already been logged.
        If this is a new session with no logged messages yet, we also check the last logged session
        for this source to prevent duplicate history logging on restart.
        """
        h = self._get_hash(content)
        with self._lock:
            # Check if already in current session
            hashes = self._conversation_hashes.get(conversation_id)
            if hashes and h in hashes:
                return True
                
            # If current session has NO messages logged yet, check last session
            if not hashes or len(hashes) == 0:
                if source:
                    last_conv_id = self._last_conversation_id.get(source)
                    if last_conv_id and last_conv_id != conversation_id:
                        last_hashes = self._conversation_hashes.get(last_conv_id)
                        if last_hashes and h in last_hashes:
                            logger.debug(f"Duplicate check matched last session {last_conv_id} for source {source}")
                            return True
        return False

    def mark_logged(self, conversation_id: str, content: str):
        """
        Adds the message text hash to the conversation's set of logged hashes.
        """
        h = self._get_hash(content)
        with self._lock:
            if conversation_id not in self._conversation_hashes:
                self._conversation_hashes[conversation_id] = set()
            self._conversation_hashes[conversation_id].add(h)
            logger.debug(f"Logged hash added for conversation {conversation_id}: {h[:10]}")

    def clear_conversation(self, conversation_id: str):
        """Removes the stored hashes for a specific conversation to free memory."""
        with self._lock:
            if conversation_id in self._conversation_hashes:
                del self._conversation_hashes[conversation_id]
                logger.debug(f"Cleared hash set for conversation {conversation_id}")
