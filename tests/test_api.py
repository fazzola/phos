from flask import Flask

from robot.core.runtime import RobotCore
from robot.core.behavior_engine import BehaviorEngine
from robot.services import PhosApplicationService
from robot.web.api import create_api


class Runtime:
    def __init__(self):
        self.core = RobotCore()
        self._behavior_engine = BehaviorEngine(self.core.events)

    def sensor_status(self):
        return {"environmental": {"status": "available", "available": True},
                "ccs811": {"status": "warming_up"}}

    def apply_base_visual_source(self, config):
        self._behavior_engine.configure_base_visual_source(config.base_visual_source)


def test_versioned_status_and_stable_error_document():
    app = Flask(__name__)
    app.register_blueprint(create_api(PhosApplicationService(Runtime())))
    client = app.test_client()
    assert client.get("/api/v1/status").status_code == 200
    capabilities = client.get("/api/v1/capabilities").json
    assert capabilities["commands"]["set_visual_source"]["allowed_values"] == ["manual", "environment", "state"]
    assert capabilities["commands"]["set_robot_state"] == {"endpoint": "/api/v1/state", "method": "POST",
                                                               "field": "state", "allowed_values": ["idle", "listening", "thinking", "speaking", "sleeping"]}
    response = client.post("/api/v1/visual-source", json={"source": "GPIO18"})
    assert response.status_code == 400
    assert response.json == {"error": {"code": "invalid_visual_source", "message": "Unsupported visual source.",
                                        "details": {"source": "GPIO18"}}}
    overlay = client.post("/api/v1/overlay", json={"temperature": "warm", "air_quality": "warning", "duration_ms": 3000})
    assert overlay.status_code == 200
    assert overlay.json["resolved"] == {"temperature": "warm", "air_quality": "warning"}
    assert client.delete("/api/v1/overlay").json["override"]["active"] is False


def test_local_openapi_and_documentation_routes():
    from pathlib import Path
    from robot.web.app import create_app
    runtime = Runtime()
    app = create_app(Path("config/phos.json"), application_service=PhosApplicationService(runtime))
    # Documentation is still protected by the same local-admin authentication
    # boundary in a complete app; route registration is verified directly.
    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert {"/openapi.json", "/docs"} <= routes
    assert "/redoc" not in routes
    with app.test_request_context("/docs"):
        response = app.process_response(app.view_functions["api_docs"]())
    document = response.get_data(as_text=True)
    assert "https://" not in document and "http://" not in document
    assert "/static/swagger-ui/swagger-ui-bundle.js" in document
    assert "/static/swagger-ui/swagger-ui.css" in document
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:")
    assert app.test_client().get("/static/swagger-ui/swagger-ui-bundle.js").status_code == 200
