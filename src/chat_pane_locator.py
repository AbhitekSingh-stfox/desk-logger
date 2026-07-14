import json
import os
import logging
import uiautomation as auto

logger = logging.getLogger("AIActivityLogger.ChatPaneLocator")

# Map of control type name strings to uiautomation control classes
CONTROL_TYPE_MAP = {
    "Document": auto.DocumentControl,
    "Pane": auto.PaneControl,
    "Edit": auto.EditControl,
    "Custom": auto.CustomControl,
    "List": auto.ListControl,
    "ListItem": auto.ListItemControl,
    "Text": auto.TextControl,
    "Group": auto.GroupControl,
    "Window": auto.WindowControl,
    "Button": auto.ButtonControl,
}

def find_window_by_pid(pid: int) -> auto.WindowControl:
    """Finds the top-level WindowControl belonging to a process ID."""
    root = auto.GetRootControl()
    for child in root.GetChildren():
        try:
            if child.ProcessId == pid:
                # Found the top-level window
                return child
        except Exception:
            continue
    return None

def matches_selector(control, selector: dict) -> bool:
    """Helper to check if a control matches a selector, supporting substring matches for string values."""
    if not selector:
        return False
    try:
        for prop, expected in selector.items():
            if prop == "ControlType":
                actual = control.ControlTypeName
                if expected not in actual and expected + "Control" != actual:
                    return False
            else:
                actual = getattr(control, prop, None)
                if not actual:
                    return False
                if isinstance(expected, str) and isinstance(actual, str):
                    if expected not in actual:
                        return False
                elif actual != expected:
                    return False
        return True
    except Exception:
        return False

def find_element_by_selector(parent, selector: dict):
    """Finds a child element using property keys in a selector dictionary (supporting substring matches)."""
    if not selector:
        return None
        
    found_elem = None
    def recursive_walk(control, depth=0):
        nonlocal found_elem
        if found_elem:
            return
        if depth > 25:
            return
        if matches_selector(control, selector):
            found_elem = control
            return
        try:
            for child in control.GetChildren():
                recursive_walk(child, depth + 1)
        except Exception:
            pass
            
    recursive_walk(parent)
    return found_elem

def find_all_elements_by_selector(parent, selector) -> list:
    """Finds all child elements matching a selector dictionary or list of selector dictionaries (supporting substring matches)."""
    if not selector:
        return []
        
    selectors = selector if isinstance(selector, list) else [selector]
    results = []
    def recursive_walk(control, depth=0):
        if depth > 25:
            return
        matched = False
        for sel in selectors:
            if matches_selector(control, sel):
                results.append(control)
                matched = True
                break
        if matched:
            return # Stop recursing inside a matched message block
        try:
            for child in control.GetChildren():
                recursive_walk(child, depth + 1)
        except Exception:
            pass
            
    recursive_walk(parent)
    return results

SKIP_SUBTREE_CONTROL_TYPES = {
    "EditControl",
    "ScrollBarControl",
    "TitleBarControl",
    "MenuBarControl",
    "ToolBarControl",
    "ComboBoxControl"
}

def walk_tree_for_text(control, min_len: int, ignored_patterns: list, results: list, max_depth: int = 15, current_depth: int = 0):
    """Recursively walks the control tree to extract candidate text blocks."""
    if current_depth > max_depth:
        return
        
    try:
        control_type = control.ControlTypeName
        if control_type in SKIP_SUBTREE_CONTROL_TYPES:
            return
            
        name = control.Name
        
        # We primarily capture text elements that represent messages.
        # Edit boxes, scrollbars, titlebars, etc. are typically excluded.
        if control_type in ("TextControl", "DocumentControl") and name:
            text = name.strip()
            # Basic validation
            if len(text) >= min_len and not any(p.lower() in text.lower() for p in ignored_patterns):
                results.append({
                    "text": text,
                    "element": control
                })
        
        # Recursively search children
        for child in control.GetChildren():
            walk_tree_for_text(child, min_len, ignored_patterns, results, max_depth, current_depth + 1)
    except Exception:
        pass

def is_block_control(control) -> bool:
    """Checks if a control type is a structural UIA block element."""
    try:
        ctype = control.ControlTypeName
        if ctype in ("ListControl", "TableControl", "ListItemControl", "GroupControl", "HeaderControl", "PaneControl", "DocumentControl"):
            return True
        return False
    except Exception:
        return False

def is_block_container(control) -> bool:
    """Determines if a control is a block container that should separate child blocks with newlines."""
    try:
        ctype = control.ControlTypeName
        if ctype in ("ListControl", "TableControl"):
            return True
        if ctype == "ListItemControl":
            return False
        if ctype in ("GroupControl", "PaneControl", "DocumentControl"):
            for child in control.GetChildren():
                if is_block_control(child):
                    return True
        return False
    except Exception:
        return False

def extract_text_hierarchical(control) -> str:
    """Extracts text from a control using generic UIA structural rules, avoiding internal newlines for inline segments."""
    try:
        control_type = control.ControlTypeName
        if control_type in SKIP_SUBTREE_CONTROL_TYPES:
            return ""
            
        name = control.Name or ""
        
        if control_type == "TextControl":
            return name
            
        children = control.GetChildren()
        if not children:
            return name
            
        child_texts = []
        for child in children:
            t = extract_text_hierarchical(child)
            if t:
                child_texts.append(t)
                
        if not child_texts:
            return name
            
        if is_block_container(control):
            return "\n".join(t.strip() for t in child_texts if t.strip())
        else:
            return "".join(child_texts)
    except Exception:
        return ""

def locate_messages(pid: int, process_name: str, adapters_config_path: str, settings: dict) -> list[dict]:
    """
    Locates and returns candidate chat messages for a process.
    If an adapter configuration is available, uses it. Otherwise, runs generic walk heuristics.
    
    Each returned list item is:
        {
            "text": str,
            "element": uiautomation.Control
        }
    """
    window = find_window_by_pid(pid)
    if not window:
        logger.debug(f"No window found for PID {pid}")
        return []

    # Try to load adapter config
    adapter = None
    if os.path.exists(adapters_config_path):
        try:
            with open(adapters_config_path, "r", encoding="utf-8") as f:
                adapters = json.load(f)
                adapter = adapters.get(process_name)
        except Exception as e:
            logger.error(f"Error loading adapters config: {e}")

    # Minimum text length and ignored patterns for generic fallback
    min_len = settings.get("min_text_length", 10)
    ignored_patterns = settings.get("ignored_text_patterns", [])

    # Scenario A: Adapter configured and found
    if adapter:
        chat_pane_selector = adapter.get("chat_pane_selector")
        message_element_selector = adapter.get("message_element_selector")
        
        chat_pane = find_element_by_selector(window, chat_pane_selector)
        if chat_pane:
            logger.debug(f"Located chat pane using adapter for {process_name}")
            
            # Find message elements within chat pane
            msg_elements = find_all_elements_by_selector(chat_pane, message_element_selector)
            if msg_elements:
                candidates = []
                for elem in msg_elements:
                    try:
                        # Extract the text content of the message node hierarchically
                        combined_text = extract_text_hierarchical(elem)
                        if combined_text:
                            candidates.append({
                                "text": combined_text.strip(),
                                "element": elem
                            })
                        elif elem.Name:
                            candidates.append({
                                "text": elem.Name.strip(),
                                "element": elem
                            })
                    except Exception:
                        continue
                return candidates

    # Scenario B: Fallback generic heuristic
    logger.debug(f"Using generic fallback heuristic for process {process_name}")
    candidates = []
    
    # Attempt to find any document control first to limit search to page content
    doc_control = None
    try:
        doc_control = auto.DocumentControl(window, searchDepth=12)
        if not doc_control.Exists(maxSearchSeconds=0.5):
            doc_control = None
        else:
            # Force Chromium renderer accessibility tree generation by triggering focus
            try:
                doc_control.SetFocus()
                # Give Chromium a tiny window to build the tree if it is currently empty
                if not doc_control.GetChildren():
                    import time
                    time.sleep(0.3)
            except Exception:
                pass
    except Exception:
        doc_control = None

    search_root = doc_control if doc_control else window
    walk_tree_for_text(search_root, min_len, ignored_patterns, candidates)
    return candidates
