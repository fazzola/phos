"""Navigation and presentation groups, never a configuration schema.

New implemented areas can register a page and select canonical field paths here.
No defaults, types or validation rules belong in this module.
"""
import re

from robot.web.configuration import editor_sections

DOMAINS = {
    "general": {"title": "General", "description": "Choose an area to manage PHOS. Save changes within each page before navigating away."},
    "network": {"title": "Network", "description": "Choose where web administration listens. Wi-Fi and other operating-system network settings are managed on the Pi."},
    "display": {"title": "Display & Appearance", "description": "Display size, animation timing and eye behavior."},
    "vision": {"title": "Vision", "description": "Local camera tracking, capture cadence and face detection."},
    "expression": {"title": "Expression Recognition", "description": "Select a provider and configure observations, model preprocessing and cloud request limits."},
    "logging": {"title": "Logging", "description": "Log level, destination and expression diagnostics. SDK credential/request debug output remains suppressed; no credential or payload logging controls are provided."},
    "security": {"title": "Web Administration / Security", "description": "Enable administration and manage your administrator password separately from runtime settings."},
    "status": {"title": "System / Status", "description": "Read-only startup information and saved configuration status. This page does not monitor live robot health."},
}

# Paths select fields that already exist in the canonical document. A trailing
# dot selects a whole implemented section; all other entries select one field.
GROUPS = {
    "network": [("listener", "Administration address", ("web.host", "web.port"), None)],
    "display": [("display", "Display", ("display.",), None),
                ("behavior", "Eye behavior", ("behavior.",), None)],
    "vision": [("vision", "Camera & tracking", ("vision.face_tracking_enabled", "vision.camera_resolution", "vision.capture_fps", "vision.detection_fps"), None),
               ("detector", "Face detection", ("vision.detector.",), None)],
    "expression": [
        ("provider", "Provider selection", ("expression.enabled", "expression.provider", "expression.inference_fps", "expression.crop_margin"), None),
        ("smoothing", "Observation smoothing", ("expression.smoothing.",), None),
        ("local", "Local ONNX provider", ("expression.local.",), "local"),
        ("aws", "AWS provider — non-secret settings", ("expression.aws.region", "expression.aws.minimum_face_confidence", "expression.aws.connect_timeout_seconds", "expression.aws.read_timeout_seconds"), "aws"),
        ("cloud-limits", "Cloud cost & rate limits", ("expression.aws.cooldown_seconds", "expression.aws.stable_seconds", "expression.aws.refresh_seconds", "expression.aws.cache_ttl_seconds", "expression.aws.max_requests_per_minute", "expression.aws.max_requests_per_session", "expression.aws.change_threshold", "expression.aws.retry_initial_seconds", "expression.aws.retry_max_seconds"), "aws"),
    ],
    "logging": [("logging", "Safe logging settings", ("logging.",), None)],
    "security": [("web", "Administration service", ("web.enabled",), None)],
}


def domain_sections(document, area):
    canonical = editor_sections(document)
    fields = [item for group in canonical for item in group["fields"]]
    result = []
    for key, title, selectors, provider in GROUPS.get(area, ()):
        selected = [item for item in fields if any(
            item["name"].startswith(selector) if selector.endswith(".") else item["name"] == selector
            for selector in selectors)]
        hints = dict.fromkeys(group["help"] for group in canonical
                             if any(item in selected for item in group["fields"]))
        result.append({"name": key, "title": title, "provider": provider,
                       "fields": selected, "help": " ".join(hints)})
    return result


def error_domain(document, error):
    """Locate canonical validator messages for navigation, without revalidating."""
    message = str(error)
    candidates = []
    for area in GROUPS:
        for group in domain_sections(document, area):
            for field in group["fields"]:
                name = field["name"]
                for token in (name, name.replace(".", "_"), name.rsplit(".", 1)[-1]):
                    if re.search(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", message):
                        candidates.append((len(token), area, group["name"]))
    return max(candidates)[1:] if candidates else (None, None)
