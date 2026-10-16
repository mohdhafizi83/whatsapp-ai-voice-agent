# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.0] - 2026-10-16

### Added
- Docker deployment for the admin API + web UI (`Dockerfile`, `docker-compose.yml`
  with healthcheck, `.dockerignore`). The Bluetooth HFP call engine cannot run in
  a container — the image ships with `VOICE_AGENT_DISABLE_ENGINE=1` and serves the
  API/UI only.
- Admin web panel at `/admin` — status, mode switch, captured leads. Fully
  self-hosted assets (Inter font, hand-written CSS, vanilla JS): no CDN, no
  inline scripts, CSP `script-src 'self'`.
- `docs/getting-started.md` (Docker quickstart + native), `docs/bluetooth-hfp.md`
  (HFP pairing/setup guide), `docs/configuration.md` (every env var),
  `docs/troubleshooting.md`.
- `CHANGELOG.md`, `CONTRIBUTING.md`.
- GitHub Release workflow (`.github/workflows/release.yml`) with GHCR image push
  on `v*` tags.
- `HOST`/`PORT` are now configurable via environment variables.

### Changed
- Experimental one-off scripts (`hfp_test.py`, `aurora_auto.py`,
  `audio-pipeline.sh`, `voice_agent.py`, `test_live.py`) moved to `examples/` —
  they are not imported by the app.
- `GeminiLiveClient` no longer raises at construction when `GEMINI_API_KEY` is
  unset, so the admin API can run key-less (API-only mode); the error surfaces
  at call time instead.

## [2.1.0]

### Added
- Initial public release: dual-mode voice agent (sales = Gemini Live native
  audio, interview = Gemini text → MiMo TTS voice clone with barge-in).
- Bluetooth HFP gateway (PC acts as hands-free headset for an Android phone,
  call detection/auto-answer via ADB).
- FastAPI admin API with fail-closed `X-API-Key` auth, rate limiting, body cap,
  security headers, WebSocket auth guard; lead capture + call logging to SQLite.
- CI: pytest + bandit + pip-audit + gitleaks.
