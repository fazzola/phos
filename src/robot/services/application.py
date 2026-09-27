"""Semantic PHOS commands and read models.

This module deliberately knows only Core, BehaviorEngine, lifecycle and the
runtime's read-only snapshot boundary.  HTTP, WebSocket, voice and MCP adapters
must use this service instead of reaching into device providers or renderers.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import platform
import time
from threading import RLock
from typing import Any, Callable

from robot.core import Event, RobotState
from robot.core.runtime import STATE_CHANGED
from robot.config import ConfigurationError, RuntimeConfig
from robot.ui.state import FaceExpression


class ApplicationError(Exception):
    """A stable adapter-safe error."""
    def __init__(self, code: str, message: str, details: dict | None = None, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.details, self.status = code, message, details or {}, status

    def document(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


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
        if source not in {"manual", "environment", "state"}:
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
