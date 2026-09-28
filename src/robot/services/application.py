"""Semantic PHOS commands and read models.

This module deliberately knows only Core, BehaviorEngine, lifecycle and the
runtime's read-only snapshot boundary.  HTTP, WebSocket, voice and MCP adapters
must use this service instead of reaching into device providers or renderers.
"""
from __future__ import annotations

import asyncio
from enum import Enum
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import platform
import time
from threading import RLock
from typing import Any, Callable

from robot.core import Event, RobotState
from robot.semantics import VisualSource
from robot.core.environmental import AirQualityOverlay, EnvironmentalState, TemperatureOverlay
from robot.core.runtime import STATE_CHANGED
from robot.config import ConfigurationError, RuntimeConfig
from robot.motion import MotionState
from robot.ui.state import FaceExpression


# These are enum members, not duplicated wire values. ERROR is lifecycle-only;
# the current visual-event command deliberately supports only reactions that the
# BehaviorEngine maps from a semantic expression event.
WRITABLE_ROBOT_STATES = tuple(item for item in RobotState if item is not RobotState.ERROR)
WRITABLE_EXPRESSIONS = (FaceExpression.NEUTRAL, FaceExpression.HAPPY, FaceExpression.SURPRISED)
WRITABLE_VISUAL_SOURCES = tuple(VisualSource)


@dataclass(frozen=True)
class CommandDefinition:
    """The canonical validation and transport contract for one semantic command."""

    method: str
    endpoint: str
    field: str
    allowed_members: tuple[Enum, ...]

    @property
    def allowed_values(self) -> list[str]:
        return [item.value for item in self.allowed_members]


# This registry is the sole application-level rule for semantic command input.
# The web capabilities document is projected from it and command handlers
# validate against it; adapters therefore do not maintain parallel enum lists.
COMMANDS = {
    "set_robot_state": CommandDefinition("POST", "/api/v1/state", "state", WRITABLE_ROBOT_STATES),
    "set_expression": CommandDefinition("POST", "/api/v1/expression", "expression", WRITABLE_EXPRESSIONS),
    "set_visual_source": CommandDefinition("POST", "/api/v1/visual-source", "source", WRITABLE_VISUAL_SOURCES),
}

OVERLAY_COMMANDS = {
    "set_overlay": {"method": "POST", "endpoint": "/api/v1/overlay", "fields": {
        "temperature": {"allowed_values": [item.value for item in TemperatureOverlay]},
        "air_quality": {"allowed_values": [item.value for item in AirQualityOverlay]},
        "duration_ms": {"type": "integer", "optional": True},
    }},
    "clear_overlay": {"method": "DELETE", "endpoint": "/api/v1/overlay"},
}


class ApplicationError(Exception):
    """A stable adapter-safe error."""
    def __init__(self, code: str, message: str, details: dict | None = None, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.details, self.status = code, message, details or {}, status

    def document(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class RemoteApplicationService:
    """Web-worker proxy for the parent-owned application service."""
    def __init__(self, lifecycle): self._lifecycle = lifecycle

    def _call(self, name, payload=None):
        response = self._lifecycle.execute(f"application.{name}", payload)
        if response.get("ok"):
            return response["result"]
        error = response.get("error", {})
        if isinstance(error, dict):
            raise ApplicationError(error.get("code", "runtime_error"), error.get("message", "PHOS request failed."),
                                   error.get("details", {}), response.get("status", 400))
        raise ApplicationError("service_unavailable", error, status=response.get("status", 503))

    def status(self): return self._call("status")
    def robot_state(self): return self._call("state")
    def environment(self): return self._call("environment")
    def motion(self): return self._call("motion")
    def health(self): return self._call("health")
    def capabilities(self): return self._call("capabilities")
    def config(self): return self._call("config")
    def update_config(self, value): return self._call("update_config", value)
    def set_expression(self, value): return self._call("expression", {"expression": value})
    def set_state(self, value): return self._call("set_state", {"state": value})
    def set_visual_source(self, value): return self._call("visual_source", {"source": value})
    def overlay(self): return self._call("overlay")
    def set_overlay(self, value): return self._call("set_overlay", value)
    def clear_overlay(self): return self._call("clear_overlay")
    def subscribe(self, listener): return lambda: None
    def emit_snapshot_changes(self): pass


class PhosApplicationService:
    """Small provider-neutral command boundary for a running PHOS instance."""
    def __init__(self, runtime, *, lifecycle=None, clock=time.monotonic):
        self._runtime = runtime
        self._core = runtime.core
        self._behavior = runtime._behavior_engine  # composition-owned semantic collaborator
        self._lifecycle = lifecycle
        self._clock = clock
        self._started = clock()
        self._listeners: list[Callable[[dict], None]] = []
        self._last: dict[str, object] = {}
        self._lock = RLock()
        self._unsubscribers = [
            self._core.events.subscribe(STATE_CHANGED, lambda event: self._emit("robot_state_changed", event.data)),
        ]

    def close(self):
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers = []

    def subscribe(self, listener: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)
        def unsubscribe():
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)
        return unsubscribe

    def _emit(self, event_type: str, payload: dict):
        # State-change events can arrive through more than one runtime path;
        # suppress identical consecutive payloads before crossing adapters.
        frozen = repr(payload)
        with self._lock:
            if self._last.get(event_type) == frozen:
                return
            self._last[event_type] = frozen
            listeners = tuple(self._listeners)
        event = {"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 "payload": payload}
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # A disconnected remote client cannot affect robot behavior.
                continue

    @staticmethod
    def _plain(value: Any):
        if is_dataclass(value):
            return {key: PhosApplicationService._plain(item) for key, item in asdict(value).items()}
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, dict):
            return {str(key): PhosApplicationService._plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [PhosApplicationService._plain(item) for item in value]
        return value

    def visual_state(self) -> dict:
        state = self._behavior.face_state
        return self._plain(state)

    def robot_state(self) -> dict:
        return {"state": self._core.state.value, "running": self._core.is_running}

    def sensors(self) -> dict:
        return self._runtime.sensor_status()

    def environment(self) -> dict:
        return self.sensors().get("environmental", {"status": "unavailable", "available": False})

    def motion(self) -> dict:
        return self.sensors().get("imu", {"status": "unavailable", "available": False})

    def health(self) -> dict:
        snapshots = self.sensors()
        mapping = {"environmental": "environmental", "ccs811": "ccs811", "imu": "mpu6050", "led_ring": "led_ring"}
        subsystems = {}
        for name, source in mapping.items():
            item = snapshots.get(source)
            raw = item.get("status", "unavailable") if item else "unavailable"
            state = {"available": "ok", "warming_up": "warming_up", "stale": "stale"}.get(raw, "unavailable")
            subsystems[name] = {"state": state, "detail": raw}
        subsystems["runtime"] = {"state": "ok" if self._core.is_running else "unavailable"}
        return {"uptime_seconds": max(0.0, self._clock() - self._started), "python": platform.python_version(),
                "subsystems": subsystems}

    def capabilities(self) -> dict:
        """Operation-oriented semantic contract derived from domain validation."""
        return {
            "commands": {**{name: _command(definition) for name, definition in COMMANDS.items()}, **OVERLAY_COMMANDS},
            "observable_states": {
                "robot_state": [item.value for item in RobotState],
                "motion_state": [item.value for item in MotionState],
                "environmental_state": [item.value for item in EnvironmentalState],
                "environmental_overlays": {
                    "temperature": [item.value for item in TemperatureOverlay],
                    "air_quality": [item.value for item in AirQualityOverlay],
                },
            },
        }

    def overlay(self) -> dict:
        environmental, override, resolved = self._behavior.overlay_state()
        return {
            "environmental": self._plain(environmental),
            "override": {"active": override is not None,
                         "temperature": None if override is None else override.temperature,
                         "air_quality": None if override is None else override.air_quality,
                         "expires_at": None if override is None else override.expires_at_iso},
            "resolved": self._plain(resolved),
        }

    def set_overlay(self, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ApplicationError("invalid_overlay", "Overlay override must be a JSON object.")
        allowed_keys = {"temperature", "air_quality", "duration_ms"}
        unknown = set(value) - allowed_keys
        if unknown:
            raise ApplicationError("invalid_overlay", "Unsupported overlay field.", {"fields": sorted(unknown)})
        if "temperature" not in value and "air_quality" not in value:
            raise ApplicationError("invalid_overlay", "At least one overlay field is required.")
        temperature = value.get("temperature")
        air_quality = value.get("air_quality")
        if "temperature" in value and temperature not in OVERLAY_COMMANDS["set_overlay"]["fields"]["temperature"]["allowed_values"]:
            raise ApplicationError("invalid_overlay_temperature", "Unsupported temperature overlay.", {"temperature": temperature})
        if "air_quality" in value and air_quality not in OVERLAY_COMMANDS["set_overlay"]["fields"]["air_quality"]["allowed_values"]:
            raise ApplicationError("invalid_overlay_air_quality", "Unsupported air-quality overlay.", {"air_quality": air_quality})
        duration_ms = value.get("duration_ms")
        if duration_ms is not None and (type(duration_ms) is not int or duration_ms <= 0):
            raise ApplicationError("invalid_overlay_duration", "duration_ms must be a positive integer.", {"duration_ms": duration_ms})
        self._behavior.set_overlay_override(temperature=temperature, air_quality=air_quality, duration_ms=duration_ms)
        result = self.overlay()
        self._emit("overlay_changed", result)
        return result

    def clear_overlay(self) -> dict:
        self._behavior.clear_overlay_override()
        result = self.overlay()
        self._emit("overlay_changed", result)
        return result

    def status(self) -> dict:
        # Runtime supplies this same provider-neutral snapshot to the local
        # lifecycle status service consumed by Web Admin.
        snapshot = getattr(self._runtime, "application_status", None)
        result = snapshot() if snapshot is not None else {
            "robot": self.robot_state(), "visual": self.visual_state(),
            "environment": self.environment(), "motion": self.motion(),
        }
        result["health"] = self.health()
        self._emit("visual_state_changed", result["visual"])
        return result

    def emit_snapshot_changes(self) -> None:
        """Publish bounded semantic snapshots when an adapter asks for one.

        This is intentionally pull-driven: it creates no telemetry thread and
        never streams raw samples.  A WebSocket adapter can call it after a
        state-changing command or its low-rate client heartbeat.
        """
        self._emit("environmental_state_changed", self.environment())
        self._emit("motion_state_changed", self.motion())
        self._emit("health_changed", self.health())

    def config(self) -> dict:
        if self._lifecycle is None:
            raise ApplicationError("service_unavailable", "Configuration service is unavailable.", status=503)
        result = self._lifecycle.execute("status")
        if not result.get("ok"):
            raise ApplicationError("service_unavailable", result.get("error", "Configuration service is unavailable."), status=503)
        saved = RuntimeConfig.from_file(self._lifecycle.path).to_dict()
        return {"saved": saved, "active": result["active"], "pending": result["changed"]}

    def update_config(self, patch: dict) -> dict:
        """Validate and persist a partial canonical-config edit, then reload safely."""
        if self._lifecycle is None:
            raise ApplicationError("service_unavailable", "Configuration service is unavailable.", status=503)
        if not isinstance(patch, dict):
            raise ApplicationError("invalid_configuration", "Configuration update must be a JSON object.")
        document = RuntimeConfig.from_file(self._lifecycle.path).to_dict()
        _merge(document, patch)
        try:
            RuntimeConfig.from_dict(document, base_dir=self._lifecycle.path.parent).save(self._lifecycle.path)
        except (ConfigurationError, OSError) as error:
            raise ApplicationError("invalid_configuration", "Configuration update was rejected.", {"reason": str(error)}) from error
        result = self._lifecycle.execute("reload")
        if not result.get("ok"):
            raise ApplicationError("runtime_unavailable", result.get("error", "Configuration was saved but could not be applied."), status=503)
        return {"saved": document, "applied": result.get("applied", []), "pending": result.get("restart_required", [])}

    def set_visual_source(self, source: str) -> dict:
        if source not in COMMANDS["set_visual_source"].allowed_values:
            raise ApplicationError("invalid_visual_source", "Unsupported visual source.", {"source": source})
        self._runtime.apply_base_visual_source(type("Config", (), {"base_visual_source": source})())
        payload = {"source": source}
        self._emit("visual_state_changed", payload)
        return payload

    def set_expression(self, expression: str) -> dict:
        try:
            target = FaceExpression(expression)
        except (TypeError, ValueError) as error:
            raise ApplicationError("invalid_expression", "Unsupported semantic expression.", {"expression": expression}) from error
        if target not in COMMANDS["set_expression"].allowed_members:
            raise ApplicationError("unsupported_expression_command", "Expression is not writable through this command.",
                                   {"expression": expression})
        # Expression is a semantic transient event, not a renderer mutation.
        loop = self._runtime._loop
        if loop is None:
            raise ApplicationError("runtime_unavailable", "PHOS runtime is not running.", status=503)
        async def publish():
            await self._core.events.publish(Event("vision.visual_expression_stable", {"visual_expression": {
                "label": target.value, "confidence": 1.0}}))
        future = asyncio.run_coroutine_threadsafe(publish(), loop)
        future.result(timeout=2)
        payload = {"expression": target.value}
        self._emit("expression_changed", payload)
        return payload

    def set_state(self, state: str) -> dict:
        try:
            target = RobotState(state)
        except (TypeError, ValueError) as error:
            raise ApplicationError("invalid_robot_state", "Unsupported robot state.", {"state": state}) from error
        if target not in COMMANDS["set_robot_state"].allowed_members:
            raise ApplicationError("unsupported_state_command", "Robot state is runtime-only.", {"state": state})
        loop = self._runtime._loop
        if loop is None:
            raise ApplicationError("runtime_unavailable", "PHOS runtime is not running.", status=503)
        asyncio.run_coroutine_threadsafe(self._core.transition_to(target, reason="remote_api"), loop).result(timeout=2)
        return self.robot_state()


def _merge(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if key not in target:
            raise ConfigurationError(f"Unknown configuration field: {key}")
        if isinstance(value, dict):
            if not isinstance(target[key], dict):
                raise ConfigurationError(f"Configuration field is not an object: {key}")
            _merge(target[key], value)
        else:
            target[key] = value


def _command(definition: CommandDefinition) -> dict:
    return {"method": definition.method, "endpoint": definition.endpoint,
            "field": definition.field, "allowed_values": definition.allowed_values}
