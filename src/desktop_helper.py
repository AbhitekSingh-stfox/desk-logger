
import ctypes
import logging

logger = logging.getLogger("AIActivityLogger.DesktopHelper")

def switch_thread_to_default_desktop() -> bool:
    """
    Switches the calling thread to the "Default" interactive desktop.
    This ensures COM/UIA calls can see the interactive user's windows even when
    running inside virtual desktops or headless developer terminals.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    # Open "Default" desktop with DESKTOP_ALL access (0x1FF)
    h_desk = user32.OpenDesktopW("Default", 0, False, 0x1FF)
    if h_desk:
        if user32.SetThreadDesktop(h_desk):
            logger.info("Successfully switched thread desktop to 'Default'.")
            return True
        else:
            err = kernel32.GetLastError()
            logger.warning(f"Failed to set thread desktop to 'Default' (Error: {err}).")
            user32.CloseDesktop(h_desk)
    else:
        err = kernel32.GetLastError()
        logger.warning(f"Could not open 'Default' desktop (Error: {err}).")
    return False
