# Architecture Decisions

## ADR-001 — Python as primary language

**Status:** Accepted

Python is the primary application language.

**Why**
- Strong Raspberry Pi ecosystem
- Excellent AI/audio/computer-vision ecosystem
- Fast iteration
- Good maintainability for a personal robotics project

C/C++ may be introduced for a hardware driver, microcontroller firmware or a performance-critical component when justified.

## ADR-002 — Hardware abstraction

**Status:** Accepted

Hardware access is isolated behind explicit interfaces/adapters, with physical-device implementation under `src/robot/hardware/` where applicable.

**Why**
- Testing without physical hardware
- Easier hardware replacement
- Cleaner AI/core layers

## ADR-003 — Raspberry Pi 3 is the baseline

**Status:** Accepted

Solutions should remain practical on Raspberry Pi 3 unless a later hardware upgrade is explicitly documented.

Expensive AI inference may use a remote machine/API or an optimized local model.

## ADR-004 — Provider-independent LLM interface

**Status:** Accepted

All language-model access uses `LLMProvider`.

**Why**
- Switch between OpenAI, Anthropic and local/self-hosted models without rewriting robot behavior.
- Prevent vendor SDK types from leaking through the architecture.
- Make AI behavior unit-testable using fake providers.
- Allow future routing between fast, powerful and offline models.

## ADR-005 — Primary LLM is not assumed to run on Raspberry Pi 3

**Status:** Accepted

The Pi 3 runs robot orchestration, UI, hardware and integration logic. The primary LLM may run through a cloud API or on a LAN server. Small local models may be explored as offline fallbacks.

## ADR-006 — Provider-neutral TTS and separate playback

**Status:** Accepted

Speech synthesis uses `TTSProvider`. Audio playback/device management is a distinct responsibility. Piper is the preferred first local TTS implementation to benchmark on Raspberry Pi 3.

## ADR-007 — Lightweight Raspberry Pi Vision

**Status:** Accepted

Use Picamera2 for Raspberry Pi Camera capture, lightweight OpenCV face detection, and a configurable lightweight ONNX expression classifier through OpenCV DNN. Expression classification is an uncertain visual observation, not mind/emotion inference. Identity recognition and image persistence are out of scope by default.

## ADR-008 — Behavior mediates Vision and UI

**Status:** Accepted

Vision does not drive the renderer directly. Stable observations plus `RobotState` feed `BehaviorEngine`, which produces UI-neutral `FaceState`. `EyeRenderer` consumes `FaceState`. PHOS does not mechanically mirror negative human facial-expression observations.

## ADR-009 — Architecture-first multi-agent workflow

**Status:** Accepted

Architecture/docs own WHAT and WHY. Coding agents such as Codex own HOW and CODE. Git/repository files are the source of truth.

Coding agents may propose architectural changes but must not silently implement changes that conflict with accepted decisions. If implementation reveals a conflict, report it and document an approved resolution before redesigning the system.

## ADR-010 — Project identity: PHOS

**Status:** Accepted

The project name is **PHOS**. Documentation, agent instructions and user-facing project references use PHOS.

The existing Python package namespace `robot` remains unchanged. Renaming the package is a separate implementation migration requiring explicit approval.

## ADR-011 — Hierarchical AGENTS.md owns PHOS-specific agent guidance

**Status:** Accepted

Durable PHOS-specific instructions live in the root `AGENTS.md`, nested subsystem `AGENTS.md` files and `docs/`. More specific instructions apply to the directory they govern.

Avoid duplicating detailed architecture across root instructions, nested instructions and skills.

## ADR-012 — Runnable vertical milestones

**Status:** Accepted

Complete and verify one runnable capability before deliberately introducing or expanding the next major subsystem. Preferred progression is eyes -> face tracking -> expression reactions -> voice -> integrations.

Code that already exists ahead of the currently verified milestone is preserved, but it should not drive automatic scope expansion.

## ADR-013 — General coding skill and PHOS guidance are separate

**Status:** Accepted

The reusable coding-agent skill is project-neutral and contains only implementation workflow. PHOS-specific facts, hardware constraints, architecture, milestone order and subsystem rules live in this repository through hierarchical `AGENTS.md` files and `docs/`.

The project does not require a PHOS-specific skill.

## ADR-014 — Optional cloud facial-expression adapter

**Status:** Accepted (explicitly requested extension of ADR-007).

Keep local ONNX as default and add selectable AWS Rekognition behind the existing
ExpressionProvider. Capture, tracking, selection and cropping stay local; only
selected stable crops leave the Pi when AWS is explicitly selected. Cloud work
is single-flight, asynchronous, rate-limited and cached with expiry/backoff;
there is no implicit fallback. Cached reads are not independent temporal evidence.
The existing semantic/behavior/UI boundaries remain unchanged. This extends
ADR-007's local baseline without replacing it. See Vision for policy and privacy.

Normal settings belong to RuntimeConfig and must be reusable by a future web
configuration layer. Secrets stay outside application settings in standard AWS
credential resolution. No web interface is part of this change.

## ADR-015 — One canonical runtime configuration

**Status:** Accepted (explicit user-requested configuration centralization).

Use `config/phos.json` for all current non-secret application settings. Required
sections map to the existing typed RuntimeConfig surface in `robot.config`;
CloudExpressionConfig remains a typed provider subset. Validate types, ranges,
relationships and active paths before building subsystems. CLI defaults and
provider-specific JSON files are replaced by this file. Existing setting flags
remain deprecated explicit overrides for a separately announced migration.

The committed file safely starts only eyes; camera/expression processing is
opt-in. Keep geometric/semantic safeguards and renderer implementation constants
in their subsystems. New normal runtime settings extend the central schema/file.
Reusable loading, validation, serialization and atomic persistence are independent
of CLI and available for the future web milestone. Secrets remain external;
no web UI or live reload is part of this change.

## ADR-016 — Optional local web administration

**Status:** Accepted (explicit user-requested web administration milestone).

Add a lightweight Flask/Waitress administration adapter in a separate process
owned by application startup. Reuse RuntimeConfig schema, validation and atomic
persistence; expose saved settings separately from the startup snapshot. No hot
reload. Canonical web settings opt into LAN binding; default disabled/loopback
preserves the existing runtime. The optional web dependencies stay outside Core,
Vision and rendering.

Use one administrator, an external owner-only salted password-hash file, mandatory
bootstrap password change, expiring signed sessions with server-side revocation,
CSRF protection and bounded password attempts. AWS secrets remain external. HTTP
is trusted-LAN-only; Internet/TLS/proxy deployment is outside this milestone.
Details and local recovery belong in the [web manual](web-administration.md).

## ADR-017 — PHOS 1.0.0 scope and shared control services

**Status:** Accepted (explicit release-finalization request).

Freeze 1.0.0 at the existing runtime, eyes, tracking, local/AWS expression and
canonical configuration/web administration scope. Hardware availability does
not bring sensors, LEDs, conversation, remote API or MCP into this release.
Keep one authoritative version in `robot.__version__`, consumed by packaging
and runtime/status reporting. Separate automated release checks from physical
acceptance and expression accuracy.

Future Web/API/MCP/Voice control surfaces must reuse application services and
must not access hardware or subsystem internals. Shared validation, authorization
and behavior semantics belong in those services, not in duplicated adapters.
See the release record and roadmap for scope and deferred capabilities.
