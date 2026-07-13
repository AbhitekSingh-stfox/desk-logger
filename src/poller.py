import time
import logging
import threading
import os
import json
import uiautomation as auto
from src import process_matcher, chat_pane_locator, role_detector, log_writer
from src.debouncer import MessageDebouncer
from src.deduplicator import MessageDeduplicator
from src.conversation_tracker import ConversationTracker

logger = logging.getLogger("AIActivityLogger.Poller")

class PollingEngine:
    def __init__(self, apps_config_path: str, adapters_config_path: str, settings_path: str):
        self.apps_config_path = apps_config_path
        self.adapters_config_path = adapters_config_path
        self.settings_path = settings_path
        
        # Load settings
        self.settings = self._load_settings()
        
        # Initialize sub-modules
        debounce_polls = self.settings.get("debounce_polls", 2)
        idle_timeout = self.settings.get("idle_timeout_minutes", 30)
        
        self.debouncer = MessageDebouncer(debounce_polls=debounce_polls)
        self.deduplicator = MessageDeduplicator()
        self.tracker = ConversationTracker(idle_timeout_minutes=idle_timeout)
        
        # Load existing hashes on startup so we don't log them again
        from src.log_writer import DEFAULT_LOG_FILE
        self.deduplicator.load_existing_hashes(DEFAULT_LOG_FILE)
        
        # In-process toggle state
        self.is_logging_active = True
        
        # Thread control
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        
        # Track last logged roles by conversation_id to guide the fallback alternation
        self._last_roles = {}
        
        # Buffer pending user messages before pairing with assistant response
        self._pending_user = {}
        
        # Keep track of active PIDs to clean up sessions on termination
        self._active_pids = set()
        
        # Process scanning cache optimization
        self._cached_targets = []
        self._last_process_scan_time = 0.0

    def _load_settings(self) -> dict:
        """Loads settings configuration file."""
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading settings file: {e}")
        return {
            "poll_interval_seconds": 1.5,
            "idle_timeout_minutes": 30,
            "min_text_length": 10,
            "debounce_polls": 2,
            "ignored_text_patterns": []
        }

    def start(self):
        """Starts the polling loop in a background daemon thread."""
        with self._lock:
            if self._running:
                logger.warning("Poller is already running.")
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="LoggerPollerThread")
            self._thread.start()
            logger.info("Polling engine started in background thread.")

    def stop(self):
        """Stops the polling loop."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            logger.info("Polling engine stopped.")

    def _run_loop(self):
        """Main background loop."""
        import ctypes
        ctypes.windll.ole32.CoInitialize(None)
        
        # Switch this background thread to Default desktop ONCE on startup
        from src.desktop_helper import switch_thread_to_default_desktop
        switch_thread_to_default_desktop()
        
        # UIA calls on a background thread may require COM initialization.
        auto.SetGlobalSearchTimeout(1.0)
        
        while True:
            # Check running state safely
            with self._lock:
                if not self._running:
                    break
                logging_active = self.is_logging_active

            # Reload settings dynamically if needed (optional, keeping it robust)
            self.settings = self._load_settings()
            poll_interval = self.settings.get("poll_interval_seconds", 1.5)

            if not logging_active:
                # Logging is paused by system tray toggle. Go to sleep.
                time.sleep(poll_interval)
                continue

            try:
                self._poll_step()
            except Exception as e:
                logger.error(f"Error during poll step: {e}", exc_info=True)

            time.sleep(poll_interval)

    def _poll_step(self):
        """Executes a single polling iteration across running target apps."""
        # 1. Enumerate active processes matching configuration (with throttled full scans to save CPU)
        import psutil
        now = time.time()
        if now - self._last_process_scan_time > 10.0 or not self._cached_targets:
            self._cached_targets = process_matcher.get_running_targets(self.apps_config_path)
            self._last_process_scan_time = now
            if self._cached_targets:
                logger.info(f"Active target apps detected (full scan): {self._cached_targets}")
        else:
            # Lightweight verification of already matched PIDs to save CPU
            valid_targets = []
            for target in self._cached_targets:
                try:
                    if psutil.pid_exists(target["pid"]):
                        valid_targets.append(target)
                except Exception:
                    pass
            self._cached_targets = valid_targets

        running_targets = self._cached_targets
        
        current_pids = {t["pid"] for t in running_targets}
        
        # Clean up trackers for processes that ended
        terminated_pids = self._active_pids - current_pids
        for pid in terminated_pids:
            # Find any sessions matching this pid and clean up
            to_remove = []
            for (proc_name, sess_pid) in list(self.tracker.sessions.keys()):
                if sess_pid == pid:
                    to_remove.append((proc_name, sess_pid))
            for key in to_remove:
                conv_id = self.tracker.sessions[key]["conversation_id"]
                self.tracker.remove_session(*key)
                self.deduplicator.clear_conversation(conv_id)
                if conv_id in self._last_roles:
                    del self._last_roles[conv_id]
        
        self._active_pids = current_pids

        # 2. Process each running target
        for target in running_targets:
            pid = target["pid"]
            name = target["name"]

            # Load adapter configuration (if any)
            adapter_config = None
            if os.path.exists(self.adapters_config_path):
                try:
                    with open(self.adapters_config_path, "r", encoding="utf-8") as f:
                        adapters = json.load(f)
                        adapter_config = adapters.get(name)
                except Exception:
                    pass

            # Fetch active window reference
            window = chat_pane_locator.find_window_by_pid(pid)
            if not window:
                continue

            try:
                window_title = window.Name
            except Exception:
                window_title = ""

            # Locate candidate message text blocks
            candidates = chat_pane_locator.locate_messages(pid, name, self.adapters_config_path, self.settings)
            
            # Pass candidates to debouncer
            finalized = self.debouncer.process_candidates(candidates)
            
            if not finalized:
                continue

            # Process finalized messages
            for msg in finalized:
                content = msg["text"]
                elem = msg["element"]

                # Fetch unique conversation ID
                conv_id = self.tracker.get_conversation_id(name, pid, window_title)

                # Deduplication check
                source_name = name.lower().replace(".exe", "")
                if self.deduplicator.is_duplicate(conv_id, content, source=source_name):
                    continue

                # Determine sender role
                prev_role = self._last_roles.get(conv_id)
                role = role_detector.detect_role(
                    candidate=msg,
                    previous_role=prev_role,
                    adapter_config=adapter_config,
                    reference_control=window
                )

                # Handle combined user and assistant message pairs
                if role == "user":
                    self._pending_user[conv_id] = {
                        "text": content,
                        "timestamp": time.time()
                    }
                    self.deduplicator.mark_logged(conv_id, content)
                    self.tracker.update_activity(name, pid)
                    self._last_roles[conv_id] = "user"
                    logger.info(f"[{name}] Detected and buffered pending user message: '{content[:35]}...'")
                
                elif role == "assistant":
                    # Retrieve pending user message for this conversation
                    pending = self._pending_user.pop(conv_id, None)
                    user_text = pending["text"] if pending else ""
                    
                    # Write combined turn log entry
                    success = log_writer.write_combined_log_entry(
                        source=name,
                        conversation_id=conv_id,
                        user_content=user_text,
                        assistant_content=content
                    )
                    
                    if success:
                        self.deduplicator.mark_logged(conv_id, content)
                        self.tracker.update_activity(name, pid)
                        self._last_roles[conv_id] = "assistant"
                        logger.info(f"[{name}] Logged turn (User: '{user_text[:25]}...' | Assistant: '{content[:25]}...')")
