# Local REST API

The PHOS local REST contract is [OpenAPI 3.1](api/openapi.yaml). It is a
versioned public contract for `/api/v1`; all control remains semantic and flows
through `PhosApplicationService`, never directly to hardware.

`GET /api/v1/capabilities` is operation-oriented. Its `commands` mapping
identifies each writable semantic operation with its endpoint, HTTP method,
request field, and allowed values. Its `observable_states` mapping lists
runtime-readable vocabulary, including values such as `error` that clients must
not submit. Both projections are derived from PHOS domain validation rules.

Validate the checked-in contract with:

```sh
PYTHONPATH=src python -m robot.web.openapi
```

The normal local server is deliberately conservative: use the canonical `web`
bind address and port, retain its administrator authentication, and put TLS plus
additional authentication at a trusted reverse proxy for any non-local access.
The OpenAPI server URL is deliberately relative (`/`), so Swagger UI always
targets the host and port that served `/docs`; it never assumes port 8080.
REST endpoints use the existing `phos_admin` HttpOnly, SameSite session cookie;
there is no API token or second account store. Unauthenticated `/api/...`
requests receive JSON `401 unauthorized`, while an authenticated session that
must complete its bootstrap password change receives JSON `403 forbidden`.
Log in at `/login` first, then open `/docs`: Swagger UI is same-origin and
automatically reuses the browser session cookie.
After administrator login, local interactive documentation is available at
`/docs` and the raw contract at `/openapi.json`. Swagger UI JavaScript and CSS
are served from PHOS package assets, so these pages and the contract work
offline; ReDoc is intentionally not exposed because no local ReDoc bundle is
currently shipped.
The events endpoint is Server-Sent Events under the current WSGI deployment;
the contract documents that transport explicitly.
