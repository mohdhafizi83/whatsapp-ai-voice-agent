#!/usr/bin/env python3
"""
Voice Agent — WhatsApp Web Voice AI
Captures caller audio from WhatsApp Web, processes with AI, responds via virtual mic.

Architecture:
  WhatsApp Web → wa_speaker (PulseAudio sink) → wa_speaker.monitor → AI captures
  AI plays → wa_mic_pipe (PulseAudio sink) → wa_mic (virtual source) → WhatsApp Web mic

Requirements:
  - PulseAudio virtual devices: wa_speaker, wa_mic_pipe, wa_mic (see audio-setup.sh)
  - Chromium running with web.whatsapp.com under Xvfb
  - OpenAI API key for Whisper STT
  - DeepSeek / LLM API key
  - edge-tts for TTS
"""

import asyncio
import json
import os
import queue
import struct
import sys
import time
import threading
from pathlib import Path

import numpy as np
import pyaudio
from openai import OpenAI

# ── Configuration ────────────────────────────────────────────────────────────

# PulseAudio device names (configured via audio-setup.sh)
WA_SPEAKER_MONITOR = "wa_speaker.monitor"   # Capture caller's voice
WA_MIC_SINK = "wa_mic_pipe"                  # Play AI response (-> wa_mic source)

# Audio settings
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000          # 16kHz standard for speech
CHUNK = 1024          # Frames per buffer
SILENCE_DURATION = 1.5  # Seconds of silence before sending to STT
SILENCE_THRESHOLD = 500  # RMS threshold for silence detection
MAX_RECORD_SECONDS = 30   # Max recording length before forced send

# VAD settings
MIN_SPEECH_DURATION = 0.5  # Minimum speech duration to process (seconds)

# API Keys (from env)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# System prompt for AI agent
SYSTEM_PROMPT = """You are a helpful voice AI assistant. Respond naturally and conversationally.
Keep responses concise (under 30 seconds when spoken). Answer questions helpfully.
When you don't know something, say so honestly."""


# ── Audio Capture ────────────────────────────────────────────────────────────

class VoiceActivityDetector:
    """Simple energy-based VAD."""
    
    def __init__(self, threshold=SILENCE_THRESHOLD, sample_rate=RATE, chunk_duration=0.032):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.chunk_samples = int(sample_rate * chunk_duration)
    
    def is_speech(self, audio_chunk: bytes) -> bool:
        """Check if audio chunk contains speech based on RMS energy."""
        samples = np.frombuffer(audio_chunk, dtype=np.int16)
        if len(samples) == 0:
            return False
        rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
        return rms > self.threshold
    
    def compute_rms(self, audio_chunk: bytes) -> float:
        samples = np.frombuffer(audio_chunk, dtype=np.int16)
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))


class AudioCapture:
    """Captures audio from PulseAudio monitor source with VAD."""
    
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.source_index = self._find_source()
        self.vad = VoiceActivityDetector()
        self.running = False
    
    def _find_source(self) -> int:
        """Find wa_speaker.monitor source index."""
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            name = info.get("name", "")
            if WA_SPEAKER_MONITOR in name:
                print(f"  ✓ Found source: {name} (index {i})")
                return i
        
        # Fallback: try to find any monitor source
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            name = info.get("name", "")
            if "monitor" in name.lower():
                print(f"  ⚠ Fallback source: {name} (index {i})")
                return i
        
        print("  ✗ Could not find wa_speaker.monitor. Run audio-setup.sh first.")
        sys.exit(1)
    
    def _find_sink(self) -> int:
        """Find wa_mic_pipe sink index for playback."""
        # PyAudio lists both inputs and outputs as devices.
        # We need the sink device for playback.
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            name = info.get("name", "")
            if WA_MIC_SINK in name and info.get("maxOutputChannels", 0) > 0:
                print(f"  ✓ Found sink: {name} (index {i})")
                return i
        
        # Fallback to default output
        print("  ⚠ wa_mic_pipe not found, using default output")
        return self.p.get_default_output_device_info()["index"]
    
    def capture_utterance(self, timeout=10) -> bytes:
        """
        Capture a complete utterance (speech + trailing silence).
        Returns PCM 16-bit mono 16kHz audio bytes.
        """
        stream = self.p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=self.source_index,
            frames_per_buffer=CHUNK,
            stream_capture_callback=None,
        )
        
        print("  🎤 Listening...")
        frames = []
        speech_active = False
        silence_frames = 0
        silence_needed = int(SILENCE_DURATION * RATE / CHUNK)
        total_frames = 0
        max_frames = int(MAX_RECORD_SECONDS * RATE / CHUNK)
        
        try:
            while total_frames < max_frames:
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                total_frames += 1
                
                rms = self.vad.compute_rms(data)
                is_speech = rms > SILENCE_THRESHOLD
                
                if is_speech:
                    if not speech_active:
                        speech_active = True
                        print("  🗣 Speech detected...")
                    silence_frames = 0
                elif speech_active:
                    silence_frames += 1
                    if silence_frames >= silence_needed:
                        print(f"  🤫 Silence detected (rms={rms:.1f})")
                        break
                
                # Progress indicator
                if total_frames % 50 == 0 and speech_active:
                    print(f"  Recording... {total_frames * CHUNK / RATE:.1f}s")
            
            if not speech_active and total_frames > 0:
                print("  ⏭ No speech detected")
                return b""
            
        finally:
            stream.stop_stream()
            stream.close()
        
        audio_bytes = b"".join(frames)
        duration = len(audio_bytes) / (CHANNELS * 2) / RATE
        print(f"  📝 Captured {duration:.1f}s of audio")
        return audio_bytes
    
    def close(self):
        self.p.terminate()


# ── Speech-to-Text ───────────────────────────────────────────────────────────

def transcribe_whisper(audio_bytes: bytes, api_key: str) -> str:
    """Transcribe audio using OpenAI Whisper API."""
    if not api_key:
        print("  ✗ No OpenAI API key for Whisper STT")
        return ""
    
    import tempfile
    client = OpenAI(api_key=api_key)
    
    # Save audio bytes to temp file for Whisper API
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    
    try:
        with open(tmp_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ms",  # Malay - will auto-detect English too
            )
        text = transcript.text.strip()
        print(f"  📝 STT: {text[:100]}")
        return text
    except Exception as e:
        print(f"  ✗ Whisper API error: {e}")
        return ""
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass


# ── LLM ──────────────────────────────────────────────────────────────────────

def ask_llm(text: str, system_prompt: str, api_key: str = "", base_url: str = "") -> str:
    """
    Send text to LLM and get response.
    Uses DeepSeek if available, otherwise tries OpenAI.
    """
    # Try DeepSeek first
    if api_key:
        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",  # or deepseek-reasoner
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=300,
                temperature=0.7,
            )
            reply = response.choices[0].message.content.strip()
            print(f"  🤖 LLM: {reply[:100]}")
            return reply
        except Exception as e:
            print(f"  ⚠ DeepSeek error: {e}")
    
    # Fallback: try OpenAI
    if os.environ.get("OPENAI_API_KEY"):
        try:
            client = OpenAI()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=300,
            )
            reply = response.choices[0].message.content.strip()
            print(f"  🤖 LLM: {reply[:100]}")
            return reply
        except Exception as e:
            print(f"  ⚠ OpenAI error: {e}")
    
    # Final fallback: echo
    print("  ✗ No LLM available")
    return "Maaf, saya tak dapat proses pertanyaan anda sekarang."


# ── Text-to-Speech ───────────────────────────────────────────────────────────

async def speak_edge_tts(text: str, sink_name: str) -> None:
    """Speak text via edge-tts, play to wa_mic_pipe sink."""
    import edge_tts
    
    # Use Malay voice if text contains Malay, else English
    voice = "ms-MY-YasminNeural"  # Malay (Malaysia)
    # Check if primarily English
    malay_words = {"maaf", "saya", "anda", "tak", "dapat", "ini", "itu", 
                   "dan", "yang", "adalah", "untuk", "dengan", "tidak"}
    eng_ratio = sum(1 for w in text.lower().split() if w not in malay_words) / max(len(text.split()), 1)
    if eng_ratio > 0.8:
        voice = "en-US-JennyNeural"
    
    print(f"  🔊 TTS ({'ms-MY' if eng_ratio <= 0.8 else 'en-US'}): {text[:80]}")
    
    communicate = edge_tts.Communicate(text, voice)
    
    # Play to wa_mic_pipe sink
    p = pyaudio.PyAudio()
    stream = None
    
    try:
        # Find sink index for playback (alsa_output or wa_mic_pipe)
        sink_idx = None
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            name = info.get("name", "")
            if sink_name in name and info.get("maxOutputChannels", 0) > 0:
                sink_idx = i
                break
        
        if sink_idx is None:
            # Find PulseAudio sink via pabort
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info.get("maxOutputChannels", 0) > 0 and "alsa" in info.get("name", ""):
                    sink_idx = i
                    break
        
        if sink_idx is None:
            sink_idx = p.get_default_output_device_info()["index"]
        
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,  # edge-tts output
            output=True,
            output_device_index=sink_idx,
            frames_per_buffer=CHUNK,
        )
        
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                stream.write(chunk["data"])
    
    except Exception as e:
        print(f"  ⚠ TTS play error: {e}")
    finally:
        if stream:
            stream.stop_stream()
            stream.close()
        p.terminate()


def speak_sync(text: str, sink_name: str):
    """Synchronous wrapper for edge-tts."""
    asyncio.run(speak_edge_tts(text, sink_name))


# ── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════╗")
    print("║     Voice Agent — WhatsApp Web AI        ║")
    print("╚══════════════════════════════════════════╝")
    print()
    
    # Check API keys
    deepseek_key = DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY", os.environ.get("HERMES_DEEPSEEK_API_KEY", ""))
    openai_key = OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    
    if not deepseek_key and not openai_key:
        print("⚠ WARNING: No LLM API key configured. Set DEEPSEEK_API_KEY or OPENAI_API_KEY.")
        print("  The agent will not process speech, but audio capture will still work.\n")
    else:
        print(f"✓ LLM: {'DeepSeek' if deepseek_key else ''}{' + ' if deepseek_key and openai_key else ''}{'OpenAI' if openai_key else ''}")
    
    print()
    print("Audio Pipeline:")
    print("  WhatsApp Web → wa_speaker → wa_speaker.monitor → AI captures")
    print("  AI responds  → wa_mic_pipe → wa_mic virtual source → WhatsApp Web")
    print()
    
    # Initialize audio capture
    capture = AudioCapture()
    
    # Conversation history (in-memory, per-call)
    history = []
    
    print("\nReady! Waiting for WhatsApp Web call...")
    print("(Press Ctrl+C to stop)\n")
    
    try:
        while True:
            # 1. Capture caller's utterance
            audio = capture.capture_utterance(timeout=30)
            
            if not audio:
                print("  ...no speech detected, listening again...\n")
                continue
            
            # 2. Transcribe
            text = transcribe_whisper(audio, openai_key)
            
            if not text:
                continue
            
            # 3. LLM response
            history.append({"role": "user", "content": text})
            
            # Keep only last 5 exchanges for context
            if len(history) > 10:
                history = history[-10:]
            
            response = ask_llm(
                text,
                SYSTEM_PROMPT + "\n\nConversation history:\n" + json.dumps(history[-6:]),
                deepseek_key,
                DEEPSEEK_BASE_URL,
            )
            
            history.append({"role": "assistant", "content": response})
            
            # 4. Speak response
            if response:
                speak_sync(response, WA_MIC_SINK)
            
            print()
    
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        capture.close()
    print("Voice agent stopped.")


if __name__ == "__main__":
    main()
