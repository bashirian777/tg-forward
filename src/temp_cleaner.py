"""Safe one-shot cleanup for stale files in the temp directory."""
import logging
import os
import time
from typing import Dict

logger = logging.getLogger(__name__)


def cleanup_temp_dir(temp_dir: str = "temp", max_age_hours: float = 24.0) -> Dict[str, int]:
    """
    Remove regular files in *temp_dir* older than *max_age_hours*.

    This is intentionally a one-shot function called once at service startup,
    before forwarding tasks begin. It does not run periodically and therefore
    cannot race with files that are actively being downloaded or uploaded.

    Returns a small summary dict:
        {"removed": <count>, "freed_bytes": <bytes>, "scanned": <count>}
    """
    summary = {"removed": 0, "freed_bytes": 0, "scanned": 0}

    if not max_age_hours or max_age_hours <= 0:
        logger.debug("Temp cleanup disabled (max_age_hours=%s)", max_age_hours)
        return summary

    if not os.path.isdir(temp_dir):
        logger.debug("Temp directory does not exist, skipping cleanup: %s", temp_dir)
        return summary

    cutoff = time.time() - (max_age_hours * 3600)

    try:
        entries = list(os.scandir(temp_dir))
    except OSError as e:
        logger.warning("Unable to scan temp directory %s: %s", temp_dir, e)
        return summary

    for entry in entries:
        try:
            if not entry.is_file(follow_symlinks=False):
                continue

            st = entry.stat()
            summary["scanned"] += 1

            if st.st_mtime < cutoff:
                os.remove(entry.path)
                summary["removed"] += 1
                summary["freed_bytes"] += st.st_size
                logger.debug(
                    "Removed stale temp file: %s (%.1f MB)",
                    entry.path,
                    st.st_size / (1024 * 1024),
                )
        except FileNotFoundError:
            continue
        except OSError as e:
            logger.warning("Failed to remove temp file %s: %s", entry.path, e)

    if summary["removed"]:
        logger.info(
            "Temp cleanup removed %s stale file(s), freed %.2f MB",
            summary["removed"],
            summary["freed_bytes"] / (1024 * 1024),
        )

    return summary