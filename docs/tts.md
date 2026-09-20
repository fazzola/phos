# Text-to-Speech

## Decision

The robot uses a provider-independent `TTSProvider` interface.

The application must not depend directly on Piper, an OpenAI TTS SDK, Home Assistant TTS or another vendor implementation outside the corresponding provider adapter.

## Initial provider: Piper

Piper is the preferred first local TTS engine because the project targets a Raspberry Pi 3 and should retain useful offline speech capability.

Start with a lightweight Italian Piper voice/model and evaluate latency on the actual Pi before selecting a larger model. Exact voice files are configuration and hardware-validation choices, not architectural assumptions.

## Architecture

```text
Robot / behavior
      |
      v
 TTSProvider
      |
      +--> PiperTTSProvider      local/offline
      +--> future cloud provider
      +--> future HA provider
```

## Contract

`TTSProvider.synthesize()` receives a neutral `TTSRequest` and returns a neutral `TTSResult`.

Provider-specific SDK objects must never escape the adapter.

## Responsibilities

### TTSProvider
- define the stable synthesis contract
- carry text, language and optional voice
- return the generated audio path and neutral metadata

### PiperTTSProvider
- translate the neutral request into a Piper invocation
- write audio to the requested output path
- convert Piper failures into explicit application errors

### Audio playback
Playback is a separate responsibility. `TTSProvider` generates audio; it does not own speaker selection, volume, ALSA configuration or playback lifecycle.

## Raspberry Pi 3 constraints

- Prefer local TTS for low-latency/offline system phrases when practical.
- Benchmark voice/model quality versus synthesis latency on the Pi 3.
- Do not assume every Piper model performs acceptably on the Pi 3.
- Keep model path and executable path configurable.
- Do not bundle large voice models in the source repository.

## Future providers

A new provider must implement `TTSProvider` without changing callers.
Examples may include cloud TTS, Home Assistant TTS or a LAN-hosted synthesis service.
