"""Shared application lifecycle operations, independent of web and hardware.

Only logging.level has a live apply boundary. Restart is a graceful-exit request
for the documented systemd supervisor, never a shell command or self-spawn.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
from threading import RLock
import time

from robot.config import ConfigurationError, RuntimeConfig

RESTART_EXIT_CODE = 75
RELOADABLE = frozenset({"logging.level"})


def changed_fields(active, saved, prefix=""):
    result = []
    for key, value in saved.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.extend(changed_fields(active[key], value, name))
        elif active[key] != value:
            result.append(name)
    return result


def apply_log_level(level):
    logging.getLogger().setLevel(level)
    # Changing PHOS verbosity must never enable AWS SDK request/credential logs.
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)


class LifecycleService:
    def __init__(self, config_path, active_config, *, restart_supported=False,
                 log_level_setter=apply_log_level, clock=time.monotonic):
        self.path = Path(config_path).resolve()
        self.active = active_config.to_dict()
        self.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.restart_supported = restart_supported
        self.restart_at = None
        self._set_log_level = log_level_setter
        self._clock = clock
        self._lock = RLock()

    @property
    def restart_due(self):
        with self._lock:
            return self.restart_at is not None and self._clock() >= self.restart_at

    def _snapshot(self, saved):
        changed = changed_fields(self.active, saved)
        return {"active": deepcopy(self.active), "config_path": str(self.path),
                "loaded_at": self.loaded_at, "changed": changed,
                "reloadable": sorted(set(changed) & RELOADABLE),
                "restart_required": sorted(set(changed) - RELOADABLE),
                "restart_supported": self.restart_supported,
                "restart_requested": self.restart_at is not None}

    def execute(self, operation):
        """Fixed allowlist; no command/path/config payload is accepted from adapters."""
        with self._lock:
            if not isinstance(operation, str) or operation not in {"status", "reload", "restart"}:
                return {"ok": False, "error": "Unsupported lifecycle operation."}
            try:
                saved = RuntimeConfig.from_file(self.path).to_dict()
            except (ConfigurationError, OSError):
                # Do not echo arbitrary config contents to adapters or logs.
                return {"ok": False, "error": "Saved configuration is invalid or unavailable. No settings were applied; repair it before reload or restart."}
            if operation == "restart":
                if not self.restart_supported:
                    return {"ok": False, "error": "Restart PHOS requires the documented user systemd service. For a terminal launch, stop PHOS and run the startup command again."}
                if self.restart_at is None:
                    # Let the worker deliver its HTTP acknowledgement before exit.
                    self.restart_at = self._clock() + 1.0
                return {"ok": True, **self._snapshot(saved), "applied": []}
            applied = []
            if operation == "reload":
                if self.restart_at is not None:
                    return {"ok": False, "error": "Restart is already requested. Wait for PHOS to start again."}
                if self.active["logging"]["level"] != saved["logging"]["level"]:
                    self._set_log_level(saved["logging"]["level"])
                    self.active["logging"]["level"] = saved["logging"]["level"]
                    applied.append("logging.level")
                self.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return {"ok": True, **self._snapshot(saved), "applied": applied}
