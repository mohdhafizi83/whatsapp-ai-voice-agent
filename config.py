"""
Voice Agent — Configuration

Dual Mode:
  Mode 1: Sales Rep (Gemini native audio)
  Mode 2: Interview (Gemini → ElevenLabs voice clone)

Telephony: Bluetooth HFP Gateway (PC jadi Hands-Free Headset)
"""

import os
from pathlib import Path

# ─── Project Paths ───────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
STORAGE_DIR = BASE_DIR / "storage"

# ─── Bluetooth HFP Gateway ──────────────────────────────────────
# MAC address Android phone (bluetoothctl scan untuk dapat)
BT_PHONE_MAC = os.getenv("BT_PHONE_MAC", "")

# ─── Gemini Live API ──────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-live-preview"
GEMINI_API_VERSION = "v1alpha"

# ─── ElevenLabs / MiMo TTS (Mode 2 — Voice Clone) ─────────────────
# Option A: ElevenLabs (lama — RM23/bln)
# ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
# ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
# ELEVENLABS_MODEL = "eleven_flash_v2_5"

# Option B: MiMo-v2.5-TTS (baru — RM0, guna kredit sedia ada) ✅
MIMO_API_KEY = os.getenv("XIAOMI_API_KEY", "")
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_TTS_MODEL = "mimo-v2.5-tts-voiceclone"  # Voice cloning model
MIMO_TTS_MODEL_DESIGN = "mimo-v2.5-tts-voicedesign"  # Create voice from description

# ─── Server ───────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8765"))

# ─── Current Mode ─────────────────────────────────────────────────
# "sales" = Mode 1 (Gemini audio output, preset voice)
# "interview" = Mode 2 (Gemini text → ElevenLabs voice clone)
ACTIVE_MODE = os.getenv("AGENT_MODE", "sales")

# ─── Audio Settings ───────────────────────────────────────────────
# Bluetooth SCO audio is 8kHz mono. Gemini expects 16kHz.
AUDIO_RATE_BT = 8000
AUDIO_RATE_GEMINI = 16000
AUDIO_CHANNELS = 1
AUDIO_FORMAT_SAMPLE_WIDTH = 2  # 16-bit

# Voice settings for Gemini output (Mode 1)
GEMINI_VOICE_NAME = "Puck"
