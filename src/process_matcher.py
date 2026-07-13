import json
import os
import logging
import psutil

logger = logging.getLogger("AIActivityLogger.ProcessMatcher")

def get_running_targets(apps_config_path: str) -> list[dict]:
    """
    Scans running processes and returns a list of active target processes
    matching names defined in the apps_config_path.
    
    Each entry is a dict containing:
        {
            "pid": int,
            "name": str
        }
    """
    if not os.path.exists(apps_config_path):
        logger.error(f"Apps configuration file not found at {apps_config_path}")
        return []

    try:
        with open(apps_config_path, "r", encoding="utf-8") as f:
            target_apps = json.load(f)
    except Exception as e:
        logger.error(f"Error loading apps configuration: {e}")
        return []

    if not isinstance(target_apps, list):
        logger.error("Apps configuration must be a list of process names.")
        return []

    # Clean and lower-case target names for comparison
    target_names = {name.lower().strip() for name in target_apps}

    running_targets = []
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            name = proc.info["name"]
            pid = proc.info["pid"]
            if name and name.lower() in target_names:
                running_targets.append({
                    "pid": pid,
                    "name": name
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception as e:
            logger.warning(f"Error checking process: {e}")
            continue

    return running_targets
