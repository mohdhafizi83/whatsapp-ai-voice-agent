# WhatsApp AI Voice Agent

A real-time AI voice agent that turns your PC into a Bluetooth hands-free gateway: incoming phone/WhatsApp calls are answered by an AI agent (Gemini Live) that talks with the caller, captures leads, and logs every conversation.

## Features

- **Bluetooth HFP gateway** — your Linux PC pairs with an Android phone as a hands-free headset; calls ring through the agent automatically
- **Dual mode**:
  - `sales` — Gemini Live native audio (fast, preset voice)
  - `interview` — Gemini text → MiMo TTS voice clone (with barge-in / interruption handling)
- **Knowledge base** — inject company/product context so the agent answers accurately
- **Lead capture** — caller details extracted and stored (SQLite)
- **Call logging** — full transcripts persisted per call
- **Mode switching at runtime** via admin API

## Architecture

```
Phone (Bluetooth HFP) ⇄ bluetooth_audio.py ⇄ app.py (FastAPI + asyncio engine)
                                             ⇅
                              gemini_client.py (Gemini Live API)
                                             ⇅
                              elevenlabs_client.py (MiMo TTS, interview mode)
                                             ⇅
                              knowledge_base.py + call_logger.py (SQLite)
```

## Requirements

- Linux with BlueZ (Bluetooth stack) + `bluez-tools`
- Android phone paired via `bluetoothctl` (HFP profile)
- Python 3.11+
- Gemini API key (Google AI Studio)
- Optional: MiMo API key for voice-clone mode

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in your keys
python app.py          # sales mode
AGENT_MODE=interview python app.py   # interview mode
```

Pair Bluetooth first:

```bash
bluetoothctl
> power on
> scan on            # find your phone
> pair <MAC>
> trust <MAC>
```

## Admin API

All admin endpoints require `X-API-Key` header (set `ADMIN_API_KEY` in `.env`; fail-closed — endpoints return 501 if unset).

```bash
# List captured leads
curl -H "X-API-Key: $ADMIN_API_KEY" http://localhost:8765/api/leads

# Switch mode
curl -X POST "http://localhost:8765/api/mode?mode=interview" -H "X-API-Key: $ADMIN_API_KEY"
```

## Security

- **Admin API key required** (`X-API-Key`, constant-time comparison) — no key configured = endpoints disabled (501)
- **Rate limiting** — 30 req/min per IP on admin endpoints
- **No secrets in code** — all credentials via environment variables (`.env`, gitignored)
- **Input validation** — mode parameter whitelisted (`sales`/`interview`)
- **PII local** — call logs and leads stay in your local SQLite DB; nothing is synced anywhere

> ⚠️ Run behind a reverse proxy with TLS if exposing the admin API beyond localhost.
> The default bind is `0.0.0.0:8765` — restrict with a firewall if not needed externally.

## systemd

`voice-agent.service` included — copy to `~/.config/systemd/user/`, adjust paths, then `systemctl --user enable --now voice-agent`.

## License

MIT
