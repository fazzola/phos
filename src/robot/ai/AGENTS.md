# PHOS AI Instructions

Applies to the AI subsystem.

- Preserve the provider-neutral `LLMProvider` boundary and neutral message/tool/response structures already present in the repository.
- Vendor SDK imports belong only in provider adapters.
- Model IDs and vendor-specific configuration must not leak into business logic.
- Cloud API, LAN-hosted models and future local fallback must remain interchangeable at the core boundary.
- Home Assistant actions, when added, are tools/integrations exposed through controlled interfaces; the LLM must not access Home Assistant directly.
- Sensitive home actions require explicit allowlisting/policy and must not become automatically available to the model.
- Do not implement AI work while the current milestone is visual-only unless explicitly requested.
