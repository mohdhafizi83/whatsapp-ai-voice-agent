#!/usr/bin/env python3
"""
Voice Agent — Phone Call AI
Architecture:
  Phone speakerphone → phone mic → scrcpy→call_audio_in → capture → Gemini Live
  Gemini response → earphone/analog output → near phone mic → caller hears
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pyaudio

sys.path.insert(0, str(Path(__file__).parent))
from gemini_client import GeminiLiveClient
import config

# ── Audio Config ──────────────────────────────────────────────────
FORMAT = pyaudio.paInt16
RATE_CAPTURE = 48000    # call_audio_in sample rate
RATE_GEMINI = 16000     # Gemini expects 16kHz
CHUNK_SIZE = 2880       # 30ms at 48kHz stereo (48000*0.03*2)
SILENCE_THRESHOLD = 300  # higher = only capture when clearly speaking
VAD_TIMEOUT = 1.0        # faster response
MAX_RECORD_SECONDS = 6   # shorter clips
SYSTEM_PROMPT = (
    "You are a friendly AI assistant on a phone call. "
    "Speak naturally and concisely. Keep responses under 20 seconds. "
    "You are talking to the person who called. Be helpful and conversational."
)

logging.basicConfig(level=logging.DEBUG, format="%(message)s")
log = logging.getLogger("agent")


# ── Device Helpers ────────────────────────────────────────────────

def find_dev(pa, name_sub, mode="input"):
    """Find PulseAudio device index by name substring."""
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if name_sub in info["name"]:
            if mode == "input" and info["maxInputChannels"] > 0:
                return i
            if mode == "output" and info["maxOutputChannels"] > 0:
                return i
    return None


# ── Audio Capture ─────────────────────────────────────────────────

class AudioCapture:
    """Capture from call_audio_in.monitor, yield 16kHz mono PCM."""

    def __init__(self):
        self.pa = pyaudio.PyAudio()
        dev_idx = find_dev(self.pa, "call_audio_in.monitor", "input")
        if dev_idx is None:
            raise RuntimeError("PulseAudio device 'call_audio_in.monitor' not found")
        log.info(f"Capture device: [{dev_idx}] call_audio_in.monitor")
        self.dev_idx = dev_idx

    def stream(self):
        """Generator yielding 16kHz mono PCM chunks."""
        stream = self.pa.open(
            format=FORMAT, channels=2, rate=RATE_CAPTURE,
            input=True, input_device_index=self.dev_idx,
            frames_per_buffer=CHUNK_SIZE,
        )
        try:
            while True:
                raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                # stereo int16 → mono float32 → downsample 48k→16k → int16
                samples = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)
                mono = samples.mean(axis=1).astype(np.int16)
                yield mono[::3].tobytes()  # every 3rd = 16kHz
        finally:
            stream.close()

    def close(self):
        self.pa.terminate()


# ── Audio Playback ────────────────────────────────────────────────

class AudioPlayer:
    """Play 16kHz mono PCM through earphone (analog output)."""

    def __init__(self):
        self.pa = pyaudio.PyAudio()
        dev_idx = find_dev(self.pa, "analog-stereo", "output")
        if dev_idx is None:
            raise RuntimeError("PulseAudio output device not found")
        log.info(f"Playback device: [{dev_idx}] analog-stereo")
        self.dev_idx = dev_idx

    def play(self, chunk: bytes):
        if not chunk:
            return
        stream = self.pa.open(
            format=FORMAT, channels=1, rate=RATE_GEMINI,
            output=True, output_device_index=self.dev_idx,
        )
        stream.write(chunk)
        stream.close()

    def close(self):
        self.pa.terminate()


# ── VAD ───────────────────────────────────────────────────────────

def is_speech(chunk: bytes) -> bool:
    if not chunk or len(chunk) < 64:
        return False
    rms = np.sqrt(np.mean(np.frombuffer(chunk, dtype=np.int16).astype(float) ** 2))
    return rms > SILENCE_THRESHOLD


# ── Main ──────────────────────────────────────────────────────────

async def main():
    log.info("=" * 45)
    log.info(" VOICE AGENT — Phone Call AI")
    log.info("=" * 45)

    capture = AudioCapture()
    player = AudioPlayer()
    gemini = GeminiLiveClient()

    await gemini.connect(SYSTEM_PROMPT)
    log.info("✅ Gemini Live API connected\n")
    log.info("🎯 Waiting for caller to speak...")

    try:
        buffer = bytearray()
        silence_start = None
        speech_start = None

        for chunk in capture.stream():
            if not chunk:
                continue

            # Detect speech
            if is_speech(chunk):
                if speech_start is None:
                    speech_start = time.time()
                buffer.extend(chunk)
                silence_start = None
            else:
                buffer.extend(chunk)
                if len(buffer) > 0 and silence_start is None:
                    silence_start = time.time()

            # Check send conditions
            elapsed = time.time() - speech_start if speech_start else 0
            send_now = False
            if silence_start and (time.time() - silence_start > VAD_TIMEOUT):
                send_now = True
            elif elapsed > MAX_RECORD_SECONDS:
                send_now = True

            if not send_now:
                continue

            # Skip if too short
            if len(buffer) < 256:
                buffer = bytearray()
                silence_start = None
                speech_start = None
                continue

            # Send to Gemini
            audio = bytes(buffer)
    
            # Amplify audio (5x gain) for Gemini speech recognition
            audio_arr = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
            audio_arr *= 5.0
            audio_arr = np.clip(audio_arr, -32767, 32767).astype(np.int16)
            audio = audio_arr.tobytes()
    
            dur = len(audio) / 2 / RATE_GEMINI
            log.info(f"\n📤 Send {dur:.1f}s → Gemini")
            await gemini.send_audio(audio)

            # Play response
            n = 0
            async for resp in gemini.receive():
                if resp:
                    player.play(resp)
                    n += 1

            log.info(f"✅ Response OK ({n} chunks)")
            buffer = bytearray()
            silence_start = None
            speech_start = None
            log.info("🎯 Waiting for caller...")

    except KeyboardInterrupt:
        log.info("\n\n⏹ Stopped")
    finally:
        await gemini.close()
        capture.close()
        player.close()
        log.info("Cleanup done.")


if __name__ == "__main__":
    asyncio.run(main())
