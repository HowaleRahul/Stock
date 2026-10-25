"""
Unified thread-safe and async-safe persistent store for config.json.
Provides cross-router synchronization, atomic writes via tempfiles, and error recovery.
"""

import os
import json
import logging
import tempfile
import threading
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("trading.api.config_store")

CONFIG_PATH = "config.json"

# Unified global lock shared across all routers, background threads, and async endpoints
_config_file_lock = threading.RLock()


def load_config_atomic(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Reads configuration from disk under lock.
    Returns empty dict if file does not exist.
    """
    target = path or CONFIG_PATH
    with _config_file_lock:
        if not os.path.exists(target):
            return {}
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Configuration root must be a JSON object.")
            return data
        except Exception as e:
            logger.exception("Failed to load configuration from %s: %s", target, e)
            raise e


def save_config_atomic(config: Dict[str, Any], path: Optional[str] = None) -> None:
    """
    Persists configuration atomically using fsync and atomic file replacement.
    Includes retry logic for Windows file locking contention.
    """
    if not isinstance(config, dict):
        raise ValueError("Configuration data must be a JSON dictionary.")

    target = path or CONFIG_PATH
    directory = os.path.dirname(os.path.abspath(target)) or "."
    temp_path: Optional[str] = None

    with _config_file_lock:
        try:
            fd, temp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
                f.flush()
                os.fsync(f.fileno())

            # Windows-resilient atomic replace with retries on transient file locks
            replaced = False
            last_err = None
            for attempt in range(5):
                try:
                    os.replace(temp_path, target)
                    replaced = True
                    break
                except PermissionError as pe:
                    last_err = pe
                    time.sleep(0.02 * (attempt + 1))

            if not replaced and last_err:
                raise last_err

        except Exception as exc:
            logger.exception("Failed to atomically persist configuration to %s: %s", target, exc)
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise exc


def update_config_atomic(updates: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    """
    Atomically reads existing configuration, merges updates, and persists.
    """
    target = path or CONFIG_PATH
    with _config_file_lock:
        current = load_config_atomic(target)
        current.update(updates)
        save_config_atomic(current, target)
        return current
