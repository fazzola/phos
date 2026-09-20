# PHOS Voice Instructions

Applies to voice/audio work.

- Preserve `TTSProvider` as the synthesis abstraction.
- Keep Piper-specific details inside its provider adapter.
- TTS generates audio; speaker/device selection, volume, ALSA and playback lifecycle are a separate subsystem.
- Prefer lightweight local components suitable for Raspberry Pi 3 unless an approved architecture decision says otherwise.
- Keep future cloud/Home Assistant TTS providers possible without changing core behavior logic.
- Voice must integrate through the robot runtime/state model rather than controlling UI or Vision directly.
