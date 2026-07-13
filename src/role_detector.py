import logging

logger = logging.getLogger("AIActivityLogger.RoleDetector")

def matches_properties(element, selector: dict) -> bool:
    """Checks if a UIAutomation element matches property requirements in a selector (supporting substring matches)."""
    if not selector:
        return False
    try:
        for prop, expected in selector.items():
            if prop == "ControlType":
                # ControlTypeName could be "TextControl", "CustomControl", etc.
                actual_type = element.ControlTypeName
                # Strip "Control" from end for easier matching (e.g. "TextControl" vs "Text")
                if expected not in actual_type and expected + "Control" != actual_type:
                    return False
            else:
                actual = getattr(element, prop, None)
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

def any_descendant_matches(element, selector: dict) -> bool:
    """Recursively checks if the element or any descendant matches the selector properties."""
    if not selector:
        return False
    if matches_properties(element, selector):
        return True
    try:
        for child in element.GetChildren():
            if any_descendant_matches(child, selector):
                return True
    except Exception:
        pass
    return False

def detect_role(candidate: dict, previous_role: str, adapter_config: dict = None, reference_control = None) -> str:
    """
    Determines whether a message is from the "user" or "assistant".
    
    Priority:
    1. Adapter role selectors (checks ClassName, AutomationId, etc. on element or descendants).
    2. Position-based heuristic (checks horizontal alignment relative to reference_control).
    3. Alternate role fallback (alternates from previous_role; starts with "user").
    """
    elem = candidate.get("element")

    # 1. Adapter selectors check
    if adapter_config and elem:
        role_selectors = adapter_config.get("role_selectors", {})
        user_sel = role_selectors.get("user")
        assistant_sel = role_selectors.get("assistant")
        
        if user_sel and matches_properties(elem, user_sel):
            logger.debug("Role detected via adapter (user selector matches): user")
            return "user"
        if assistant_sel and matches_properties(elem, assistant_sel):
            logger.debug("Role detected via adapter (assistant selector matches): assistant")
            return "assistant"

    # 2. Position/Layout heuristic
    if elem and reference_control:
        try:
            rect = elem.BoundingRectangle
            ref_rect = reference_control.BoundingRectangle
            
            if rect and ref_rect:
                ref_center = (ref_rect.left + ref_rect.right) / 2.0
                
                # Check horizontal position (left edge of the message block relative to the reference center)
                # User messages start on the right side of the window (rect.left > ref_center)
                # Assistant messages start on the left side of the window (rect.left <= ref_center)
                if rect.left > ref_center:
                    logger.debug("Role detected via layout (left edge right of center): user")
                    return "user"
                else:
                    logger.debug("Role detected via layout (left edge left of center): assistant")
                    return "assistant"
        except Exception as e:
            logger.debug(f"Could not determine role from position layout: {e}")

    # 3. Turn-alternation fallback
    if previous_role == "user":
        logger.debug("Role fallback via turn alternation: assistant")
        return "assistant"
    elif previous_role == "assistant":
        logger.debug("Role fallback via turn alternation: user")
        return "user"
    
    # Defaults to user if no context is available (start of conversation)
    logger.debug("Role fallback default: user")
    return "user"
