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
    response = client.post("/api/v1/visual-source", json={"source": "GPIO18"})
    assert response.status_code == 400
    assert response.json == {"error": {"code": "invalid_visual_source", "message": "Unsupported visual source.",
                                        "details": {"source": "GPIO18"}}}
