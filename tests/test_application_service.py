from robot.core.runtime import RobotCore
from robot.core.behavior_engine import BehaviorEngine
from robot.services.application import COMMANDS, PhosApplicationService
from robot.core.environmental import EnvironmentalState
from robot.core.state import RobotState
from robot.motion import MotionState
from robot.web.openapi import _resolve, load_spec


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


def test_capabilities_are_derived_from_canonical_semantic_enums():
    service = PhosApplicationService(Runtime())
    capabilities = service.capabilities()
    observable = capabilities["observable_states"]
    assert observable["robot_state"] == [item.value for item in RobotState]
    assert observable["motion_state"] == [item.value for item in MotionState]
    assert observable["environmental_state"] == [item.value for item in EnvironmentalState]
    assert observable["environmental_overlays"]["temperature"] == ["none", "cold", "warm"]
    assert observable["environmental_overlays"]["air_quality"] == ["none", "warning", "bad"]
    for name, definition in COMMANDS.items():
        assert capabilities["commands"][name] == {
            "method": definition.method, "endpoint": definition.endpoint,
            "field": definition.field, "allowed_values": definition.allowed_values,
        }
    assert "error" not in capabilities["commands"]["set_robot_state"]["allowed_values"]


def test_command_validation_capabilities_and_openapi_enums_stay_synchronized():
    capabilities = PhosApplicationService(Runtime()).capabilities()
    spec = load_spec()
    command_schemas = spec["components"]["schemas"]["Capabilities"]["properties"]["commands"]["properties"]
    for name, definition in COMMANDS.items():
        capability_schema = _resolve(spec, command_schemas[name]["$ref"])
        capability_values = capability_schema["properties"]["allowed_values"]["items"]["enum"]
        request_schema = spec["paths"][definition.endpoint][definition.method.lower()]["requestBody"]["content"]["application/json"]["schema"]
        request_schema = _resolve(spec, request_schema["$ref"]) if "$ref" in request_schema else request_schema
        request_values = request_schema["properties"][definition.field]
        request_values = _resolve(spec, request_values["$ref"]) if "$ref" in request_values else request_values
        assert definition.allowed_values == capabilities["commands"][name]["allowed_values"]
        assert definition.allowed_values == capability_values == request_values["enum"]


def test_runtime_only_or_unmapped_values_are_not_accepted_as_writable_commands():
    service = PhosApplicationService(Runtime())
    for command, value, code in ((service.set_state, "error", "unsupported_state_command"),
                                 (service.set_expression, "worried", "unsupported_expression_command")):
        try:
            command(value)
        except Exception as error:
            assert error.code == code
        else:
            raise AssertionError(f"{value} was accepted despite not being writable")
