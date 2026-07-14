import hashlib
import logging

logger = logging.getLogger("AIActivityLogger.Debouncer")

class MessageDebouncer:
    def __init__(self, debounce_polls: int = 2):
        """
        debounce_polls: Number of consecutive polls the message text must remain
                        unchanged before it is considered finalized.
        """
        self.debounce_polls = debounce_polls
        # Structure: { key: { "text": str, "stable_count": int, "finalized": bool } }
        self.active_messages = {}

    def _get_candidate_key(self, candidate: dict) -> str:
        """Generates a unique key for tracking the candidate element."""
        elem = candidate.get("element")
        text = candidate.get("text", "")
        
        # 1. Attempt to get UIA RuntimeId (unique and stable for active controls)
        if elem:
            try:
                r_id = elem.GetRuntimeId()
                if r_id:
                    # Convert list/tuple of ints to a string key
                    return f"uia_{'_'.join(map(str, r_id))}"
            except Exception:
                pass

        # 2. Fallback to BoundingRectangle
        if elem:
            try:
                rect = elem.BoundingRectangle
                if rect:
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    return f"rect_{rect.left}_{rect.top}_{w}_{h}"
            except Exception:
                pass

        # 3. Last fallback: hash of the initial text snippet
        clean_prefix = text[:100].strip()
        h = hashlib.sha1(clean_prefix.encode("utf-8")).hexdigest()
        return f"text_{h}"

    def process_candidates(self, candidates: list[dict]) -> list[dict]:
        """
        Processes a list of candidates from a poll.
        Returns a list of candidate dicts that have finalized in this poll.
        """
        finalized_candidates = []
        current_keys = set()

        for cand in candidates:
            text = cand.get("text", "").strip()
            if not text:
                continue

            key = self._get_candidate_key(cand)
            current_keys.add(key)

            if key not in self.active_messages:
                # New message candidate detected
                self.active_messages[key] = {
                    "text": text,
                    "stable_count": 0,
                    "finalized": False
                }
                logger.debug(f"New candidate tracked: Key={key[:15]} Text={text[:30]}...")
            else:
                state = self.active_messages[key]
                if state["text"] != text:
                    # Text changed (streaming in-progress)
                    state["text"] = text
                    state["stable_count"] = 0
                    if state["finalized"]:
                        logger.debug(f"Finalized message changed; reopening: Key={key[:15]}")
                        state["finalized"] = False
                else:
                    # Text did not change
                    if not state["finalized"]:
                        state["stable_count"] += 1
                        logger.debug(f"Candidate stable count incremented: Key={key[:15]} Count={state['stable_count']}")
                        
                        if state["stable_count"] >= self.debounce_polls:
                            state["finalized"] = True
                            final_cand = cand.copy()
                            final_cand["key"] = key
                            finalized_candidates.append(final_cand)
                            logger.debug(f"Message finalized: Key={key[:15]} Text={text[:40]}...")

        # Clean up stale keys no longer visible in the UI
        # (e.g. scrolled out of view or conversation cleared)
        stale_keys = [k for k in self.active_messages if k not in current_keys]
        for k in stale_keys:
            del self.active_messages[k]

        return finalized_candidates
