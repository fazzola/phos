"""Editor conversion and persistence through the canonical configuration model."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from threading import RLock

from robot.config import ConfigurationError, RuntimeConfig, load_document


class ConfigurationService:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.lock = RLock()

    def read(self):
        document = load_document(self.path)
        # Validate schema and types before reflecting data into the UI. Inactive
        # or removed model files must not prevent fixing their paths in the editor.
        config = RuntimeConfig.from_dict(document, base_dir=self.path.parent, check_paths=False)
        return config.to_dict()

    @staticmethod
    def revision(document):
        return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()

    def save_form(self, form, *, area=None):
        with self.lock:
            document = self.read()
            if form.get("revision") != self.revision(document):
                raise ConfigurationError("Configuration changed since this page was loaded. Reload before saving.")
            # Domain pages merge only their own controls. Validate the full
            # result so cross-domain constraints still use startup's rules.
            if area is None:
                groups = editor_sections(document)  # Existing service callers.
            else:
                from robot.web.domains import domain_sections
                groups = domain_sections(document, area)
            allowed = {item["name"] for group in groups for item in group["fields"]}
            if not allowed or set(form) - allowed - {"csrf_token", "revision", "area"}:
                raise ConfigurationError("Unexpected fields for this configuration area.")
            edited = deepcopy(document)
            for group in groups:
                for item in group["fields"]:
                    route = item["name"]
                    value = form.get(route, "")
                    try:
                        if item["kind"] == "checkbox":
                            value = value == "on"
                        elif item["kind"] == "number":
                            value = json.loads(value)
                        elif item["kind"] == "array":
                            value = ([part.strip() for part in value.split(",") if part.strip()]
                                     if route == "expression.local.labels" else json.loads("[" + value + "]"))
                        elif item["nullable"] and not value.strip():
                            value = None
                    except (ValueError, TypeError):
                        raise ConfigurationError(f"{route}: enter a valid number or comma-separated list.") from None
                    keys, target = route.split("."), edited
                    for key in keys[:-1]:
                        target = target[key]
                    target[keys[-1]] = value
            RuntimeConfig.from_dict(edited, base_dir=self.path.parent).save(self.path)


# Presentation hints only. Field structure and validation belong to robot.config.
CHOICES = {"expression.provider": ("local", "aws"),
           "logging.level": ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
           "display.iris_color": ("cyan", "blue", "green", "turquoise", "amber", "violet", "white")}
HELP = {
    "web": "Disabled by default. Use the Pi's LAN IP or 0.0.0.0 for trusted LAN access. Restart after changing these settings.",
    "display": "Display dimensions are pixels; fps controls animation cadence. Iris color is a named eye theme. Display and appearance changes require PHOS restart.",
    "behavior": "Timing pairs are minimum, maximum in seconds. Smoothing controls gaze response.",
    "vision": "Tracking uses the local camera. Resolution is width, height in pixels.",
    "vision.detector": "Leave cascade path blank for platform discovery. Minimum size is width, height in pixels.",
    "expression": "Local runs ONNX on the Pi. AWS sends selected face crops to AWS when expressions are enabled. There is no automatic fallback.",
    "expression.local": "Paths are relative to the configuration file. Labels must match model output order; input size is width, height and mean is three channel values.",
    "expression.aws": "Non-secret request policy only. Credentials stay external in the AWS SDK chain; availability is not checked here. Times are seconds; zero session limit means unlimited.",
    "expression.smoothing": "Requires repeated confident observations. Keep neutral disabled until calibrated.",
    "logging": "Blank file means console only. Paths are relative to the configuration file. Enable diagnostics temporarily.",
}


def editor_sections(document, prefix=""):
    sections = []
    for name, values in document.items():
        route = f"{prefix}.{name}" if prefix else name
        direct, nested = [], {}
        for key, value in values.items():
            if isinstance(value, dict):
                nested[key] = value
                continue
            field_name = f"{route}.{key}"
            kind = ("checkbox" if isinstance(value, bool) else "number" if isinstance(value, (float, int))
                    else "array" if isinstance(value, list) else "text")
            direct.append({"name": field_name, "label": key.replace("_", " ").capitalize(),
                           "kind": kind, "value": ", ".join(map(str, value)) if isinstance(value, list) else value,
                           "nullable": value is None or field_name in {"expression.local.model_path", "vision.detector.cascade_path", "logging.file", "expression.aws.region"},
                           "choices": CHOICES.get(field_name)})
        sections.append({"name": route, "title": route.replace(".", " / ").replace("_", " ").title(),
                         "help": HELP.get(route, ""), "fields": direct})
        sections.extend(editor_sections(nested, route))
    return sections
