"""
Gemini Live API Client

Menguruskan WebSocket connection ke Gemini Live API.
Guna google-genai SDK untuk audio-to-audio (Mode 1) atau audio-to-text (Mode 2).

Mode 1 (sales):   Audio → Gemini → Audio (native, low latency, barge-in native)
Mode 2 (interview): Audio → Gemini → Text → MiMo TTS (dengan barge-in handling)
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional

from google import genai
from google.genai import types as genai_types

import config

logger = logging.getLogger("voice-agent.gemini")


class GeminiLiveClient:
    """
    Wrapper untuk Gemini Live API.
    
    Mode 1 (sales):   Audio → Gemini → Audio (native, low latency)
    Mode 2 (interview): Audio → Gemini → Text → MiMo TTS
    """

    def __init__(self):
        self.client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options={"api_version": config.GEMINI_API_VERSION},
        )
        self.session: Optional[genai_types.LiveClientSession] = None
        self._mode = config.ACTIVE_MODE
        self._interrupt_event = asyncio.Event()
        self._connected = False

    def _get_config(self) -> dict:
        """Generate session config based on current mode."""
        if self._mode == "interview":
            return {
                "response_modalities": ["TEXT"],
            }
        else:
            return {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": config.GEMINI_VOICE_NAME,
                        }
                    }
                },
            }

    async def connect(self, system_prompt: str):
        """Open WebSocket session ke Gemini Live API."""
        logger.info(f"Connecting to Gemini Live API (mode={self._mode})...")
        live_config = self._get_config()

        # Setup system instruction
        if system_prompt:
            live_config["system_instruction"] = genai_types.Content(
                parts=[genai_types.Part(text=system_prompt)]
            )

        # Using async context manager for the live session
        cm = self.client.aio.live.connect(
            model=config.GEMINI_MODEL,
            config=live_config,
        )
        self._cm = cm  # store for cleanup
        self.session = await cm.__aenter__()
        self._connected = True
        logger.info("Gemini Live API session connected")

    async def close(self):
        """Close the Gemini session."""
        if self.session and hasattr(self, '_cm') and self._cm:
            await self._cm.__aexit__(None, None, None)
            self.session = None
            self._cm = None
            self._connected = False
            logger.info("Gemini session closed")

    async def send_audio(self, audio_chunk: bytes):
        """Send audio as a complete turn to Gemini, triggering a response."""
        if not self.session:
            raise RuntimeError("Session not connected. Call connect() first.")
        
        self._interrupt_event.clear()
        
        # Use send_client_content with turn_complete=True so Gemini knows
        # the user finished speaking and should respond.
        await self.session.send_client_content(
            turns=genai_types.Content(
                role="user",
                parts=[genai_types.Part(
                    inline_data=genai_types.Blob(
                        data=audio_chunk,
                        mime_type="audio/pcm;rate=16000",
                    )
                )]
            ),
            turn_complete=True,
        )

    async def receive(self) -> AsyncGenerator[bytes, None]:
        """Receive audio/text responses from Gemini.

        Mode 1: Yields raw PCM audio bytes
        Mode 2: Yields text chunks
        """
        if not self.session:
            raise RuntimeError("Session not connected.")

        async for response in self.session.receive():
            log_prefix = f"Gemini recv: type={type(response).__name__}"
            logger.debug(f"{log_prefix} full={str(response)[:200]}")
            
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if self._mode == "interview":
                        if part.text:
                            logger.debug(f"{log_prefix} text={part.text[:50]}")
                            yield part.text.encode()
                    else:
                        if part.inline_data and part.inline_data.data:
                            data = part.inline_data.data
                            logger.debug(f"{log_prefix} audio={len(data)} bytes")
                            yield data
                        elif part.text:
                            logger.debug(f"{log_prefix} text(no audio): {part.text[:50]}")
            
            # Log other response types for debugging
            elif response.server_content:
                if response.server_content.turn_complete:
                    logger.debug(f"{log_prefix} turn_complete")
                elif response.server_content.interrupted:
                    logger.debug(f"{log_prefix} interrupted")

    async def receive_with_interrupt(self) -> AsyncGenerator[bytes, None]:
        """
        Receive responses dengan interrupt detection (Mode 2).
        
        Bila caller interrupt (hantar audio baru), Gemini akan hantar
        TURN_COMPLETE atau INTERRUPT event. Kita detect ni dan yield
        signal ke caller untuk stop MiMo TTS.
        """
        if not self.session:
            raise RuntimeError("Session not connected.")

        async for response in self.session.receive():
            # Check for interrupt signal
            if response.server_content:
                # Turn complete — Gemini dah selesai generate
                if response.server_content.turn_complete:
                    logger.info("Gemini turn complete")
                    yield b"__TURN_COMPLETE__"
                    continue
                
                # Interrupt detected — caller potong cakap
                if response.server_content.interrupted:
                    logger.info("Gemini interrupt detected!")
                    self._interrupt_event.set()
                    yield b"__INTERRUPT__"
                    continue

            # Normal text/audio response
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.text:
                        yield part.text.encode()

    async def wait_for_interrupt(self, timeout: float = 0.5) -> bool:
        """Wait for interrupt signal dari Gemini."""
        try:
            await asyncio.wait_for(self._interrupt_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def clear_interrupt(self):
        """Clear interrupt flag."""
        self._interrupt_event.clear()

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value not in ("sales", "interview"):
            raise ValueError("Mode must be 'sales' or 'interview'")
        self._mode = value
