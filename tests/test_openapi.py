from flask import Flask

from robot.web.api import create_api
from robot.web.openapi import validate


class Service:
    def status(self): return {}
    def robot_state(self): return {}
    def environment(self): return {}
    def motion(self): return {}
    def health(self): return {}
    def config(self): return {}
    def update_config(self, value): return {}
    def set_expression(self, value): return {}
    def set_state(self, value): return {}
    def set_visual_source(self, value): return {}
    def subscribe(self, listener): return lambda: None
    def emit_snapshot_changes(self): pass


def test_openapi_is_valid_and_covers_every_public_api_route():
    spec = validate()
    app = Flask(__name__)
    app.register_blueprint(create_api(Service()))
    actual = {(rule.rule, method.lower()) for rule in app.url_map.iter_rules()
              if rule.rule.startswith("/api/v1/") for method in rule.methods
              if method not in {"HEAD", "OPTIONS"}}
    documented = {(path, method) for path, operations in spec["paths"].items()
                  for method in operations}
    assert actual == documented
