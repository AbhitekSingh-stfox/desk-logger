from src.desktop_helper import switch_thread_to_default_desktop

# Force the main process thread to switch to the "Default" user desktop immediately.
# This prevents Windows COM/UIAutomation from caching the sandbox's virtual desktop.
switch_thread_to_default_desktop()

import os
import sys
import logging
import argparse
from src.poller import PollingEngine
from src.tray_app import TrayApplication

# Setup structured logging to standard output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

import ctypes
import getpass

logger = logging.getLogger("AIActivityLogger.Main")

# Keep reference to the mutex to prevent it from being garbage collected
_mutex_ref = None

def check_single_instance() -> bool:
    global _mutex_ref
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.windll.kernel32
    
    username = getpass.getuser()
    # Mutex name is user-specific to support multi-session Windows servers
    mutex_name = f"Global\\AIActivityLoggerMutex_{username}"
    
    _mutex_ref = kernel32.CreateMutexW(None, False, mutex_name)
    last_error = kernel32.GetLastError()
    if last_error == ERROR_ALREADY_EXISTS:
        return False
    return True

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="AI Conversation Activity Logger")
    parser.add_argument("--console", action="store_true", help="Run in headless console mode without system tray")
    args = parser.parse_args()

    # Setup single-instance check
    if not check_single_instance():
        logger.critical("Another instance of AI Activity Logger is already running for this user. Exiting to prevent duplicate logs.")
        sys.exit(1)

    logger.info("Initializing Desktop AI Conversation Logger...")

    # Define configuration file locations
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(base_dir, "config")
    
    apps_config = os.path.join(config_dir, "apps.json")
    adapters_config = os.path.join(config_dir, "adapters.json")
    settings_config = os.path.join(config_dir, "settings.json")

    # Verify that configurations exist
    for cfg in (apps_config, adapters_config, settings_config):
        if not os.path.exists(cfg):
            logger.error(f"Required configuration file is missing: {cfg}")
            sys.exit(1)

    # Initialize the Polling Engine
    poller = PollingEngine(
        apps_config_path=apps_config,
        adapters_config_path=adapters_config,
        settings_path=settings_config
    )

    # Scenario A: Headless console mode (for testing)
    if args.console:
        logger.info("Running in console-only mode. Press Ctrl+C to stop.")
        # Enable detailed debug logs automatically for ease of testing
        logging.getLogger("AIActivityLogger").setLevel(logging.DEBUG)
        
        try:
            import time
            
            # Load initial config settings
            settings = poller._load_settings()
            poll_interval = settings.get("poll_interval_seconds", 1.5)
            
            while True:
                try:
                    poller._poll_step()
                except Exception as e:
                    logger.error(f"Error during poll step: {e}")
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Shutting down console logger.")
            sys.exit(0)

    # Scenario B: Standard Tray Application mode
    # Start background polling thread
    poller.start()

    # Setup signal handling to ensure graceful terminate on Ctrl+C / SIGINT / SIGTERM
    import signal
    def handle_exit_signal(sig, frame):
        logger.info("Shutdown signal received. Stopping background poller...")
        poller.stop()
        logger.info("Clean shutdown complete. Exiting.")
        os._exit(0)

    signal.signal(signal.SIGINT, handle_exit_signal)
    signal.signal(signal.SIGTERM, handle_exit_signal)

    # Callback when application shuts down
    def on_quit():
        logger.info("Clean shutdown complete. Exiting.")
        poller.stop()
        os._exit(0)

    # Initialize and run system tray menu (runs on main thread, blocking)
    try:
        tray = TrayApplication(poller_engine=poller, quit_callback=on_quit)
        tray.run()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
        poller.stop()
        os._exit(0)
    except Exception as e:
        logger.critical(f"Unhandled exception in main tray thread: {e}", exc_info=True)
        poller.stop()
        os._exit(1)

if __name__ == "__main__":
    main()
