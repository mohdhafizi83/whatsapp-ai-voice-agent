# Bluetooth HFP Setup (critical path)

The agent turns your Linux PC into a **Bluetooth hands-free headset (HFP)**
for your Android phone. Incoming calls ring "into" the PC; the agent detects
them via ADB, auto-answers, and bridges the SCO audio to Gemini Live.

```
Phone call ⇄ Bluetooth SCO ⇄ BlueZ + PulseAudio ⇄ PyAudio ⇄ app.py ⇄ Gemini Live
```

**This cannot run in Docker** — containers have no Bluetooth stack or audio
hardware. Run natively on Linux.

## 1. Prerequisites (Debian/Ubuntu)

```bash
sudo apt install bluez bluez-tools pulseaudio pulseaudio-utils \
     libportaudio2 python3-dev
# ADB for call detection + auto-answer:
sudo apt install adb   # or platform-tools
```

## 2. Pair the phone (HFP profile)

```bash
bluetoothctl
  power on
  agent on
  default-agent
  scan on                 # make phone discoverable; note its MAC
  pair <PHONE_MAC>        # accept prompts on BOTH phone and PC
  trust <PHONE_MAC>
  quit
```

Put the phone's Bluetooth device settings for the PC → enable **Calls
(HFP/HSP)** profile. Verify the PC really got the hands-free profile:

```bash
pactl list cards short                 # expect a bluez.* card
pactl list sinks short | grep bluez    # SCO sink appears during a call
```

Put the MAC in `.env`: `BT_PHONE_MAC=<PHONE_MAC>`.

## 3. Connect ADB (call detection + auto-answer)

The engine polls `adb` to detect ringing and sends `KEYCODE_CALL` to answer.

- **USB:** enable Developer Options → USB debugging on the phone, then
  `adb devices` should list it.
- **Wi-Fi:** `adb tcpip 5555` once over USB, then `adb connect <phone-ip>:5555`
  (this is what `run_agent.sh` uses with `localhost:5555` via port-forward).

## 4. Run and test the audio path

```bash
set -a; source .env; set +a
python app.py
```

From another phone, call the paired phone. Expected log sequence:

```
Incoming call detected!
Answered call via ADB keyevent
Mode 1: Gemini Live Audio (Sales)
Gemini Live API session connected
```

Sanity probes live in `examples/`:

- `examples/hfp_test.py` — raw RFCOMM/AT test of the HFP link (edit the MAC at
  the top first)
- `examples/audio-pipeline.sh` — alternative PulseAudio routing setup used
  with scrcpy-based capture

## 5. Troubleshooting quick hits

| Symptom | Fix |
|---|---|
| `Bluetooth not connected. Waiting...` | `bluetoothctl info <MAC>` must show `Connected: yes`; re-pair/trust |
| No `bluez` sink in `pactl` | HFP profile not enabled for the device on the phone; `pactl set-card-profile <card> headset_head_unit` |
| `ADB not connected. Waiting...` | `adb devices` must show the phone as `device` (authorize the debugging prompt) |
| Call answered but caller hears nothing | SCO route dropped — check `pactl list sink-inputs` during the call |
| `OSError` from PyAudio at startup | `libportaudio2` missing, or no audio server running |

More in [troubleshooting.md](troubleshooting.md).
