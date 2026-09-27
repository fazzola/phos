# Local REST API

The PHOS local REST contract is [OpenAPI 3.1](api/openapi.yaml). It is a
versioned public contract for `/api/v1`; all control remains semantic and flows
through `PhosApplicationService`, never directly to hardware.

Validate the checked-in contract with:

```sh
PYTHONPATH=src python -m robot.web.openapi
```

The normal local server is deliberately conservative: use the canonical `web`
bind address and port, retain its administrator authentication, and put TLS plus
additional authentication at a trusted reverse proxy for any non-local access.
The events endpoint is Server-Sent Events under the current WSGI deployment;
the contract documents that transport explicitly.
