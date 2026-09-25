"""Shared validated reload and supervisor-owned restart operations."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
from threading import RLock
import time

from robot.config import ConfigurationError, RuntimeConfig

RESTART_EXIT_CODE = 75
PREVIEW_RELOADABLE = frozenset({
    "vision.camera_preview.enabled", "vision.camera_preview.position", "vision.camera_preview.scale",
    "vision.camera_preview.max_fps", "vision.camera_preview.show_face_box",
    "vision.camera_preview.show_expression", "vision.camera_preview.show_confidence",
})
IMU_MOTION_RELOADABLE = frozenset({
    "sensors.imu.motion.movement_threshold_m_s2", "sensors.imu.motion.tilt_threshold_m_s2",
    "sensors.imu.motion.shake_threshold_deg_s", "sensors.imu.motion.impact_threshold_m_s2",
    "sensors.imu.motion.confirmation_seconds", "sensors.imu.motion.cooldown_seconds",
})
RELOADABLE = frozenset({"logging.level", "display.iris_color", *PREVIEW_RELOADABLE, *IMU_MOTION_RELOADABLE})


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
        self._apply_appearance = None
        self._apply_camera_preview = None
        self._apply_imu_motion = None
        self._sensor_status = None
        self._clock = clock
        self._lock = RLock()

    def register_appearance_applier(self, applier):
        """Register the running application service's renderer update boundary."""
        with self._lock:
            self._apply_appearance = applier

    def register_camera_preview_applier(self, applier):
        """Register runtime service for applying validated preview settings."""
        with self._lock:
            self._apply_camera_preview = applier

    def register_imu_motion_applier(self, applier):
        with self._lock:
            self._apply_imu_motion = applier

    @property
    def restart_due(self):
        with self._lock:
            return self.restart_at is not None and self._clock() >= self.restart_at

    def register_sensor_status(self, supplier):
        """Register a nonblocking snapshot supplier, never a hardware callback."""
        with self._lock:
            self._sensor_status = supplier

    def _snapshot(self, saved):
        changed = changed_fields(self.active, saved)
        return {"active": deepcopy(self.active), "config_path": str(self.path),
                "loaded_at": self.loaded_at, "changed": changed,
                "reloadable": sorted(set(changed) & RELOADABLE),
                "restart_required": sorted(set(changed) - RELOADABLE),
                "restart_supported": self.restart_supported,
                "restart_requested": self.restart_at is not None,
                "sensors": self._sensor_status() if self._sensor_status is not None else {}}

    def execute(self, operation):
        """Fixed allowlist; no command/path/config payload is accepted from adapters."""
        with self._lock:
            if not isinstance(operation, str) or operation not in {"status", "reload", "restart"}:
                return {"ok": False, "error": "Unsupported lifecycle operation."}
            try:
                config = RuntimeConfig.from_file(self.path)
                saved = config.to_dict()
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
                if (self.active["display"]["iris_color"] != saved["display"]["iris_color"]
                        and self._apply_appearance is None):
                    return {"ok": False, "error": "Runtime appearance service is not ready. No settings were applied; retry reload shortly."}
                preview_paths = changed_fields(self.active["vision"]["camera_preview"],
                    saved["vision"]["camera_preview"], "vision.camera_preview")
                preview_changed = bool(preview_paths)
                if preview_changed and self._apply_camera_preview is None:
                    return {"ok": False, "error": "Runtime camera preview service is not ready. No settings were applied; retry reload shortly."}
                motion_paths = changed_fields(self.active["sensors"]["imu"]["motion"],
                    saved["sensors"]["imu"]["motion"], "sensors.imu.motion")
                if motion_paths and self._apply_imu_motion is None:
                    return {"ok": False, "error": "Runtime IMU motion service is not ready. No settings were applied; retry reload shortly."}
                if self.active["display"]["iris_color"] != saved["display"]["iris_color"]:
                    try:
                        self._apply_appearance(config)
                    except Exception:
                        return {"ok": False, "error": "The running display could not accept the appearance update. No active configuration was recorded; retry reload or restart PHOS."}
                    self.active["display"]["iris_color"] = saved["display"]["iris_color"]
                    applied.append("display.iris_color")
                if preview_changed:
                    try:
                        self._apply_camera_preview(config)
                    except Exception:
                        logging.getLogger(__name__).exception("Camera preview reload failed")
                        return {"ok": False, **self._snapshot(saved), "applied": applied,
                                "error": "Camera preview could not be applied. Earlier appearance changes may already be active. Check PHOS logs, then retry reload or restart."}
                    self.active["vision"]["camera_preview"] = deepcopy(saved["vision"]["camera_preview"])
                    applied.extend(preview_paths)
                if motion_paths:
                    try:
                        self._apply_imu_motion(config)
                    except Exception:
                        logging.getLogger(__name__).exception("IMU motion reload failed")
                        return {"ok": False, **self._snapshot(saved), "applied": applied,
                                "error": "IMU motion settings could not be applied. No IMU hardware was reinitialized; retry reload or restart PHOS."}
                    self.active["sensors"]["imu"]["motion"] = deepcopy(saved["sensors"]["imu"]["motion"])
                    applied.extend(motion_paths)
                if self.active["logging"]["level"] != saved["logging"]["level"]:
                    self._set_log_level(saved["logging"]["level"])
                    self.active["logging"]["level"] = saved["logging"]["level"]
                    applied.append("logging.level")
                self.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return {"ok": True, **self._snapshot(saved), "applied": applied}
