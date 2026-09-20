# PHOS installation on Raspberry Pi

This guide installs the dependencies required to run PHOS from
`/home/pi/phos` on a Raspberry Pi 3 with the HDMI display. The project source
sync script copies `src/` and seeds `config/phos.json` once, so install dependencies separately
on the Pi.

## 1. Prepare Raspberry Pi OS

Use a current Raspberry Pi OS image with a graphical desktop session. PHOS
uses Tkinter for its fullscreen display, and face tracking uses the modern
`rpicam`/Picamera2 camera stack.

Update package indexes and install the default display runtime dependency:

```bash
sudo apt update
sudo apt install -y python3-tk
```

## 2. Install face-tracking dependencies

With a Raspberry Pi Camera connected, install the Raspberry Pi OS packages:

```bash
sudo apt install -y python3-picamera2 python3-opencv opencv-data
```

Use these packages with the system `python3`. They provide `picamera2`,
`cv2`, and the OpenCV Haar Cascade data used by PHOS. Do not install
Picamera2 with `pip` into the same system environment: Picamera2 depends on
the Raspberry Pi camera stack and Raspberry Pi recommends installing it with
`apt`.

`opencv-python-headless` and `picamera2` are also listed as the project's
optional `vision` dependencies in `pyproject.toml`, but that pip extra is not
the recommended setup for the Pi's system Python/camera stack.
`requirements.txt` contains the same Python dependencies for non-Pi
development environments.

## 3. Verify the camera and Python modules

First verify that Raspberry Pi OS can access the connected camera:

```bash
rpicam-hello
```

Then verify that the same interpreter PHOS uses can import both libraries:

```bash
python3 -c "import cv2; from picamera2 import Picamera2; print('cv2', cv2.__version__, 'Picamera2 available')"
```

If either command fails, resolve the camera connection or the package
installation before starting PHOS. The exact camera model and physical
availability are recorded in `docs/hardware.md`.

## 4. Copy PHOS to the Pi

From the development machine, run the repository script:

```bash
./run_pi.sh
```

It synchronizes local `src/` to `/home/pi/phos/src/` on the host configured
in `run_pi.sh`, and copies `config/phos.json` only if the Pi has no such file.
Existing Pi settings are not overwritten.
For a first copy, create the destination directory on the Pi if necessary:

```bash
mkdir -p /home/pi/phos/src /home/pi/phos/config
```

## 5. Start PHOS

The selected replacement candidate is OpenCV Zoo MobileFaceNet (FP32 ONNX).
Pi CPU timings are recorded, but camera accuracy still requires validation in
[Vision model evaluation](vision-model-evaluation.md) before production promotion.
Download and verify the published model (no model conversion or new runtime needed):

```bash
cd ~/phos

mkdir -p models/expression

wget -O models/expression/facial_expression_recognition_mobilefacenet_2022july.onnx \
https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/facial_expression_recognition/facial_expression_recognition_mobilefacenet_2022july.onnx

echo '4f61307602fc089ce20488a31d4e4614e3c9753a7d6c41578c854858b183e1a9  models/expression/facial_expression_recognition_mobilefacenet_2022july.onnx' | sha256sum -c -

wget -O models/expression/opencv-zoo-LICENSE \
https://raw.githubusercontent.com/opencv/opencv_zoo/main/LICENSE
```

Run from a graphical Raspberry Pi OS desktop session:

```bash
cd /home/pi/phos
python3 src/robot/main.py --config config/phos.json
```

This same command is used for all modes. The committed configuration starts
only the animated eyes. Edit `config/phos.json` with your normal text editor:

- Set `vision.face_tracking_enabled` true for local gaze tracking only.
- Set `expression.enabled` true and keep `expression.provider` as `"local"`
  for MobileFaceNet expression observations. The model/preprocessing fields
  are already provided under `expression.local`; the downloaded file must exist.
- Set `logging.expression_diagnostics` true temporarily to inspect detections,
  inference and semantic decisions, then turn it off after verification.

Restart after changes. Model and log paths resolve relative to the JSON file,
not your terminal directory. The included model path starts with `../models/`.
Malformed configuration and missing active model files fail before camera or
fullscreen display startup. Ctrl+C stops PHOS; Escape leaves fullscreen.
Do not change the candidate's channel/preprocessing settings without checking
its model contract. FER+ rollback settings are in [Vision](vision.md).

`config/phos.json` is both the canonical example and the user-editable file;
there are no separate provider configuration files. You may copy the complete
file to another location and select it with `--config`; update relative paths
if moving it manually. See [all fields and validation rules](development.md#configuration).
The old individual settings flags are deprecated overrides only. For upgrades,
compare your Pi configuration with the canonical file and add any new required
fields; the source sync deliberately preserves your settings.

## Troubleshooting

### `ModuleNotFoundError: No module named 'cv2'`

Install OpenCV for the interpreter running PHOS:

```bash
sudo apt install -y python3-opencv opencv-data
python3 -c "import cv2; print(cv2.__version__)"
```

### `ModuleNotFoundError: No module named 'picamera2'`

Install Picamera2 from Raspberry Pi OS packages:

```bash
sudo apt install -y python3-picamera2
python3 -c "from picamera2 import Picamera2; print('Picamera2 available')"
```

### Camera opens but finds no faces

Confirm `rpicam-hello` works, ensure the face is well lit and visible, and
confirm the camera is oriented correctly. PHOS does not save camera frames or
face crops.

## Sources

Raspberry Pi documents Picamera2 as the supported Python API for the modern
camera stack and recommends installation through `apt`: [Camera software
documentation](https://www.raspberrypi.com/documentation/computers/camera_software.html).
Its camera documentation covers physical camera installation and setup:
[Raspberry Pi Camera documentation](https://www.raspberrypi.com/documentation/accessories/camera.html).

## Optional AWS expression mode

Keep the camera/OpenCV packages from step 2. Local ONNX mode needs no AWS
package, account, credentials or network connection. For AWS mode on system
Python, additionally install:

```bash
sudo apt install -y python3-boto3
```

Alternatively, in an existing virtual environment with access to the Pi system
camera packages and a full repository checkout, use `python3 -m pip install
'.[aws]'` (optional `boto3>=1.34` extra). Do not install this extra into the
managed system Python using pip. boto3 brings botocore; no new ML runtime is
needed. An AWS account, working network, a supported Rekognition region and
permission for `rekognition:DetectFaces` are required. No S3 access is needed.

Use the [standard SDK credential chain](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html):
external shared profiles/roles work without credential environment variables.
For environment credentials, replace placeholders in your external shell/session:

```bash
export AWS_ACCESS_KEY_ID='<access-key-id>'
export AWS_SECRET_ACCESS_KEY='<secret-access-key>'
export AWS_SESSION_TOKEN='<session-token-if-using-temporary-credentials>'
export AWS_DEFAULT_REGION='eu-west-1'
```

Omit `AWS_SESSION_TOKEN` for long-lived credentials; temporary credentials require
it. `AWS_REGION` is also supported. Region precedence is PHOS configuration/CLI,
then `AWS_REGION`, then the SDK (`AWS_DEFAULT_REGION` or profile). Credentials
are never read manually or stored in PHOS JSON. Do not put secrets in committed
files or issue/debug logs. PHOS does not use or create a `.env` file.

In `config/phos.json`, change `expression.enabled` to true and
`expression.provider` to `"aws"`. Retain the complete `expression.aws` block and
edit its request limits/region if needed. Then run:

```bash
python3 src/robot/main.py --config config/phos.json
```

**AWS mode sends selected cropped facial images to AWS.** No local ONNX file
is required for this mode. Camera capture, selection and cropping remain local.
The request/cache/backoff policy is documented in [Vision](vision.md#cloud-request-and-evidence-policy).
To stop cloud processing, stop PHOS and set `expression.provider` to `"local"`
with a valid local model, or set `expression.enabled` false; restart with the
same command. To keep gaze without expression analysis, enable
`vision.face_tracking_enabled`.

For verification, enable `logging.expression_diagnostics` in JSON. Check
`PHOS configuration loaded` and `Expression provider: aws`, then hold a well-lit
face in view. Logs show attempts/cache/skips/latency; tracking should continue
smoothly during requests. Leave/re-enter to verify stale results are discarded.
Distinct samples are needed for temporal confirmation; short-term reactions
are deliberately limited by the conservative cloud policy. Turn diagnostics
off after testing. If AWS fails, UNKNOWN and bounded retries preserve local
tracking/eyes without silently selecting another provider. Check boto3, region,
external credentials, IAM permission and network. Automated tests do not verify
recognition quality or cloud service availability on physical hardware.

## Optional web administration

Follow the [web administration user manual](web-administration.md) to install
the web extra, add/enable the canonical `web` section and access the editor.
It documents LAN URLs, first login with `phos`, mandatory password change, local
recovery and HTTP security limits. Configuration edits use the existing model
and require restart; AWS credentials remain external. Existing deployments must
add the required `web` section from the canonical file when upgrading.
