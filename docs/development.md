# Development Guide

## Local development

The application should support a development mode that does not require Raspberry Pi hardware.

Use interfaces and fakes/mocks for hardware.

## Configuration

Keep environment-specific values out of source code.

Prefer a configuration file plus environment variables for secrets.

Never commit API keys, passwords or tokens.

## Dependencies

Before adding a dependency, consider:
1. Is the standard library sufficient?
2. Is the dependency maintained?
3. Does it work on Raspberry Pi 3?
4. Does it materially simplify the implementation?

## Testing

Test:
- state transitions
- event handling
- AI tool contracts
- hardware adapters through fakes
- error handling

Do not make ordinary unit tests depend on physical GPIO/audio/display hardware.
