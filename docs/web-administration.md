# PHOS web administration user manual

PHOS includes an optional single-administrator configuration editor. It uses the
same JSON model and validation as startup, with no camera, AWS or display access
from the web worker. Saving never applies settings. Reload applies logging level,
supported eye appearance and camera preview settings; other runtime changes
require restarting PHOS.

## Install and enable

Use the [PHOS 1.0.0 installation procedure](installation.md#phos-100-reproducible-installation)
on the Pi (Python 3.11+). In `/home/pi/phos`, create the virtual environment with
`--system-site-packages` so the system camera/OpenCV/Tk packages remain available,
then install the pinned web dependencies:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-web.txt
```

`run_pi.sh` now copies that snapshot and the manual alongside source. Full
package installs may use `.venv/bin/python -m pip install -c requirements-web.txt
'.[web]'`. The existing Python >=3.9 package compatibility remains, but older
interpreters are not the pinned release-installation baseline.

The canonical `web` section defaults to `enabled: false`, `host: "127.0.0.1"`,
`port: 8080`, preserving eyes-only startup without extra dependencies. Existing
deployments must add this required section to their complete JSON file; source
sync does not overwrite deployed settings.

For access from another device on a **trusted LAN**, edit the existing section:

```json
"web": {
  "enabled": true,
  "host": "0.0.0.0",
  "port": 8080
}
```

An explicit LAN interface IP is more restrictive than `0.0.0.0`, which binds all
IPv4 interfaces. IPv6 literals are also accepted. Hostnames are not bind settings.
No separate web CLI flags exist.

Use the [user systemd service](installation.md#managed-startup-and-browser-restart)
for production and browser restart. For a foreground diagnostic run:

```bash
cd /home/pi/phos
.venv/bin/python src/robot/main.py --config config/phos.json
```

With dependencies already available to system Python, the unchanged command is
`python3 src/robot/main.py --config config/phos.json`.
Open **http://<PI-LAN-IP>:8080/** from your phone, tablet or desktop. Obtain the
Pi address locally with `hostname -I`. With the default loopback binding, only
**http://127.0.0.1:8080/** on the Pi can connect. A custom port changes both URLs.
Do not configure router port forwarding or expose this interface to the Internet.

## First login and password changes

1. Enter the bootstrap password **`phos`**; there is no username field.
2. The editor remains inaccessible until you change that password.
3. Enter current password `phos`, a different new password of 12–256 characters,
   and its confirmation. Prefer a long, unique passphrase.
4. Log in again using the new password. Configuration is now available.

Use **Change password** later; current password and confirmation are required.
Every successful change ends all sessions, including your own. **Log out** also
invalidates that session on the server. Sessions expire after 30 minutes from
login (not extended by activity) and all expire when PHOS restarts. Up to 32
sessions are retained; a new login beyond that retires the oldest.

The single account permits five password-verification attempts per minute across
all clients, including successful logins and password-change attempts. Wait one
minute after a throttle message. This global budget prevents bypass by changing
IP or cookies, but another LAN client can temporarily deny login. Limits reset
on restart. There is no persistent lockout or remote password reset.

## Edit configuration

The administration home is **General**, with links to each configuration domain.
The same navigation appears on every authenticated page and wraps for phone and
tablet screens. The current page is highlighted. No frontend framework is needed.

| Page | Settings and actions |
| --- | --- |
| General | Overview and navigation to configuration pages. |
| Network | Web bind address (`web.host`) and port (`web.port`). Wi-Fi, DNS and other OS networking remain managed on the Pi. |
| Display & Appearance | Display dimensions, fps, fullscreen and transitions; blink/gaze intervals, gaze smoothing and reaction decay from `behavior`. |
| Vision | Face tracking, camera resolution/cadence, face detection and optional display-only camera picture-in-picture preview. |
| Expression Recognition | Provider selection/enabling and observation cadence/crop margin; smoothing; local ONNX model, labels and preprocessing; AWS region/confidence/timeouts; a separate cloud cost/rate-limit group. |
| Logging | Supported log level, output file and expression diagnostics. No credential/payload logging switches; SDK credential/request debug output remains suppressed. |
| Web Administration / Security | Enable/disable web administration (`web.enabled`) and a link to the separate password-change page. Passwords are never runtime configuration. |
| System / Status | Read-only PHOS version, configuration path, active expression provider/enabled state, last successful load/reload time, saved-versus-active comparison and restart-required fields. Live robot state is not monitored and AWS credential availability is not probed. |

Active-configuration information is shown on **System / Status**, visually separated
from editable settings. Deprecated CLI overrides, if used, appear in startup
settings but do not change the saved file. The software version comes from the authoritative `robot.__version__`; live
health is not inferred from the active configuration snapshot.

Every editable page has its own **Save** button. It merges only that page's
fields into the same canonical JSON file, validates the **complete configuration**,
and atomically saves it. Other areas are preserved. There are no per-page
configuration files or independent validation schemas. Save before navigating
away: unsaved input is not carried between pages. A save in another tab makes
previously loaded pages stale, including pages in other areas.

Fields use checkboxes, numeric inputs, text inputs, comma-separated arrays and
provider/log-level dropdowns. Optional paths/region may be blank. Numeric pairs
are entered as `640, 480` or `3.5, 6.5`; labels are entered in model-output order.
The canonical model remains authoritative for all ranges, types and relationships;
see [the field reference](development.md#field-reference).

Navigation is defined by a small domain registry, separate from the canonical
schema. Future implemented subsystems can add areas there. Sensors, LED Ring,
Audio, Voice, LLM, Home Assistant, Remote API and MCP have no settings or
placeholder pages in this milestone.

Choose **local** or **aws** under Expression Recognition. The matching provider fields are
shown; switching keeps the inactive provider's settings for later use. Both
sections remain accessible if JavaScript is disabled. Enabling local expressions
requires a readable ONNX model and valid labels. AWS selection does not require
an ONNX file. Switching the provider does not implicitly enable expressions.

**AWS mode sends selected face crops to AWS when expressions are enabled.**
Credentials remain exclusively in the external SDK chain/environment/profile/
role mechanism. There are no access-key, secret-key or token fields. This editor
does not probe credential availability or make AWS requests.

**Save** on an editable page converts fields and calls the same model validation and
atomic persistence used elsewhere. Invalid input leaves the file unchanged,
displays an error in the relevant group and preserves non-sensitive input.
If validation finds a problem in another area, the page links to that area;
the current changes remain unsaved. All fields, including
inactive provider fields, must remain valid. After a validation error all provider
groups are shown so inactive settings can also be corrected. Config-relative model/log
paths keep their existing interpretation. Missing active model paths can be
repaired in the editor while PHOS is already running; malformed JSON or invalid
schema edited outside the UI requires local repair.

Successful saves report that configuration is saved and direct you to **System
 actions**. Save alone does not change running settings. Use Reload for logging,
eye appearance and camera preview settings, or Restart PHOS for all other changes.
Turning web off takes effect at
restart. A page loaded before another save is rejected as stale: reload it
before editing again. Do not edit the JSON simultaneously from the terminal.

Saving flushes a temporary file in the same directory, then atomically replaces
the target file. A validation or replacement failure preserves the old target.
No automatic previous-version backup is kept. Before editing, use for example:

```bash
cp config/phos.json config/phos.json.backup
```

To recover, stop PHOS, restore a known-good complete file with
`cp config/phos.json.backup config/phos.json`, and restart. An interrupted worker
may leave an unused hidden temporary file; it is never loaded as configuration.

## Local password recovery and storage

Credential data is in **`.phos-admin/password.json` beside the selected JSON
file**: normally `/home/pi/phos/config/.phos-admin/password.json`. This stores
only a salted Werkzeug PBKDF2-SHA256 hash (1,000,000 iterations) and the mandatory
change flag. No plaintext password, session key or AWS credential is stored.
The directory is owner-only (`0700`) and file owner-only (`0600`); run PHOS as
its normal OS user. All selected configuration files in the same directory
share this administrator store. Only one PHOS web instance per store is supported.

Forgotten password recovery requires local filesystem/terminal access:

1. Stop PHOS completely.
2. Disable LAN access temporarily by setting `web.host` to `127.0.0.1`, or
   disconnect the Pi from the network during bootstrap.
3. Move the entire credential directory aside (choose an unused backup name):

   ```bash
   cd /home/pi/phos
   mv config/.phos-admin config/.phos-admin-recovery-backup
   ```

4. Restart PHOS. A missing credential directory is created with bootstrap
   password `phos`. Complete the mandatory change locally.
5. Restore the desired trusted-LAN binding and restart. Retired hash backups
   remain sensitive local files; do not commit or share them.

For a custom configuration, use its parent directory instead of `config/`.
A missing or corrupt password file *inside an existing directory* fails closed;
it never silently re-enables `phos`. Use the same whole-directory recovery
procedure. Do not delete only `password.json` while the server is running.

## Security and operational limits

- This milestone serves **HTTP**, without TLS. Passwords and session cookies
  can be intercepted on an untrusted network. Only use a trusted LAN; perform
  initial password setup locally where possible. Public Internet access, cloud
  access and reverse-proxy/TLS deployment are outside this milestone.
- Flask signed cookies use a random per-worker secret, HttpOnly and
  SameSite=Strict. Secure is intentionally unset because this server uses HTTP;
  setting it would prevent LAN browser login over HTTP. Server-side random
  session IDs allow logout/password-change revocation and absolute expiry.
- Flask-WTF protects all POST actions, including login, password changes, saves
  and logout, against CSRF. Pages use escaping, a restrictive content security
  policy, no-store caching and anti-framing headers. Password fields are never
  repopulated. Request bodies and credentials are not logged.
- Waitress runs in a separate process with two threads, bounded connections and
  request sizes. Password hashing cannot block the render event loop, but all
  work still shares the Pi's limited CPU. Measure performance on target hardware.
- The worker starts before the runtime; a startup failure prevents a misleading
  enabled-but-unreachable launch. Missing dependencies, invalid credential
  permissions and occupied ports must be fixed locally. Shutdown terminates
  the worker and releases its port, even if runtime startup fails. If the worker
  crashes later, the robot continues; restart PHOS to recover administration.
- Filesystem access is trusted. The editor can select model/cascade/log paths
  within the privileges of the PHOS OS account. Run as a normal user, not root.
- Configurations/credentials are atomically replaced, but there is no automatic
  backup, cross-process edit lock, arbitrary subsystem hot reload or high-availability service. A dead web worker
  now causes graceful parent shutdown and a nonzero exit for systemd recovery.

Implementation uses [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/),
[Flask-WTF CSRF protection](https://flask-wtf.readthedocs.io/en/1.2.x/csrf/),
[Werkzeug password hashing](https://werkzeug.palletsprojects.com/en/stable/utils/#werkzeug.security.generate_password_hash)
and [Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html).

## Verification on the Pi

Enable LAN access, start PHOS, complete the first login, and check the editor
from a phone and desktop. Open Display & Appearance, save a harmless display setting and confirm the eyes
keep running unchanged until restart. Verify the saved value after restart,
then test logout, wrong password and local recovery. If camera tracking is
already enabled, confirm it stays responsive while logging in/saving. Provider
switches still require the model/AWS setup and physical verification described
in [installation](installation.md) and [Vision](vision.md); automated web tests
use no camera, display, actual credentials or AWS calls.


## Login request rejected

A form/session verification error occurs before the password is checked. Reload
`http://<PI-LAN-IP>:8080/login` after restarting PHOS and allow cookies for that
address. Old tabs contain tokens invalidated by a restart. If it persists, check
the terminal for `Administration CSRF rejection`; the reason is logged without
passwords or token values. Browser favicon/missing-page requests do not clear
the login session. Update the Pi's source if using the initial implementation.


## Save vs Reload vs Restart PHOS

Lifecycle actions are on **System actions**, separate from editable domain forms.
System / Status remains read-only and links to those actions. Every operation
requires administrator authentication after mandatory bootstrap rotation;
state changes also require CSRF protection.

| Operation | Effect |
| --- | --- |
| Save on a domain page | Validates and atomically persists the full canonical JSON. Does not change active settings. |
| Reload configuration | Reads that same file, validates every setting and active path with startup's model, then applies logging level, iris theme and all `vision.camera_preview` settings through shared runtime services. Shows applied fields and remaining restart-required fields. |
| Restart PHOS | Requires the managed service and explicit confirmation. Validates the saved file, requests graceful application shutdown, then systemd starts PHOS again from disk. |

If any setting/path is invalid, Reload applies **nothing**, including logging
level. Restart is also rejected before shutdown when the saved file is invalid.
No-op reloads report no changes. SDK logging stays at WARNING or above even when
PHOS logging is switched to DEBUG. No credentials, tokens or request payloads
are exposed by this feature.

The **Display & Appearance** page also offers the canonical `display.iris_color`
choice: cyan, blue, green, turquoise, amber, violet or white. It configures the
base iris theme; semantic accent tints still come from BehaviorEngine-produced
FaceState. Save it with the other Display & Appearance fields, then use Reload
configuration. The renderer receives the validated appearance through the
runtime's display-loop update boundary; the iris color blends smoothly into the
next frames. PHOS, Vision, camera, BehaviorEngine and providers keep running.
Expression semantics do not enter the renderer directly.

The **Vision** page also manages the optional camera preview on the physical
PHOS display. It is off by default; choose a corner, scale and maximum preview
FPS, then select whether to show the current face box and expression diagnostics.
Save and use Reload configuration to apply these fields immediately. The preview
uses the existing camera owner and latest in-memory frame, stays on the local
display, and is neither recorded nor exposed over this administration interface.

Iris color and camera preview settings are reloadable. Display geometry, cadence,
fullscreen and behavioral timing still require restart. Other implemented settings requiring restart are
web enabled/host/port; camera resolution/tracking/detection; expression enabled/provider, preprocessing,
smoothing and AWS policy; log destination and expression diagnostics. Switching
local/AWS is never done live. Password changes use their separate immediate
session-revoking mechanism, independent of Save/Reload.

The page shows configuration path, last successful startup/reload UTC time,
whether saved and active settings differ, reloadable differences and fields
requiring restart. Active settings are tracked by the parent application service,
not inferred from the saved file. The timestamp does not mean restart-only
settings were applied: those remain listed as pending. Runtime health and AWS
credential availability are not monitored.

To reload, open System actions and click **Reload configuration**. To restart,
click **Review and confirm restart**, read the interruption notice, check the
confirmation checkbox and press **Restart PHOS**. GET/page navigation never
restarts anything. A confirmation can be used only once. The acknowledgement is:
**Restart requested. PHOS will reload the configuration on startup.**

Expect temporary web loss and log in again after a few seconds. A slow connection
may lose the acknowledgement as shutdown begins; check the service locally before
retrying. The saved network settings determine the new URL. If web administration
was disabled, use the Pi terminal to enable it again. Unsaved form edits are lost.

Follow [managed startup](installation.md#managed-startup-and-browser-restart) to
install the user service. Manual terminal launches support Reload, but browser
Restart is unavailable; stop and rerun the normal startup command locally. Do
not run a manual copy beside the service (camera/port contention). No reboot,
arbitrary command execution, privileged shell or generic service-management API
is provided. **Reboot Raspberry Pi** is deferred beyond 1.0.0.

Configuration must remain valid until restart completes. Avoid concurrent local
file edits; a file changed or hardware removed after validation can still cause
startup to fail. Systemd bounds repeated startup failures; inspect its journal
and repair locally as described in installation. A lifecycle channel failure
reports unavailable rather than pretending that settings were applied.

Preview reload failures are shown as errors and logged in the parent. Earlier
successful appearance changes may already be active; inspect System actions
after correcting the camera/dependency problem. Invalid JSON/schema applies
nothing. An accepted preview configuration does not certify live image quality;
check the physical display and logs. The lifecycle channel waits up to five
seconds. If a native camera start takes longer, the action may still complete;
the response reports uncertainty and the channel stays unavailable until PHOS
restarts. Check locally rather than assuming the operation was cancelled.
