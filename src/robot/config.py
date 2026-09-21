"""Canonical, secret-free PHOS settings. No hardware, SDK or CLI dependencies."""
from __future__ import annotations

import json
import ipaddress
import math
import os
import tempfile
import sys
from dataclasses import asdict, dataclass, fields, field
from pathlib import Path
from typing import Optional, Tuple

# Source checkouts use the one canonical document. Wheels install that same
# source file as data; no independent defaults are maintained in the package.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "phos.json"
if not DEFAULT_CONFIG_PATH.is_file():
    DEFAULT_CONFIG_PATH = Path(sys.prefix) / "share" / "phos" / "config" / "phos.json"


class ConfigurationError(ValueError):
    """Invalid settings, reported before any subsystem is constructed."""


def _keys(value, expected, location):
    if not isinstance(value, dict):
        raise ConfigurationError(f"{location} must be an object")
    missing, unknown = set(expected) - value.keys(), value.keys() - set(expected)
    if missing:
        raise ConfigurationError(f"{location}: missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ConfigurationError(f"{location}: unknown fields: {', '.join(sorted(unknown))}; secrets are not supported")


def load_document(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Read JSON for editing; use RuntimeConfig.from_dict to validate before use."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConfigurationError(f"Duplicate configuration key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"{path}: invalid JSON at line {error.lineno}, column {error.colno}") from error
    except (OSError, UnicodeError) as error:
        raise ConfigurationError(f"Cannot read configuration file: {path} ({type(error).__name__})") from error


@dataclass(frozen=True, init=False)
class CloudExpressionConfig:
    region: Optional[str]
    cooldown_seconds: float
    stable_seconds: float
    cache_ttl_seconds: float
    refresh_seconds: float
    max_requests_per_minute: float
    max_requests_per_session: int
    change_threshold: float
    minimum_face_confidence: float
    retry_initial_seconds: float
    retry_max_seconds: float
    connect_timeout_seconds: float
    read_timeout_seconds: float

    def __init__(self, **overrides) -> None:
        values = load_document(DEFAULT_CONFIG_PATH)["expression"]["aws"]
        values.update(overrides)
        self._assign(values)

    def _assign(self, values) -> None:
        names = {f.name for f in fields(self)}
        _keys(values, names, "expression.aws")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        self.__post_init__()

    @classmethod
    def from_dict(cls, values) -> CloudExpressionConfig:
        result = object.__new__(cls)
        result._assign(values)
        return result

    def __post_init__(self) -> None:
        for name in ("cooldown_seconds", "stable_seconds", "cache_ttl_seconds", "refresh_seconds", "max_requests_per_minute",
                     "retry_initial_seconds", "retry_max_seconds", "connect_timeout_seconds",
                     "read_timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("change_threshold", "minimum_face_confidence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if type(self.max_requests_per_session) is not int or self.max_requests_per_session < 0:
            raise ValueError("max_requests_per_session must be a nonnegative integer")
        if self.refresh_seconds >= self.cache_ttl_seconds:
            raise ValueError("refresh_seconds must be less than cache_ttl_seconds")
        if self.retry_max_seconds < self.retry_initial_seconds:
            raise ValueError("retry_max_seconds must be at least retry_initial_seconds")
        if self.region is not None and (not isinstance(self.region, str) or not self.region.strip()):
            raise ValueError("region must be a nonempty string or null")


# The section structure maps to the existing typed RuntimeConfig surface. Values
# live only in phos.json; this mapping is schema, not a second set of defaults.
_SCHEMA = {
    "web": {"enabled": "web_enabled", "host": "web_host", "port": "web_port"},
    "display": {"width": "display_width", "height": "display_height", "fps": "display_fps",
                "fullscreen": "fullscreen", "transition_seconds": "display_transition_seconds",
                "iris_color": "iris_color"},
    "behavior": {"blink_interval_seconds": "blink_interval_seconds", "gaze_interval_seconds": "gaze_interval_seconds",
                 "face_gaze_smoothing": "face_gaze_smoothing", "reaction_decay_per_second": "reaction_decay_per_second"},
    "vision": {"face_tracking_enabled": "face_tracking_enabled", "camera_resolution": "camera_resolution",
               "capture_fps": "vision_capture_fps", "detection_fps": "face_detection_fps",
               "detector": {"cascade_path": "cascade_path", "scale_factor": "detector_scale_factor",
                            "min_neighbors": "detector_min_neighbors", "min_size": "detector_min_size"}},
    "expression": {
        "enabled": "expression_enabled", "provider": "expression_provider", "inference_fps": "expression_inference_fps",
        "crop_margin": "expression_crop_margin",
        "smoothing": {"minimum_confidence": "expression_minimum_confidence",
                      "minimum_observations": "expression_minimum_observations",
                      "local_maximum_gap_seconds": "expression_local_maximum_gap_seconds",
                      "neutral_enabled": "expression_neutral_enabled"},
        "local": {"model_path": "expression_model_path", "labels": "expression_labels",
                  "input_size": "expression_input_size", "scale": "expression_scale", "mean": "expression_mean",
                  "swap_rb": "expression_swap_rb", "grayscale": "expression_grayscale"},
        "aws": "cloud_expression",
    },
    "logging": {"level": "log_level", "file": "log_file", "expression_diagnostics": "expression_diagnostics"},
}
_PATH_FIELDS = {"expression_model_path", "cascade_path", "log_file"}
_TUPLE_FIELDS = {"camera_resolution", "expression_labels", "expression_input_size", "expression_mean",
                 "blink_interval_seconds", "gaze_interval_seconds", "detector_min_size"}


def _decode(document, schema=_SCHEMA, location="config"):
    _keys(document, schema, location)
    result = {}
    for key, target in schema.items():
        value, name = document[key], f"{location}.{key}"
        if isinstance(target, dict):
            result.update(_decode(value, target, name))
        elif target == "cloud_expression":
            try:
                result[target] = CloudExpressionConfig.from_dict(value)
            except (ValueError, TypeError) as error:
                raise ConfigurationError(f"{name}: {error}") from error
        else:
            if target in _TUPLE_FIELDS:
                if not isinstance(value, (list, tuple)):
                    raise ConfigurationError(f"{name} must be an array")
                value = tuple(value)
            if target in _PATH_FIELDS and value is not None:
                if not isinstance(value, (str, Path)) or not str(value).strip():
                    raise ConfigurationError(f"{name} must be a nonempty path or null")
                value = Path(value)
            result[target] = value
    return result


@dataclass(frozen=True, init=False)
class RuntimeConfig:
    """Typed application settings; JSON is the authoritative default path.

    Existing Python keyword construction remains a compatibility convenience:
    it overlays canonical settings. File/dict loading requires the full schema.
    """

    web_enabled: bool
    web_host: str
    web_port: int
    display_width: int
    display_height: int
    display_fps: int
    fullscreen: bool
    display_transition_seconds: float
    iris_color: str
    blink_interval_seconds: Tuple[float, float]
    gaze_interval_seconds: Tuple[float, float]
    face_gaze_smoothing: float
    reaction_decay_per_second: float
    face_tracking_enabled: bool
    camera_resolution: Tuple[int, int]
    vision_capture_fps: float
    face_detection_fps: float
    cascade_path: Optional[Path]
    detector_scale_factor: float
    detector_min_neighbors: int
    detector_min_size: Tuple[int, int]
    expression_enabled: bool
    expression_inference_fps: float
    expression_provider: str
    cloud_expression: CloudExpressionConfig
    expression_minimum_confidence: float
    expression_minimum_observations: int
    expression_local_maximum_gap_seconds: float
    expression_neutral_enabled: bool
    expression_model_path: Optional[Path]
    expression_labels: Tuple[str, ...]
    expression_input_size: Tuple[int, int]
    expression_scale: float
    expression_mean: Tuple[float, float, float]
    expression_swap_rb: bool
    expression_grayscale: bool
    expression_diagnostics: bool
    expression_crop_margin: float
    log_level: str
    log_file: Optional[Path]
    _base_dir: Path = field(init=False, repr=False, compare=False)

    def __init__(self, **overrides) -> None:
        # Preserve existing Python calls; new application entry points use from_file.
        if "expression_enabled" not in overrides and (
            overrides.get("expression_model_path") is not None or overrides.get("expression_provider") == "aws"
        ):
            overrides["expression_enabled"] = True
        for name in _PATH_FIELDS & overrides.keys():
            if overrides[name] is not None:
                overrides[name] = Path(overrides[name]).resolve()
        values = _decode(load_document(DEFAULT_CONFIG_PATH))
        self._assign(values, DEFAULT_CONFIG_PATH.parent, overrides)

    def _assign(self, values, base_dir, overrides=None):
        names = {f.name for f in fields(self) if f.init}
        if overrides:
            unknown = overrides.keys() - names
            if unknown:
                raise ConfigurationError(f"Unknown configuration overrides: {', '.join(sorted(unknown))}")
            values.update(overrides)
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_base_dir", Path(base_dir).resolve())
        self.validate()

    @classmethod
    def from_file(cls, path: Path = DEFAULT_CONFIG_PATH, *, overrides=None) -> RuntimeConfig:
        path = Path(path).resolve()
        return cls.from_dict(load_document(path), base_dir=path.parent, overrides=overrides)

    @classmethod
    def from_dict(cls, document: dict, *, base_dir: Path, overrides=None, check_paths=True) -> RuntimeConfig:
        """Validate a document, independent of argparse and AWS credentials.

        Editors may skip filesystem checks to repair removed model paths; schema
        and value validation still run. Startup and save always check paths.
        """
        result = object.__new__(cls)
        result._assign(_decode(document), base_dir, overrides)
        if check_paths:
            result.validate_paths()
        return result

    def to_dict(self) -> dict:
        """Return the complete secret-free JSON structure for editing/persistence."""
        def encode(schema):
            result = {}
            for key, target in schema.items():
                if isinstance(target, dict):
                    result[key] = encode(target)
                else:
                    value = getattr(self, target)
                    if isinstance(value, CloudExpressionConfig):
                        value = asdict(value)
                    elif isinstance(value, Path):
                        value = str(value)
                    elif isinstance(value, tuple):
                        value = list(value)
                    result[key] = value
            return result
        return encode(_SCHEMA)

    def save(self, path: Path) -> None:
        """Atomically persist validated settings, rebasing paths if relocated."""
        path = Path(path).resolve()
        document = self.to_dict()
        for section, key, name in ((document["expression"]["local"], "model_path", "expression_model_path"),
                                   (document["vision"]["detector"], "cascade_path", "cascade_path"),
                                   (document["logging"], "file", "log_file")):
            value = self.resolve_path(getattr(self, name))
            if value is not None:
                section[key] = os.path.relpath(value, path.parent)
        validated = self.from_dict(document, base_dir=path.parent)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=f".{path.name}.", delete=False) as output:
                temporary = Path(output.name)
                json.dump(validated.to_dict(), output, indent=2, allow_nan=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def resolve_path(self, path: Optional[Path]) -> Optional[Path]:
        return None if path is None else (self._base_dir / path).resolve()

    @property
    def vision_enabled(self) -> bool:
        return self.face_tracking_enabled or self.expression_enabled

    def validate(self) -> None:
        def number(name, *, minimum=0, inclusive=False, maximum=None, integer=False):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or (integer and type(value) is not int)
                    or (value < minimum if inclusive else value <= minimum)
                    or (maximum is not None and value > maximum)):
                raise ConfigurationError(f"{name}: invalid number/range")

        number("web_port", integer=True, maximum=65535)
        try:
            ipaddress.ip_address(self.web_host)
        except (ValueError, TypeError):
            raise ConfigurationError("web.host must be an IPv4 or IPv6 bind address") from None
        if not isinstance(self.web_host, str):
            raise ConfigurationError("web.host must be an IP address string")

        for name in ("display_width", "display_height", "display_fps", "expression_minimum_observations"):
            number(name, integer=True)
        number("detector_min_neighbors", inclusive=True, integer=True)
        for name in ("display_transition_seconds", "reaction_decay_per_second", "vision_capture_fps",
                     "face_detection_fps", "expression_inference_fps", "expression_local_maximum_gap_seconds",
                     "expression_scale"):
            number(name)
        number("detector_scale_factor", minimum=1)
        number("face_gaze_smoothing", maximum=1)
        number("expression_minimum_confidence", inclusive=True, maximum=1)
        number("expression_crop_margin", inclusive=True, maximum=.5)
        for name in ("web_enabled", "fullscreen", "face_tracking_enabled", "expression_enabled", "expression_neutral_enabled",
                     "expression_swap_rb", "expression_grayscale", "expression_diagnostics"):
            if type(getattr(self, name)) is not bool:
                raise ConfigurationError(f"{name} must be a boolean")
        for name in ("camera_resolution", "expression_input_size", "detector_min_size"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or len(value) != 2 or any(type(v) is not int or v <= 0 for v in value):
                raise ConfigurationError(f"{name} must contain two positive integers")
        if any(size > dimension for size, dimension in zip(self.detector_min_size, self.camera_resolution)):
            raise ConfigurationError("vision.detector.min_size cannot exceed camera_resolution")
        for name in ("blink_interval_seconds", "gaze_interval_seconds"):
            value = getattr(self, name)
            if (not isinstance(value, tuple) or len(value) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in value)
                    or value[1] < value[0]):
                raise ConfigurationError(f"{name} must contain two positive ascending numbers")
        if not isinstance(self.expression_provider, str) or self.expression_provider not in {"local", "aws"}:
            raise ConfigurationError("expression.provider must be local or aws")
        if not isinstance(self.iris_color, str) or self.iris_color not in {
            "cyan", "blue", "green", "turquoise", "amber", "violet", "white"
        }:
            raise ConfigurationError("display.iris_color must be cyan, blue, green, turquoise, amber, violet or white")
        if not isinstance(self.cloud_expression, CloudExpressionConfig):
            raise ConfigurationError("expression.aws must be CloudExpressionConfig")
        if not isinstance(self.log_level, str) or self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("logging.level must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        for name in _PATH_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, Path):
                raise ConfigurationError(f"{name} must be a Path or null")
        labels = self.expression_labels
        if (not isinstance(labels, tuple) or any(not isinstance(v, str) or not v.strip() for v in labels)
                or len(set(labels)) != len(labels)):
            raise ConfigurationError("expression.local.labels must contain unique nonempty strings")
        if (not isinstance(self.expression_mean, tuple) or len(self.expression_mean) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in self.expression_mean)):
            raise ConfigurationError("expression.local.mean must contain three finite numbers")
        if self.expression_enabled and self.expression_provider == "local" and (self.expression_model_path is None or not labels):
            raise ConfigurationError("Enabled local expressions require expression.local.model_path and labels")

    def validate_paths(self) -> None:
        """Check active model and explicit detector paths before hardware starts."""
        required = []
        if self.expression_enabled and self.expression_provider == "local":
            required.append(("expression.local.model_path", self.expression_model_path))
        if self.vision_enabled and self.cascade_path is not None:
            required.append(("vision.detector.cascade_path", self.cascade_path))
        for name, value in required:
            path = self.resolve_path(value)
            if path is None or not path.is_file() or not os.access(path, os.R_OK):
                raise ConfigurationError(f"{name}: readable file required: {path}")
        log = self.resolve_path(self.log_file)
        if log is not None and (not log.parent.is_dir() or not os.access(log.parent, os.W_OK)
                                or (log.exists() and (not log.is_file() or not os.access(log, os.W_OK)))):
            raise ConfigurationError(f"logging.file: writable file/parent required: {log}")
