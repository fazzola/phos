# PHOS installation on Raspberry Pi

## PHOS 1.0.0 reproducible installation

Use Raspberry Pi OS **with a graphical desktop**, Python 3.11+ and an 800×600
HDMI display on the Pi 3. Tk needs an active X display (XWayland on a Wayland
desktop). Raspberry Pi OS Lite alone is insufficient. The recommended production
launch is the user systemd service below; terminal launch is for diagnostics.
These instructions use the desktop user's `~/phos` (`/home/pi/phos` for user `pi`).

This is a reproducible source/dependency procedure, not a frozen OS image. Record
`cat /etc/os-release`, `uname -m`, `python3 --version` and apt package versions
with the release acceptance results. Actual fresh-Pi acceptance is still pending;
see [release checklist](release-1.0.0.md#release-checklist).

### 1. Install system dependencies and source

On the Pi, as the desktop user:

```bash
sudo apt update
sudo apt install -y git wget ca-certificates python3-venv python3-tk python3-picamera2 python3-opencv opencv-data rpicam-apps
cd ~
git clone https://github.com/fazzola/phos.git phos
cd ~/phos
git rev-parse HEAD
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-web.txt
.venv/bin/python -m pip check
.venv/bin/python -c "import tkinter, cv2, flask, flask_wtf, waitress; from picamera2 import Picamera2; print('Runtime imports OK; OpenCV', cv2.__version__)"
```

Use the audited commit when it becomes available; no `v1.0.0` tag is assumed to
exist yet. The source checkout already contains `config/phos.json`; do not create
an incomplete JSON file. No package installation is needed to run the source
entry point. The web dependency snapshot is pinned; camera/OpenCV/Tk come from
apt and are exposed to the venv by `--system-site-packages`. Do not pip-install
the `vision` extra on the Pi. OpenCV DNN loads ONNX directly: **onnxruntime,
TensorFlow and PyTorch are not required**.

Alternative source transfer: review the destination in `run_pi.sh` and run it
from your development checkout. It seeds a missing configuration and preserves
existing Pi settings/models/administrator data; it neither installs dependencies
nor restarts PHOS. Upgrades must merge new required fields from the complete
canonical schema. The script has a site-specific destination, not auto-discovery.

### 2. Check the camera and display

Before starting PHOS, run this from the Pi desktop with the camera connected:

```bash
rpicam-hello --timeout 5000
.venv/bin/python src/robot/ui/demo.py
```

Close the camera test before PHOS acquires it. In the eye demo use `1`–`5` for
expressions, arrows for gaze and `q` to exit. Resolve camera connection/desktop
permission problems before proceeding. Camera packages and setup follow
[Raspberry Pi's supported camera documentation](https://www.raspberrypi.com/documentation/computers/camera_software.html).

### 3. Configure PHOS and Web Admin

Edit `~/phos/config/phos.json`. Release defaults start only eyes: tracking,
expressions, camera preview and Web Admin are disabled. Keep this complete file;
all six sections (`web`, `display`, `behavior`, `vision`, `expression`, `logging`)
are required, including inactive provider fields and `vision.camera_preview`.
Paths inside JSON resolve relative to its directory.

For trusted-LAN administration set `web.enabled` to `true` and `web.host` to the
Pi's LAN address or `0.0.0.0`; default port is 8080. No AWS/password secrets belong
in JSON. Validate before any camera/display startup:

```bash
cd ~/phos
PYTHONPATH=src .venv/bin/python -c "from pathlib import Path; from robot.config import RuntimeConfig; RuntimeConfig.from_file(Path('config/phos.json')); print('Configuration valid')"
```

Enable gaze with `vision.face_tracking_enabled: true`. Enable the local display
picture-in-picture with `vision.camera_preview.enabled: true` (it is **not a web
video stream**). Keep expressions off until choosing one provider below.

### 4. Select optional expression processing

Skip this step for eyes, tracking or camera preview alone. For AWS follow
[optional AWS mode](#optional-aws-expression-mode). For local mode, install the
configured MobileFaceNet candidate:

```bash
cd ~/phos
mkdir -p models/expression
wget -O models/expression/facial_expression_recognition_mobilefacenet_2022july.onnx \
  https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/facial_expression_recognition/facial_expression_recognition_mobilefacenet_2022july.onnx
echo '4f61307602fc089ce20488a31d4e4614e3c9753a7d6c41578c854858b183e1a9  models/expression/facial_expression_recognition_mobilefacenet_2022july.onnx' | sha256sum -c -
wget -O models/expression/opencv-zoo-LICENSE \
  https://raw.githubusercontent.com/opencv/opencv_zoo/main/LICENSE
```

Stop if the checksum differs. Set `expression.enabled: true` and
`expression.provider: "local"`; retain the supplied model path, labels and
preprocessing. No AWS dependency is needed. The candidate's recognition quality
is not established; read [model evaluation](vision-model-evaluation.md).
Keep neutral reactions disabled until calibrated. Revalidate the JSON.

### 5. Start PHOS

For a first foreground check from the desktop:

```bash
cd ~/phos
.venv/bin/python src/robot/main.py --config config/phos.json
```

Check the startup version is **1.0.0** and the logged configuration path is the
file you edited. Escape leaves fullscreen; Ctrl+C stops PHOS. Stop this process
before installing/starting the production service below.

When web is enabled, open `http://<PI-LAN-IP>:8080/`, enter `phos`, set a different
12–256 character password, then log in again. There is no username. Password
changes revoke all sessions. Use the [administration manual](web-administration.md)
for domain editing, validation, recovery and trusted-LAN HTTP limitations.

## Managed startup and browser restart

The **recommended production launch** is `deploy/phos.service`, a user systemd
service running with the desktop user's camera/display/file permissions. No root
service, sudo endpoint or adapter-owned shell command is involved. From a terminal
**in that user's Pi graphical desktop**, after stopping any foreground PHOS:

```bash
cd ~/phos
mkdir -p ~/.config/systemd/user
cp deploy/phos.service ~/.config/systemd/user/phos.service
systemctl --user import-environment DISPLAY
if [ -n "${XAUTHORITY:-}" ]; then
  systemctl --user import-environment XAUTHORITY
fi
systemctl --user daemon-reload
systemctl --user enable --now phos.service
systemctl --user status phos.service
journalctl --user -u phos.service -n 100 --no-pager
```

The unit uses `%h/phos`, `.venv/bin/python` and `%h/phos/config/phos.json`. Adjust
WorkingDirectory/ExecStart locally if installing elsewhere. Tk must have a usable
DISPLAY and authorization; do not enable lingering/headless boot for this app.
Login startup depends on the desktop activating `graphical-session.target` and
importing its display environment. Check `systemctl --user is-active
graphical-session.target`. If the desktop does not manage that target/environment,
run the import commands and `systemctl --user start phos.service` at each desktop
login. Automatic login startup on that desktop remains an acceptance prerequisite.

Operations:

```bash
systemctl --user restart phos.service
systemctl --user stop phos.service
systemctl --user start phos.service
journalctl --user -u phos.service -n 100 --no-pager
```

In Web Admin, **System actions → Reload configuration** applies logging level,
iris theme and every camera-preview setting. Other changed fields remain listed
as restart-required. **Restart PHOS** requires confirmation, shuts down the runtime
and worker, exits with code 75 and lets systemd start the same entry point after
three seconds. Reconnect at the saved host/port and log in again. Disabling web
intentionally removes browser access. Manual launches cannot offer browser restart.
This never reboots the Pi.

Unexpected runtime or web-worker failure exits nonzero for systemd recovery.
The unit limits starts to three per 60 seconds and kills the entire service
control group on stop (20-second shutdown deadline). An explicit `systemctl stop`
does not restart it. Fix configuration/dependency/display errors before recovery:

```bash
systemctl --user reset-failed phos.service
systemctl --user start phos.service
```

The service marker `PHOS_SERVICE_MANAGED=1` plus systemd's `INVOCATION_ID` enables
browser restart; neither is a normal runtime setting. Do not set the marker in
manual launches. See [systemd service semantics](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml).

## Optional AWS expression mode

Camera/OpenCV remain required. Install the SDK into the Pi system environment
which the venv can access:

```bash
sudo apt install -y python3-boto3
cd ~/phos
.venv/bin/python -c "import boto3; print('AWS SDK import OK')"
```

Configure credentials **outside the repository** using the
[standard Boto3 credential chain](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html),
preferably the service user's `~/.aws/credentials` and `~/.aws/config` or a role.
Protect credential files with owner-only permissions. The default shared profile
needs no shell environment import. The AWS account must allow
`rekognition:DetectFaces` in the selected supported region; no S3 access is needed.

For a named profile already configured for this desktop user:

```bash
export AWS_PROFILE=phos
systemctl --user import-environment AWS_PROFILE
systemctl --user restart phos.service
```

For externally supplied environment credentials, import only the existing names
needed by your session before service start/restart:

```bash
systemctl --user import-environment AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
# Only when using temporary credentials:
systemctl --user import-environment AWS_SESSION_TOKEN
```

Do not put secret values in JSON, unit files, shell history or issue logs. The
service does not automatically inherit interactive shell variables. Region
precedence is `expression.aws.region`, `AWS_REGION`, then SDK settings
(`AWS_DEFAULT_REGION` or profile). PHOS does not load a `.env` file.

Set `expression.enabled: true`, `expression.provider: "aws"` and the non-secret
`expression.aws` policy. No ONNX model is required. Restart PHOS. **Selected facial
crops leave the Pi and are sent to AWS**. Import checks and automated tests make
no AWS calls. Perform live AWS acceptance only with an authorized account.

Requests are single-flight, cached, rate-limited and backed off on error; they do
not silently switch providers. Diagnostics show sanitized latency/request counts.
Switching provider or disabling expressions requires restart. See
[Vision policy](vision.md#cloud-request-and-evidence-policy).

## Troubleshooting

- Missing `cv2`/`picamera2`: use the apt packages and the venv created with
  `--system-site-packages`; verify imports with `.venv/bin/python`.
- Missing image: confirm `vision.camera_preview.enabled`, the startup config
  path, and updated Python source; reload/restart. Check `phos.log` or journal for
  `Camera preview reload failed` or `Could not render camera preview`.
- Tk startup failure: launch/import DISPLAY and XAUTHORITY from the actual desktop
  session; SSH alone does not supply display authorization.
- No faces: check lighting/framing and `rpicam-hello` with PHOS stopped. Use
  `logging.expression_diagnostics` temporarily; restart to apply it.
- Config save/reload rejection: correct the complete schema and active model/log
  paths. Save alone never changes the running configuration.
- No browser after restart: use the newly saved address/port, check the journal
  and service start limit. Restart invalidates sessions.

Deprecated per-setting CLI overrides are still functional for compatibility;
production uses only `--config`. Supported eye and Vision diagnostic commands
remain available; no obsolete provider-specific JSON files are required.
