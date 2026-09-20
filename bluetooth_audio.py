"""
Bluetooth HFP Audio Bridge

Capture audio dari Bluetooth SCO (Hands-Free Profile) dan stream ke Gemini.
FiziServerStation bertindak sebagai Bluetooth Car Kit / Hands-Free Headset.

Audio path:
  Phone mic/call → Bluetooth SCO → PulseAudio → PyAudio → Gemini
  Gemini response → PyAudio → PulseAudio → Bluetooth SCO → Phone speaker/call
"""

import asyncio
import logging
import subprocess
import time
from typing import Optional

import pyaudio
import numpy as np

import config

logger = logging.getLogger("voice-agent.bluetooth")


def find_bluetooth_audio_device() -> Optional[int]:
    """Find the Bluetooth SCO audio device index in PyAudio."""
    p = pyaudio.PyAudio()
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        name = dev["name"].lower()
        # Bluetooth SCO devices appear as "bluez" in PulseAudio
        if "bluez" in name or "bluetooth" in name:
            logger.info(f"Found Bluetooth device: {dev['name']} (index={i})")
            p.terminate()
            return i
    p.terminate()
    return None


def check_bluetooth_connection() -> bool:
    """Verify Bluetooth phone is connected."""
    try:
        result = subprocess.run(
            ["bluetoothctl", "info", config.BT_PHONE_MAC],
            capture_output=True, text=True, timeout=5
        )
        if "Connected: yes" in result.stdout:
            return True
        return False
    except Exception as e:
        logger.error(f"Bluetooth check failed: {e}")
        return False


def get_bluetooth_source_sink():
    """Get PulseAudio Bluetooth source (mic) and sink (speaker) names."""
    try:
        result = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True, timeout=5
        )
        sink = None
        for line in result.stdout.split("\n"):
            if "bluez" in line.lower():
                parts = line.split()
                sink = parts[1] if len(parts) > 1 else None
                break

        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True, text=True, timeout=5
        )
        source = None
        for line in result.stdout.split("\n"):
            if "bluez" in line.lower():
                parts = line.split()
                source = parts[1] if len(parts) > 1 else None
                break

        return source, sink
    except Exception as e:
        logger.error(f"PulseAudio query failed: {e}")
        return None, None


class BluetoothAudioBridge:
    """
    Bridge antara Bluetooth SCO audio dan Gemini Live API.
    
    Capture audio dari Bluetooth → PCM 16kHz → Gemini
    Gemini response → PCM → Bluetooth playback
    """

    def __init__(self):
        self.pyaudio = pyaudio.PyAudio()
        self.device_index = None
        self.source, self.sink = None, None

    def setup(self) -> bool:
        """Initialize Bluetooth audio devices."""
        # Check connection
        if not check_bluetooth_connection():
            logger.error("Bluetooth phone not connected!")
            return False

        # Find PulseAudio Bluetooth devices
        self.source, self.sink = get_bluetooth_source_sink()
        if not self.source or not self.sink:
            logger.error("No PulseAudio Bluetooth source/sink found!")
            return False

        logger.info(f"Bluetooth source (mic): {self.source}")
        logger.info(f"Bluetooth sink (speaker): {self.sink}")
        return True

    def open_input_stream(self, rate=8000, channels=1, chunk=3200):
        """Open audio input stream from Bluetooth SCO."""
        return self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            frames_per_buffer=chunk,
        )

    def open_output_stream(self, rate=8000, channels=1, chunk=3200):
        """Open audio output stream to Bluetooth SCO."""
        return self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            output=True,
            frames_per_buffer=chunk,
        )

    def resample(self, audio_data: bytes, from_rate: int, to_rate: int) -> bytes:
        """Resample audio between rates (8kHz ↔ 16kHz)."""
        if from_rate == to_rate:
            return audio_data

        samples = np.frombuffer(audio_data, dtype=np.int16)
        ratio = to_rate / from_rate
        new_length = int(len(samples) * ratio)
        resampled = np.interp(
            np.linspace(0, len(samples) - 1, new_length),
            np.arange(len(samples)),
            samples
        ).astype(np.int16)
        return resampled.tobytes()

    def cleanup(self):
        """Close all PyAudio streams."""
        self.pyaudio.terminate()


class PhoneCallMonitor:
    """
    Monitor Android phone via ADB for incoming calls.
    Auto-answer using ADB tap commands.
    """

    def __init__(self):
        self.is_calling = False

    def check_adb_connection(self) -> bool:
        """Verify ADB connection to phone."""
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")
            # Skip header line, check for device
            for line in lines[1:]:
                if "device" in line and "offline" not in line:
                    return True
            return False
        except Exception:
            return False

    def check_incoming_call(self) -> bool:
        """Check if there's an incoming call via dumpsys."""
        try:
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "telephony.registry"],
                capture_output=True, text=True, timeout=5
            )
            return "mRinging" in result.stdout and "null" not in result.stdout
        except Exception:
            return False

    def check_active_call(self) -> bool:
        """Check if there's an active call."""
        try:
            result = subprocess.run(
                ["adb", "shell", "dumpsys", "telephony.registry"],
                capture_output=True, text=True, timeout=5
            )
            return "mForegroundCallState: 2" in result.stdout
        except Exception:
            return False

    def answer_call(self):
        """Auto-answer incoming call via ADB tap."""
        # Method 1: Use ADB input tap (coordinates need adjustment per phone)
        # Method 2: Use ADB keyevent to answer
        try:
            # KEYCODE_CALL = 5 — answer call
            subprocess.run(
                ["adb", "shell", "input", "keyevent", "5"],
                timeout=5
            )
            logger.info("Answered call via ADB keyevent")
        except Exception as e:
            logger.error(f"Failed to answer call: {e}")

    def end_call(self):
        """End active call via ADB."""
        try:
            # KEYCODE_ENDCALL = 6 — end call
            subprocess.run(
                ["adb", "shell", "input", "keyevent", "6"],
                timeout=5
            )
            logger.info("Ended call via ADB keyevent")
        except Exception as e:
            logger.error(f"Failed to end call: {e}")
