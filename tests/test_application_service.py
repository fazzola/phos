from robot.core.runtime import RobotCore
from robot.core.behavior_engine import BehaviorEngine
from robot.services import PhosApplicationService


class Runtime:
    def __init__(self):
        self.core = RobotCore()
        self._behavior_engine = BehaviorEngine(self.core.events)

    def sensor_status(self):
        return {
            "environmental": {"status": "available", "available": True, "measurements": {"temperature_c": 21.5}},
            "ccs811": {"status": "warming_up", "available": False},
            "imu": {"status": "unavailable", "available": False},
        }

    def apply_base_visual_source(self, config):
        self._behavior_engine.configure_base_visual_source(config.base_visual_source)


def test_status_has_semantic_environment_and_health():
    service = PhosApplicationService(Runtime())
    status = service.status()
    assert status["environment"]["status"] == "available"
    assert status["health"]["subsystems"]["ccs811"]["state"] == "warming_up"
    assert status["health"]["subsystems"]["imu"]["state"] == "unavailable"


def test_visual_source_rejects_hardware_command_and_events_are_deduplicated():
    service = PhosApplicationService(Runtime())
    events = []
    service.subscribe(events.append)
    service.set_visual_source("environment")
    service.set_visual_source("environment")
    assert [event["type"] for event in events] == ["visual_state_changed"]
    try:
        service.set_visual_source("gpio18")
    except Exception as error:
        assert error.code == "invalid_visual_source"
    else:
        raise AssertionError("hardware command was accepted")
