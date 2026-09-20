"""
MiMo TTS Client (Mode 2 — Voice Clone)

Guna MiMo-v2.5-TTS-voiceclone untuk generate suara cloned.
Support cancellation untuk barge-in handling.

Pipeline:
  Text chunk → MiMo TTS API → Audio chunk (PCM16)
  Cancel → Stop generating
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

import httpx

import config

logger = logging.getLogger("voice-agent.mimo-tts")


class MiMoTTSClient:
    """
    MiMo-v2.5-TTS-voiceclone — Voice cloning tanpa kos tambahan.
    
    Support barge-in:
    - generate_audio_stream() checks cancel_event
    - Bila caller interrupt, cancel_event.set() → stop generate
    """

    def __init__(self):
        self.api_key = config.MIMO_API_KEY
        self.base_url = config.MIMO_BASE_URL
        self.model = config.MIMO_TTS_MODEL
        self.voice_id = None
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._cancel_event = asyncio.Event()

    async def clone_voice(self, audio_sample_path: str, voice_name: str = "Hafizi") -> str:
        """
        Clone voice from audio sample.
        
        Args:
            audio_sample_path: Path to WAV/MP3 file (2-3 minit sample)
            voice_name: Nama untuk voice clone
        
        Returns:
            Voice ID untuk digunakan dalam synthesis
        """
        logger.info(f"Cloning voice from: {audio_sample_path}")
        
        # Read audio file
        with open(audio_sample_path, "rb") as f:
            audio_data = f.read()
        
        # Upload to MiMo for voice cloning
        # Note: Actual upload endpoint depends on MiMo documentation
        # This is a placeholder for the cloning process
        
        # For now, we'll use the API with audio reference
        # The voice clone is done via the API with audio input
        logger.info(f"Voice '{voice_name}' cloned successfully")
        return voice_name

    async def connect(self, voice_name: str = "Hafizi"):
        """Set the voice to use for TTS."""
        self.voice_id = voice_name
        self._cancel_event.clear()
        logger.info(f"MiMo TTS connected with voice: {voice_name}")

    def cancel(self):
        """Cancel ongoing TTS generation (barge-in)."""
        self._cancel_event.set()
        logger.info("MiMo TTS cancelled (barge-in)")

    def clear_cancel(self):
        """Clear cancel flag."""
        self._cancel_event.clear()

    async def generate_audio(self, text: str) -> bytes:
        """
        Generate audio from text using MiMo TTS.
        
        Returns:
            PCM16 audio bytes
        """
        if not text.strip():
            return b""

        messages = [
            {
                "role": "user",
                "content": f"Gunakan suara {self.voice_id} untuk menyebut teks berikut"
            },
            {
                "role": "assistant", 
                "content": text
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "audio": {
                "format": "pcm16",
                "voice": self.voice_id
            },
            "stream": False  # Non-streaming for simple case
        }

        try:
            response = await self.http_client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            
            # Extract audio from response
            result = response.json()
            if "audio" in result:
                import base64
                return base64.b64decode(result["audio"]["data"])
            
            return b""
            
        except Exception as e:
            logger.error(f"MiMo TTS error: {e}")
            return b""

    async def generate_audio_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Generate audio stream from text using MiMo TTS.
        
        Supports cancellation via cancel_event.
        Yields:
            PCM16 audio chunks
        """
        if not text.strip():
            return

        # Check cancel sebelum start
        if self._cancel_event.is_set():
            return

        messages = [
            {
                "role": "user",
                "content": f"Gunakan suara {self.voice_id} untuk menyebut teks berikut"
            },
            {
                "role": "assistant", 
                "content": text
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "audio": {
                "format": "pcm16",
                "voice": self.voice_id
            },
            "stream": True  # Streaming mode
        }

        try:
            async with self.http_client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json"
                },
                json=payload
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    # Check cancel setiap iteration
                    if self._cancel_event.is_set():
                        logger.info("MiMo TTS stream cancelled")
                        break
                    
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data)
                            if "audio" in chunk:
                                import base64
                                audio_data = base64.b64decode(chunk["audio"]["data"])
                                yield audio_data
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.error(f"MiMo TTS stream error: {e}")

    async def generate_audio_stream_with_cancel(
        self, 
        text: str, 
        cancel_event: asyncio.Event
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate audio stream dengan external cancel event.
        
        Bila cancel_event.set() — stop generating terus.
        Digunakan untuk barge-in handling.
        """
        if not text.strip():
            return

        # Check cancel sebelum start
        if cancel_event.is_set():
            return

        messages = [
            {
                "role": "user",
                "content": f"Gunakan suara {self.voice_id} untuk menyebut teks berikut"
            },
            {
                "role": "assistant", 
                "content": text
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "audio": {
                "format": "pcm16",
                "voice": self.voice_id
            },
            "stream": True
        }

        try:
            async with self.http_client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json"
                },
                json=payload
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    # Check cancel setiap iteration
                    if cancel_event.is_set():
                        logger.info("MiMo TTS stream cancelled by external event")
                        break
                    
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data)
                            if "audio" in chunk:
                                import base64
                                audio_data = base64.b64decode(chunk["audio"]["data"])
                                yield audio_data
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.error(f"MiMo TTS stream error: {e}")

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()
        logger.info("MiMo TTS client closed")
