# PHOS installation on Raspberry Pi

This guide installs the dependencies required to run PHOS from
`/home/pi/phos` on a Raspberry Pi 3 with the HDMI display. The project source
sync script copies only `src/`, so install these system dependencies separately
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

It synchronizes local `src/` to `/home/pi/phos/src/` on `pi@192.168.1.128`.
For a first copy, create the destination directory on the Pi if necessary:

```bash
mkdir -p /home/pi/phos/src
```

## 5. Start PHOS

Run these commands from a graphical Raspberry Pi OS desktop session:

```bash
cd /home/pi/phos
python3 src/robot/main.py
```

Start the face-tracking milestone with:

```bash
cd /home/pi/phos
python3 src/robot/main.py --face-tracking
```

The default command requires no camera and displays idle animated eyes. The
face-tracking command starts Picamera2 and OpenCV, detects the largest visible
face at the configured detection rate, and smoothly moves pupils toward it.
Press `Ctrl+C` to stop PHOS cleanly; press `Escape` to leave fullscreen mode.

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
