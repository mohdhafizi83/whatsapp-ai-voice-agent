# Getting Started — WhatsApp AI Voice Agent

Two ways to run: **Docker** (admin API + web UI only) or **native** (full
product, including the Bluetooth call engine).

> ⚠️ **Docker does not cover the phone/audio path.** The Bluetooth HFP engine
> needs host BlueZ, PulseAudio and ADB hardware, which containers don't have.
> The container runs with `VOICE_AGENT_DISABLE_ENGINE=1` and serves the admin
> API + `/admin` panel. To answer real calls, install natively and follow
> [Bluetooth HFP Setup](bluetooth-hfp.md).

## Requirements

- Docker + Docker Compose v2.24+ *(for the Docker path)*
- OR Python 3.11+, Linux with BlueZ (`bluez-tools`), `pulseaudio`/`pipewire` with `pulseaudio-utils`, `adb` *(for the full native path)*
- Gemini API key ([Google AI Studio](https://aistudio.google.com/apikey))
- Optional: MiMo (Xiaomi) API key for interview-mode voice clone

## Quickstart (Docker — admin API + UI)

```bash
git clone https://github.com/mohdhafizi83/whatsapp-ai-voice-agent.git
cd whatsapp-ai-voice-agent
cp .env.example .env      # set at least ADMIN_API_KEY (openssl rand -hex 32)
docker compose up -d --build
```

Check it came up:

```bash
docker compose ps                     # should show "healthy"
curl http://localhost:8765/           # {"status":"running","mode":"sales",...}
```

Open **http://localhost:8765/admin** — the admin panel. Paste your
`ADMIN_API_KEY` into the "Admin API key" box (stored in your browser only) to
view leads and switch modes.

## Install without Docker (full product, with calls)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill BT_PHONE_MAC, GEMINI_API_KEY, ADMIN_API_KEY
```

Pair your Android phone as a hands-free device — **follow
[docs/bluetooth-hfp.md](bluetooth-hfp.md)** (pair, trust, HFP profile, ADB).
Then:

```bash
set -a; source .env; set +a
python app.py                          # sales mode
AGENT_MODE=interview python app.py     # interview mode
```

`app.py` starts both the FastAPI admin API (port 8765) and the call engine
that waits for incoming calls. A `voice-agent.service` systemd unit is
included for always-on setups.

## Verify it works

```bash
curl http://localhost:8765/                                  # status JSON
curl -H "X-API-Key: ***" http://localhost:8765/api/leads   # lead list
curl -X POST "http://localhost:8765/api/mode?mode=interview" \
     -H "X-API-Key: ***"                                    # switch mode
```

## Next steps

- [Configuration](configuration.md) — every environment variable
- [Bluetooth HFP Setup](bluetooth-hfp.md) — pairing & call path
- [Troubleshooting](troubleshooting.md) — common failures
- [Contributing](../CONTRIBUTING.md) — dev setup & conventions
