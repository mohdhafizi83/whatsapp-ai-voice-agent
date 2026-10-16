# Configuration — WhatsApp AI Voice Agent

All runtime configuration is environment variables (loaded from `.env` by your
launcher; `voice-agent.service` uses `EnvironmentFile=.env`). Copy
`.env.example` → `.env` and edit.

## .env variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes (calls) | — | Google AI Studio API key for Gemini Live. Without it the admin API still runs, but calls fail at connect time. |
| `BT_PHONE_MAC` | Yes (calls) | — | MAC of the paired Android phone (`bluetoothctl scan on`). Used by `bluetoothctl info` connection checks. |
| `ADMIN_API_KEY` | Yes (admin API) | *(empty)* | Protects `/api/leads` and `/api/mode` via `X-API-Key` header. Generate: `openssl rand -hex 32`. **Fail-closed:** unset ⇒ admin endpoints return 501. |
| `AGENT_MODE` | No | `sales` | `sales` = Mode 1 (Gemini native audio) · `interview` = Mode 2 (Gemini text → MiMo TTS voice clone with barge-in). Runtime-switchable via `POST /api/mode`. |
| `XIAOMI_API_KEY` | Interview mode | — | MiMo (Xiaomi) TTS key for voice cloning in interview mode. |
| `VOICE_AGENT_DISABLE_ENGINE` | No | *(unset)* | `1` = serve the API without the Bluetooth call loop (tests, CI, Docker, API-only hosts). The Docker image sets this automatically. |
| `HOST` | No | `0.0.0.0` | Bind address for the FastAPI server. |
| `PORT` | No | `8765` | Port for the FastAPI server. |
| `ELEVENLABS_API_KEY` | No (legacy) | — | Optional alternative TTS for interview mode (code path currently commented out in `config.py`; MiMo is the default). |
| `ELEVENLABS_VOICE_ID` | No (legacy) | — | Voice id for the legacy ElevenLabs path. |

## Fixed settings (`config.py`)

Not env-configurable; edit `config.py` if you must change them:

| Setting | Value | Meaning |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.1-flash-live-preview` | Gemini Live model |
| `GEMINI_API_VERSION` | `v1alpha` | API version |
| `GEMINI_VOICE_NAME` | `Puck` | Preset voice for sales mode |
| `MIMO_TTS_MODEL` | `mimo-v2.5-tts-voiceclone` | Interview-mode voice-clone model |
| `AUDIO_RATE_BT` / `AUDIO_RATE_GEMINI` | 8000 / 16000 | SCO ↔ Gemini resampling |
| `PORT`/`HOST` defaults | 8765 / 0.0.0.0 | Overridable via env (see above) |

## Files & paths

| Path | Purpose |
|---|---|
| `.env` | Secrets + settings (gitignored — never commit it) |
| `templates/system_prompt_sales.md` | System prompt, sales mode (`{caller_number}`, `{agent_name}` placeholders) |
| `templates/system_prompt_interview.md` | System prompt, interview mode |
| `knowledge/*.md` | Knowledge-base docs injected into interview-mode prompts |
| `storage/calls.db` | SQLite: calls, transcripts, leads (mounted volume in Docker) |

## Security notes

- Admin endpoints: 30 req/min per IP rate limit, 1 MB body cap, constant-time
  key comparison, security headers on every response.
- Bind is `0.0.0.0` by default — put TLS/reverse proxy in front if the port is
  reachable beyond localhost, or set `HOST=127.0.0.1`.
