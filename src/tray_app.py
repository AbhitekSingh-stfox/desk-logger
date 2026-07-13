import os
import logging
import threading
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

logger = logging.getLogger("AIActivityLogger.TrayApp")

# Color palette (sleek, modern colors)
COLOR_ACTIVE = (16, 185, 129)  # Emerald green
COLOR_INACTIVE = (100, 116, 139)  # Slate gray

def create_glowing_circle(color: tuple, size: int = 64) -> Image:
    """Generates a high-quality system tray icon representing status."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Outer semi-transparent glow ring
    glow_color = color + (80,)  # Add alpha transparency
    draw.ellipse((4, 4, size - 5, size - 5), fill=glow_color)
    
    # Inner solid indicator circle
    draw.ellipse((12, 12, size - 13, size - 13), fill=color, outline=(255, 255, 255), width=2)
    
    return image

class TrayApplication:
    def __init__(self, poller_engine, quit_callback=None):
        self.poller = poller_engine
        self.quit_callback = quit_callback
        self.icon = None
        
        # Load initial status icons
        self.icon_active = create_glowing_circle(COLOR_ACTIVE)
        self.icon_inactive = create_glowing_circle(COLOR_INACTIVE)

    def run(self):
        """Starts the tray application event loop."""
        menu = pystray.Menu(
            item(
                "Toggle Logging",
                self.on_toggle,
                checked=lambda item: self.poller.is_logging_active
            ),
            item(
                "Open Log Folder",
                self.on_open_folder
            ),
            pystray.Menu.SEPARATOR,
            item(
                "Quit",
                self.on_quit
            )
        )

        initial_icon = self.icon_active if self.poller.is_logging_active else self.icon_inactive
        tooltip = "AI Activity Logger (Active)" if self.poller.is_logging_active else "AI Activity Logger (Paused)"

        self.icon = pystray.Icon(
            "ai_activity_logger",
            icon=initial_icon,
            title=tooltip,
            menu=menu
        )
        
        logger.info("Starting system tray application loop...")
        # Note: this blocks the current thread until self.icon.stop() is called
        self.icon.run()

    def on_toggle(self, icon, item):
        """Callback to switch logging status and swap status icon."""
        self.poller.is_logging_active = not self.poller.is_logging_active
        
        if self.poller.is_logging_active:
            icon.icon = self.icon_active
            icon.title = "AI Activity Logger (Active)"
            logger.info("Logging toggled: ACTIVE")
        else:
            icon.icon = self.icon_inactive
            icon.title = "AI Activity Logger (Paused)"
            logger.info("Logging toggled: PAUSED")

    def on_open_folder(self, icon, item):
        """Opens the folder containing the log files in Windows Explorer."""
        from src.log_writer import DEFAULT_LOG_DIR
        if not os.path.exists(DEFAULT_LOG_DIR):
            try:
                os.makedirs(DEFAULT_LOG_DIR, exist_ok=True)
            except Exception as e:
                logger.error(f"Could not create folder: {e}")
                return
                
        try:
            logger.info(f"Opening log directory: {DEFAULT_LOG_DIR}")
            os.startfile(DEFAULT_LOG_DIR)
        except Exception as e:
            logger.error(f"Failed to open log folder: {e}")

    def on_quit(self, icon, item):
        """Stops the poller engine and closes the tray application."""
        logger.info("Quit command triggered from menu.")
        
        # 1. Stop background polling thread
        self.poller.stop()
        
        # 2. Stop tray icon loop
        icon.stop()
        
        # 3. Call any additional cleanup triggers
        if self.quit_callback:
            self.quit_callback()
