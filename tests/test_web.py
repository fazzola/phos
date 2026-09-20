"""Hardware-free administration/security tests using real CSRF and password hashes."""
import json
from html.parser import HTMLParser
import re
import socket
from urllib.request import urlopen

import pytest

from robot.config import ConfigurationError, RuntimeConfig, load_document
from robot.web.app import create_app
from robot.web.auth import PasswordStore
from robot.web.server import WebServer

PASSWORD = "a new long test password"


@pytest.fixture
def setup(tmp_path):
    document = load_document()
    document["logging"]["file"] = None
    path = tmp_path / "phos.json"
    path.write_text(json.dumps(document))
    now = [100.0]
    app = create_app(path, active_document=document, clock=lambda: now[0])
    app.testing = True
    return app, path, now


def csrf(response):
    return re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)).group(1)


def post(client, route, data=None):
    values = {"csrf_token": csrf(client.get("/password" if route in {"/", "/logout"} else route, follow_redirects=True)), **(data or {})}
    return client.post(route, data=values)


def login(client, password="phos"):
    return post(client, "/login", {"password": password})


def authorize(app):
    client = app.test_client()
    assert login(client).location == "/password"
    assert post(client, "/password", {"current": "phos", "new": PASSWORD, "confirmation": PASSWORD}).status_code == 302
    assert login(client, PASSWORD).location == "/"
    return client


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}
        self.select = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and "name" in a:
            if a.get("type") != "checkbox" or "checked" in a:
                self.values[a["name"]] = a.get("value", "on")
        elif tag == "select":
            self.select = a["name"]
        elif tag == "option" and "selected" in a:
            self.values[self.select] = a["value"]


def form(client, area="display"):
    parser = FormParser()
    parser.feed(client.get(f"/configuration/{area}").get_data(as_text=True))
    return parser.values


def test_bootstrap_login_forces_change_and_never_exposes_config(setup):
    app, path, _ = setup
    client = app.test_client()
    assert client.get("/").location == "/login"
    assert client.get("/password").location == "/login"
    assert client.post("/", data={}).status_code == 400
    assert login(client).location == "/password"
    assert client.get("/").location == "/password"
    assert post(client, "/", {}).location == "/password"
    page = client.get("/password").get_data(as_text=True)
    assert "First login" in page
    data = json.loads((path.parent / ".phos-admin/password.json").read_text())
    assert "phos" not in data["password_hash"]
    assert data["must_change"] is True
    assert (path.parent / ".phos-admin").stat().st_mode & 0o777 == 0o700
    assert (path.parent / ".phos-admin/password.json").stat().st_mode & 0o777 == 0o600


def test_incorrect_login_and_password_validation(setup):
    app, _, now = setup
    client = app.test_client()
    assert login(client, "wrong").status_code == 401
    assert login(client).status_code == 302
    for current, new, confirm in [("wrong", PASSWORD, PASSWORD), ("phos", "short", "short"), ("phos", PASSWORD, "different")]:
        response = post(client, "/password", {"current": current, "new": new, "confirmation": confirm})
        assert response.status_code == 400
        assert 'value="phos"' not in response.get_data(as_text=True)
    assert app.extensions["phos_passwords"].must_change
    now[0] += 61
    assert post(client, "/password", {"current": "phos", "new": PASSWORD, "confirmation": PASSWORD}).status_code == 302
    assert login(client).status_code == 401
    assert login(client, PASSWORD).location == "/"


def test_password_change_revokes_all_sessions_and_persists(setup):
    app, path, now = setup
    first = authorize(app)
    second = app.test_client()
    assert login(second, PASSWORD).status_code == 302
    now[0] += 61
    replacement = "a different long password"
    assert post(first, "/password", {"current": PASSWORD, "new": replacement, "confirmation": replacement}).status_code == 302
    assert first.get("/").location == "/login"
    assert second.get("/").location == "/login"
    assert login(first, PASSWORD).status_code == 401
    assert login(first, replacement).location == "/"
    reloaded = PasswordStore(path.parent / ".phos-admin")
    assert reloaded.verify(replacement) and not reloaded.must_change


def test_logout_cookie_replay_and_expiration(setup):
    app, _, now = setup
    client = authorize(app)
    cookie = client.get_cookie("phos_admin").value
    assert client.get("/logout").status_code == 405
    assert post(client, "/logout").location == "/login"
    client.set_cookie("phos_admin", cookie)
    assert client.get("/").location == "/login"
    assert login(client, PASSWORD).location == "/"
    now[0] += 1801
    assert client.get("/").location == "/login"


@pytest.mark.parametrize("route", ["/", "/password", "/logout", "/login"])
def test_csrf_protects_every_mutation(setup, route):
    app, path, _ = setup
    client = authorize(app)
    original = path.read_bytes()
    assert client.post(route, data={"password": PASSWORD}).status_code == 400
    assert client.post(route, data={"csrf_token": "forged"}).status_code == 400
    assert path.read_bytes() == original


def test_login_rate_limit_is_global_and_expires(setup):
    app, _, now = setup
    for _ in range(5):
        assert login(app.test_client(), "wrong").status_code == 401
    client = app.test_client()
    response = login(client)
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"
    now[0] += 61
    assert login(client).location == "/password"


def test_configuration_controls_switch_both_providers_and_persist(setup):
    app, path, _ = setup
    client = authorize(app)
    model = path.parent / "model.onnx"
    model.write_bytes(b"fake model; never inferred")
    for provider in ("aws", "local"):
        data = form(client, "expression")
        data.update({"expression.provider": provider, "expression.enabled": "on",
                     "expression.local.model_path": "model.onnx"})
        response = client.post("/", data=data)
        assert response.status_code == 302
        config = RuntimeConfig.from_file(path)
        assert config.expression_provider == provider and config.expression_enabled
        assert config.display_fps == 30
        page = client.get("/configuration/expression").get_data(as_text=True)
        assert "Configuration saved. Restart PHOS to apply changes." in page
        status = client.get("/configuration/status").get_data(as_text=True)
        assert "Saved configuration differs" in status
        assert "<dt>Startup expression provider</dt><dd>local" in status
        assert "Expression Recognition" in page


@pytest.mark.parametrize("field,value", [("display.fps", "0"), ("vision.camera_resolution", "1,2,3"),
    ("expression.aws.refresh_seconds", "999999"), ("expression.provider", "bad"),
    ("display.fps", "not-a-number"), ("web.port", "65536")])
def test_invalid_form_preserves_file_and_input(setup, field, value):
    app, path, _ = setup
    client = authorize(app)
    old = path.read_bytes()
    area = {"display": "display", "vision": "vision", "expression": "expression", "web": "network"}[field.split(".")[0]]
    data = form(client, area)
    preserved, entered = {"display": ("display.width", "777"), "vision": ("vision.capture_fps", "13"),
                          "expression": ("expression.aws.region", "test-region"), "network": ("web.host", "192.168.1.127")}[area]
    data.update({field: value, preserved: entered})
    response = client.post("/", data=data)
    assert response.status_code == 400
    assert path.read_bytes() == old
    assert f'value="{entered}"' in response.get_data(as_text=True)


def test_stale_form_cannot_overwrite_new_save(setup):
    app, path, _ = setup
    client = authorize(app)
    old = form(client)
    new = dict(old, **{"display.fps": "21"})
    assert client.post("/", data=new).status_code == 302
    assert client.post("/", data=old).status_code == 400
    assert RuntimeConfig.from_file(path).display_fps == 21


def test_aws_secrets_never_exposed_or_persisted(setup, monkeypatch, caplog):
    app, path, _ = setup
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "SENSITIVE_TEST_VALUE")
    client = authorize(app)
    data = form(client, "expression")
    assert not any("access_key" in name or "token" in name and name != "csrf_token" for name in data)
    data["expression.aws.access_key"] = "SENSITIVE_TEST_VALUE"
    assert client.post("/", data=data).status_code == 400
    assert "SENSITIVE_TEST_VALUE" not in client.get("/").get_data(as_text=True) + path.read_text() + caplog.text
    assert PASSWORD not in path.read_text() + caplog.text


def test_safe_save_failure_keeps_existing_configuration(setup, monkeypatch):
    app, path, _ = setup
    client = authorize(app)
    original = path.read_bytes()
    data = form(client)
    data["display.fps"] = "19"
    def fail(*args):
        raise OSError("simulated replace failure")
    monkeypatch.setattr("robot.config.os.replace", fail)
    assert client.post("/", data=data).status_code == 503
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".phos.json.*"))


def test_missing_active_model_can_be_repaired_in_editor(setup):
    app, path, _ = setup
    client = authorize(app)
    document = load_document(path)
    document["expression"]["enabled"] = True
    path.write_text(json.dumps(document))
    assert client.get("/").status_code == 200
    data = form(client, "expression")
    data.pop("expression.enabled")
    assert client.post("/", data=data).status_code == 302
    assert not RuntimeConfig.from_file(path).expression_enabled


def test_security_headers_and_cookie(setup):
    app, _, _ = setup
    response = app.test_client().get("/login")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_corrupt_password_store_fails_closed_and_local_reset_bootstraps(setup):
    _, path, _ = setup
    directory = path.parent / ".phos-admin"
    (directory / "password.json").write_text("broken")
    with pytest.raises(ValueError):
        PasswordStore(directory)
    directory.rename(path.parent / "retired-admin")
    reset = PasswordStore(directory)
    assert reset.must_change and reset.verify("phos")


@pytest.mark.parametrize("key,value", [("enabled", "true"), ("port", True), ("port", 0),
                                       ("port", 65536), ("host", 123), ("host", "hostname")])
def test_web_settings_use_canonical_validation(key, value, tmp_path):
    document = load_document()
    document["web"][key] = value
    with pytest.raises(ConfigurationError):
        RuntimeConfig.from_dict(document, base_dir=tmp_path)


def test_real_web_worker_serves_and_releases_port(setup):
    _, path, _ = setup
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    document = load_document(path)
    document["web"].update(enabled=True, host="127.0.0.1", port=port)
    config = RuntimeConfig.from_dict(document, base_dir=path.parent)
    worker = WebServer(path, config)
    with pytest.raises(RuntimeError, match="simulated runtime failure"):
        with worker:
            assert worker.process.is_alive()
            with urlopen(f"http://127.0.0.1:{port}/login", timeout=5) as response:
                assert b"Administrator login" in response.read()
            raise RuntimeError("simulated runtime failure")
    assert worker.process is None
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))


def test_password_save_failure_keeps_old_hash_and_session(setup, monkeypatch):
    app, path, now = setup
    client = authorize(app)
    now[0] += 61
    credential = path.parent / ".phos-admin/password.json"
    before = credential.read_bytes()
    def fail(*args):
        raise OSError("simulated credential replace failure")
    monkeypatch.setattr("robot.web.auth.os.replace", fail)
    response = post(client, "/password", {"current": PASSWORD, "new": "another long password", "confirmation": "another long password"})
    assert response.status_code == 503
    assert credential.read_bytes() == before
    assert app.extensions["phos_passwords"].verify(PASSWORD)
    assert client.get("/").status_code == 200
    assert list(credential.parent.iterdir()) == [credential]


def test_main_owns_enabled_worker_and_cleans_up_on_runtime_failure(setup, monkeypatch):
    from robot import main
    app, path, _ = setup
    document = load_document(path)
    document["web"]["enabled"] = True
    path.write_text(json.dumps(document))
    seen = []
    class Worker:
        def __init__(self, config_path, config):
            assert config_path == path and config.web_enabled
        def __enter__(self):
            seen.append("start")
        def __exit__(self, *args):
            seen.append("stop")
    async def fail(*, config):
        assert seen == ["start"]
        raise RuntimeError("runtime failed")
    monkeypatch.setattr("robot.web.server.WebServer", Worker)
    monkeypatch.setattr(main, "async_main", fail)
    monkeypatch.setattr(main.logging, "basicConfig", lambda **kw: None)
    monkeypatch.setattr("sys.argv", ["phos", "--config", str(path)])
    with pytest.raises(RuntimeError, match="runtime failed"):
        main.main()
    assert seen == ["start", "stop"]


def test_disabled_worker_does_not_spawn_or_create_credentials(tmp_path, monkeypatch):
    config = RuntimeConfig.from_file()
    monkeypatch.setattr("robot.web.server.multiprocessing.get_context", lambda *a: pytest.fail("disabled web spawned"))
    with WebServer(tmp_path / "phos.json", config) as worker:
        assert worker.process is None
    assert not (tmp_path / ".phos-admin").exists()


def test_sessions_do_not_survive_worker_restart(setup):
    app, path, _ = setup
    client = authorize(app)
    cookie = client.get_cookie("phos_admin").value
    restarted = create_app(path).test_client()
    restarted.set_cookie("phos_admin", cookie)
    assert restarted.get("/").location == "/login"
    assert login(restarted, PASSWORD).location == "/"


@pytest.mark.parametrize("background_path,status", [("/favicon.ico", 404), ("/", 302), ("/missing", 404)])
def test_browser_background_requests_preserve_login_csrf(setup, background_path, status):
    app, _, _ = setup
    client = app.test_client()
    token = csrf(client.get("/login"))
    assert client.get(background_path).status_code == status
    response = client.post("/login", data={"csrf_token": token, "password": "phos"})
    assert response.status_code == 302
    assert response.location == "/password"


def test_csrf_error_explains_recovery_without_logging_secrets(setup, caplog):
    app, _, _ = setup
    response = app.test_client().post("/login", data={"password": "secret-test-password"})
    assert response.status_code == 400
    assert b"allow cookies" in response.data
    assert "Administration CSRF rejection" in caplog.text
    assert "secret-test-password" not in caplog.text



def test_domain_pages_partition_canonical_fields_and_are_protected(setup):
    from robot.web.domains import DOMAINS, GROUPS
    from robot.web.configuration import editor_sections
    app, path, _ = setup
    anonymous = app.test_client()
    for area in DOMAINS:
        assert anonymous.get(f"/configuration/{area}").location == "/login"
    client = authorize(app)
    exposed = []
    for area in DOMAINS:
        response = client.get(f"/configuration/{area}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert f'<h2>{DOMAINS[area]["title"].replace("&", "&amp;")}</h2>' in page
        assert 'aria-current="page"' in page
        controls = form(client, area)
        settings = [name for name in controls if "." in name]
        exposed.extend(settings)
        if area not in GROUPS:
            assert not settings
            assert client.post(f"/configuration/{area}", data=controls).status_code == 405
        else:
            assert client.post(f"/configuration/{area}", data={}).status_code == 400
    # Checkboxes that are off are omitted from successful form values, but still
    # need to be present exactly once in the rendered pages.
    all_html = "".join(client.get(f"/configuration/{area}").get_data(as_text=True) for area in GROUPS)
    for group in editor_sections(load_document(path)):
        for field in group["fields"]:
            assert all_html.count(f'name="{field["name"]}"') == 1
    assert len(exposed) == len(set(exposed))
    assert client.get("/configuration/sensors").status_code == 404


def test_each_domain_save_preserves_other_domains_and_rejects_injected_fields(setup):
    app, path, _ = setup
    client = authorize(app)
    before = load_document(path)
    data = form(client, "network")
    data["web.port"] = "8181"
    assert client.post("/configuration/network", data=data).status_code == 302
    after = load_document(path)
    expected = json.loads(json.dumps(before))
    expected["web"]["port"] = 8181
    assert after == expected
    # A Network form cannot silently modify Display or disable the web service.
    data = form(client, "network")
    data.update({"display.fps": "1", "web.enabled": "on"})
    assert client.post("/configuration/network", data=data).status_code == 400
    assert load_document(path) == after
    data = form(client, "security")
    data["web.enabled"] = "on"
    assert client.post("/configuration/security", data=data).status_code == 302
    assert load_document(path)["web"] == {"enabled": True, "host": "127.0.0.1", "port": 8181}


def test_cross_domain_validation_links_to_relevant_area(setup):
    app, path, _ = setup
    client = authorize(app)
    document = load_document(path)
    document["expression"]["enabled"] = True
    document["expression"]["local"]["model_path"] = "missing.onnx"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    data = form(client, "display")
    data["display.width"] = "777"
    response = client.post("/configuration/display", data=data)
    assert response.status_code == 400
    assert b'/configuration/expression#local' in response.data
    assert b'value="777"' in response.data
    assert path.read_bytes() == before


def test_expression_groups_status_and_separate_password_page(setup, monkeypatch):
    app, _, _ = setup
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-never-rendered")
    client = authorize(app)
    page = client.get("/configuration/expression").get_data(as_text=True)
    for label in ("Provider selection", "Local ONNX provider", "AWS provider", "Cloud cost &amp; rate limits"):
        assert label in page
    assert page.count('data-provider="aws"') == 2
    assert 'data-provider="local"' in page
    assert 'name="display.width"' not in page
    status = client.get("/configuration/status").get_data(as_text=True)
    assert "Not monitored" in status and "Not checked" in status
    assert 'name="revision"' not in status
    security = client.get("/configuration/security").get_data(as_text=True)
    assert 'href="/password"' in security
    assert 'type="password"' not in security
    logging = client.get("/configuration/logging").get_data(as_text=True)
    assert 'name="logging.level"' in logging and 'name="logging.file"' in logging
    assert 'name="logging.expression_diagnostics"' in logging
    assert "SDK credential/request debug output remains suppressed" in logging
    assert "secret-never-rendered" not in page + status + security + logging


def test_domain_error_hints_match_fields_without_matching_unrelated_words():
    from robot.web.domains import error_domain
    document = load_document()
    assert error_domain(document, "display_fps: invalid number/range") == ("display", "display")
    assert error_domain(document, "expression.local.model_path: readable file required") == ("expression", "local")
    assert error_domain(document, "expression.aws: refresh_seconds must be less than cache_ttl_seconds") == ("expression", "cloud-limits")
    assert error_domain(document, "Check local filesystem permissions.") == (None, None)
