# Examples / experimental scripts

One-off probes and superseded prototypes. **Not imported by the app** — keep
experiments here, not in the repo root. Hardware-specific constants (MACs,
serials) are the original author's — edit before running.

| File | What it is |
|---|---|
| `hfp_test.py` | Raw RFCOMM socket + AT-command probe of the phone's HFP Audio Gateway |
| `aurora_auto.py` | ADB GUI automation that installs WhatsApp via Aurora Store (screenshot-driven) |
| `audio-pipeline.sh` | PulseAudio routing setup for the scrcpy-based capture pipeline |
| `voice_agent.py` | Superseded prototype: WhatsApp **Web** in Chromium + virtual PulseAudio devices + OpenAI Whisper STT + edge-tts (needs `openai` package, not in requirements) |
| `test_live.py` | Minimal Gemini Live API smoke test (needs `GEMINI_API_KEY`, hits the network) |

The supported phone-call engine is `voice_agent_phone.py` / `app.py` at the
repo root.
