---
hide:
  - navigation
  - toc
classes:
  - phos-home
---

# Web Admin

<div class="phos-page-intro" markdown>

<span class="phos-kicker">CONFIGURE WITH BOUNDARIES</span>

Web Admin is PHOS’s optional, single-administrator configuration editor for a
trusted LAN. It does not access the camera, hardware drivers or renderer
directly: it uses the same canonical `config/phos.json` model, validation and
atomic persistence as startup.

</div>

## First access and safety

When enabled, browse to the configured Pi address. The bootstrap password is
`phos`, must be changed on first login, and there is no username. Password
hashes live outside runtime JSON; sessions expire and all forms use CSRF
protection. This is HTTP for a trusted LAN—not a public Internet service.

## Configuration domains

The current editor exposes General, Network, Display & Appearance, Vision,
Expression Recognition, Sensors, Logging, Web Administration / Security and
read-only System / Status. Sensor and appearance areas include the implemented
environmental behavior, IMU, LED ring and visual-source controls where those
options are enabled in the canonical configuration.

Status reports saved-versus-active configuration, version, active expression
selection and reload/restart-required differences; it does not claim live
hardware health or probe AWS credentials.

## Save, reload, restart

<div class="phos-callout" markdown>

**Save** validates and atomically persists the complete JSON file; it does not
change the running process. **Reload configuration** can apply logging level,
iris appearance, LED-ring visual settings and camera-preview settings. Other
valid changes remain explicitly restart-required. **Restart PHOS** is available
only through the managed user systemd service, with confirmation; it never
reboots the Pi.

</div>

Use the [canonical Web Admin manual](web-administration.md) for the full domain
map, recovery steps and security limits.
