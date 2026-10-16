# Troubleshooting

## Docker

**Container unhealthy / restarts in a loop**
- `docker compose logs voice-agent` — usually a Python import error (stale
  image: rebuild with `docker compose up -d --build`).
- Port already bound: change the host port in `docker-compose.yml`
  (`"8765:8765"` → `"<other>:8765"`).

**`env_file ... required: false` error**
- Needs Docker Compose ≥ v2.24. Upgrade, or delete the `env_file:` block and
  pass variables via `environment:` instead.

**`/api/leads` returns 501**
- `ADMIN_API_KEY` is not set in the container env. Set it in `.env` and
  recreate: `docker compose up -d`.

## Native

**`Bluetooth not connected. Waiting...`**
- `bluetoothctl info <MAC>` must print `Connected: yes`. Re-pair + `trust`.
  See [bluetooth-hfp.md](bluetooth-hfp.md).

**`ADB not connected. Waiting...`**
- `adb devices` must show the phone as `device`. Accept the USB-debugging
  prompt on the phone; for Wi-Fi ADB use `adb connect <ip>:5555`.

**`OSError: No Default Input Device Available` (PyAudio)**
- No PulseAudio/PipeWire session (e.g. running from a plain SSH session without
  a desktop). Start the audio server or run under the user's graphical session.

**`ModuleNotFoundError: pyaudio`**
- `pip install -r requirements.txt` needs `python3-dev` + `portaudio19-dev`
  headers to build PyAudio on Debian/Ubuntu.

**Calls connect but audio is one-way / silent**
- SCO route issue: during a call check `pactl list sinks short` for a
  `bluez.*` sink and set the card profile to `headset_head_unit`.

**`GEMINI_API_KEY is not set — cannot start a Gemini Live session`**
- Expected in API-only mode when a call arrives without a key. Set
  `GEMINI_API_KEY` and restart.

## Admin UI

**Panel loads but leads show "Invalid or missing API key"**
- Enter the server's `ADMIN_API_KEY` in the key box (it is kept in browser
  localStorage only).

**Blank page / blocked assets**
- The UI CSP only allows same-origin assets. If you reverse-proxy, keep
  `/assets/*` routed to the app (no CDN rewrites).
