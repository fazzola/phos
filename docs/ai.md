# AI and LLM Strategy

## Goal

The robot must not depend on a single AI vendor or model.

## Contract

Application code talks to `LLMProvider`:

- input: neutral `LLMMessage` objects
- optional input: neutral `LLMTool` definitions
- output: neutral `LLMResponse`
- tool requests: neutral `LLMToolCall` objects

## Provider adapters

Initial adapter locations:

- `ai/providers/openai_provider.py`
- `ai/providers/anthropic_provider.py`
- `ai/providers/local_provider.py`

Only these adapters may import vendor SDKs.

## Runtime model strategy

### Normal mode
Use a fast, relatively inexpensive remote model for ordinary dialogue and tool selection.

### Complex mode (future)
A routing policy may escalate selected tasks to a stronger model. Routing must target capabilities/configured providers, not hard-code application behavior around a brand.

### Offline mode (future)
A small model may handle limited offline tasks. Raspberry Pi 3 performance constraints mean a LAN-hosted model is also considered a local/offline-capable backend when the local network is available.

## Speech

Initially keep these stages independent:

```text
microphone -> STT -> RobotAgent/LLMProvider -> TTS -> speaker
```

This is easier to debug and permits changing each component independently. Realtime end-to-end voice can be evaluated later.

## Home Assistant tools

Home Assistant actions are exposed as robot tools rather than direct model API access. Maintain an allow-list for permitted actions. High-impact actions such as locks, alarms or garage access must not become available merely because a provider supports tool calling.
