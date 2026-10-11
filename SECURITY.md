# Security Policy

## Threat Model

| # | Asset | Threat | Attack surface | Mitigation |
|---|-------|--------|----------------|------------|
| 1 | Admin API (`/api/leads`, `/api/mode`) | Unauthenticated lead theft / mode tampering | HTTP endpoints bound on `0.0.0.0` | `X-API-Key` required (constant-time compare); **fail closed** — 501 when `ADMIN_API_KEY` unset; rate limit 30 req/min/IP |
| 2 | WebSocket endpoints | Unauthenticated session hijacking of any `/ws` route | WS upgrade requests | `WebSocketAuthGuard` middleware rejects every upgrade without valid `?api_key=` (close 1008); fail closed (1011) when `ADMIN_API_KEY` unset. No `/ws` routes exist today — guard is defense-in-depth |
| 3 | Memory / availability | Body-size DoS via huge payloads | HTTP request bodies | 1 MB cap: `Content-Length` checked up front (413); chunked bodies truncated at cap |
| 4 | Lead database integrity | Injection of control chars / oversized strings into SQLite + downstream LLM context | `POST /api/leads` JSON | Pydantic validation: per-field length caps, control chars stripped, phone charset whitelist; generic 422 (no internal detail) |
| 5 | Clickjacking / MIME sniffing / referrer leakage | Browser-based attacks on any served page | HTTP responses | Security headers on every response: CSP `default-src 'none'; frame-ancestors 'none'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` |
| 6 | Internal error details | Stack traces leaking paths/versions | Unhandled exceptions | Global handler returns generic `{"error":"internal server error"}`; traceback only in server logs |
| 7 | API keys (Gemini, MiMo, admin) | Secret leakage via logs or repo | Logging, git history | Keys only via env vars (`.env` gitignored); no key material is ever logged; gitleaks in CI scans history |
| 8 | Outbound requests (SSRF) | Attacker redirects server to internal metadata/loopback services | Gemini Live + MiMo TTS HTTP calls | **No user-configurable URLs**: all outbound targets are compile-time constants (`GEMINI` via google-genai SDK, `MIMO_BASE_URL` in `config.py`) or operator-set env vars — request data never influences a URL, so no resolver guard is needed. If a future feature accepts user-supplied URLs, apply an `ipaddress`+`getaddrinfo` guard blocking private/loopback/link-local/metadata ranges, http/https only, no redirects |
| 9 | Caller PII (phone numbers, transcripts) | Exposure beyond the operator's machine | SQLite storage | Data stays local (`storage/*.db`, gitignored); nothing is synced; PII local policy in README |
| 10 | Supply chain | Vulnerable or malicious dependencies | `requirements.txt` | Exact version pins; `pip-audit` against OSV + bandit static analysis + gitleaks in CI; all actions pinned to full commit SHAs |

## Route inventory (app.py)

| Route | Method | Auth | Notes |
|-------|--------|------|-------|
| `/` | GET | open | Liveness only (status/mode/bluetooth/adb booleans) |
| `/api/leads` | GET | admin | rate-limited |
| `/api/leads` | POST | admin | lead capture; validated payload; auth checked before body parse |
| `/api/mode` | POST | admin | mode whitelist `sales`/`interview` |
| any `/ws*` | WS | `?api_key=` query | guard rejects unauthenticated upgrades (no routes registered today) |

WebSocket auth uses the `api_key` **query parameter** (documented choice): browser
WebSocket clients cannot set custom headers, and the alternative (first-message
auth) leaves a window where an unauthenticated peer can send bytes before
rejection. Query-param auth closes the connection before any handler runs.
Keep admin keys out of URLs in shared/proxied environments (strip query strings
from proxy access logs if applicable).

## Reporting a vulnerability

Open a private security advisory on the GitHub repository. Do not file public
issues for vulnerabilities.
