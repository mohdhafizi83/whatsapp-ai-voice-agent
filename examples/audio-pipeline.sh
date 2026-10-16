#!/bin/bash
# Audio Pipeline for WhatsApp Voice Agent
# Requires: Phone connected via USB ADB (7a5255b5)

set -e

PHONE_SERIAL="7a5255b5"
AUDIO_SINK="call_audio_in"     # Sink for incoming call audio (from phone)
OUTPUT_SINK="call_audio_out"   # Sink for AI voice (to phone)

echo "=== Starting WhatsApp Voice Agent Audio Pipeline ==="

# 1. Kill any existing scrcpy audio capture
pkill -f "scrcpy.*audio-source" 2>/dev/null || true
sleep 1

# 2. Capture phone audio output → call_audio_in sink
# scrcpy --audio-source=output captures the phone's audio output
# (ringer, notifications, media, and hopefully call audio)
echo "[1] Starting phone audio capture..."
scrcpy -s "$PHONE_SERIAL" \
    --audio-source=output \
    --no-video \
    --no-window \
    --audio-sink="$AUDIO_SINK" \
    --audio-dup \
    --stay-awake \
    --no-clipboard-autosync &

SCRCPY_PID=$!
echo "     scrcpy PID: $SCRCPY_PID"

# Wait for scrcpy to establish
sleep 2

# 3. Create loopback: route phone audio to voice agent's processing
# Voice agent reads from call_audio_in.monitor for STT
echo "[2] Audio capture: call_audio_in.monitor → Voice Agent"

# 4. Create loopback: voice agent plays TTS to analog output
# The phone in speakerphone mode picks up analog output via its mic
echo "[3] Audio playback: Voice Agent → call_audio_out → analog output"

echo ""
echo "=== Pipeline Status ==="
echo "Capture: scrcpy → call_audio_in → Voice Agent (STT)"
echo "Playback: Voice Agent (TTS) → call_audio_out → Speaker 🔊"
echo ""
echo "scrcpy PID: $SCRCPY_PID"
echo "To stop: kill $SCRCPY_PID"
echo ""

# Show audio sources
echo "Active audio sources:"
pactl list sources short | grep -E "call_audio|RUNNING"
