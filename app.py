"""
Voice Agent — Main Server

Mode 1 (sales):    Audio → Gemini Live (native audio) → Audio back
Mode 2 (interview): Audio → Gemini Live (text) → MiMo TTS → Audio back
                    dengan barge-in handling (caller boleh interrupt)

Usage:
  python app.py                    # Start in sales mode
  AGENT_MODE=interview python app.py  # Start in interview mode
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

import config
from bluetooth_audio import BluetoothAudioBridge, PhoneCallMonitor, find_bluetooth_audio_device, check_bluetooth_connection
from call_logger import CallLogger
from gemini_client import GeminiLiveClient
from elevenlabs_client import MiMoTTSClient
from knowledge_base import KnowledgeBase

# ─── Logging Setup ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("voice-agent")


# ─── Audio Conversion ─────────────────────────────────────────────
def resample_8k_to_16k(audio_8k: bytes) -> bytes:
    """Convert 8kHz PCM to 16kHz PCM via simple linear interpolation."""
    import struct
    samples = struct.unpack(f"<{len(audio_8k)//2}h", audio_8k)
    # Linear interpolation
    upsampled = []
    for i, s in enumerate(samples):
        upsampled.append(s)
        if i < len(samples) - 1:
            # Interpolate midpoint
            mid = (s + samples[i + 1]) // 2
            upsampled.append(mid)
    return struct.pack(f"<{len(upsampled)}h", *upsampled)

def resample_16k_to_8k(audio_16k: bytes) -> bytes:
    """Convert 16kHz PCM to 8kHz PCM via simple downsampling."""
    import struct
    samples = struct.unpack(f"<{len(audio_16k)//2}h", audio_16k)
    # Downsample by taking every other sample
    downsampled = samples[::2]
    return struct.pack(f"<{len(downsampled)}h", *downsampled)


# ─── Voice Agent Engine ───────────────────────────────────────────
class VoiceAgentEngine:
    """Core voice agent — runs the continuous call loop."""

    def __init__(self):
        self.bt = BluetoothAudioBridge()
        self.monitor = PhoneCallMonitor()
        self.gemini = GeminiLiveClient()
        self.tts = MiMoTTSClient()
        self.call_logger = CallLogger()
        self.knowledge = KnowledgeBase()
        self.running = False

    def get_system_prompt(self, mode: str, caller: str = "") -> str:
        """Load system prompt for current mode."""
        template_dir = config.TEMPLATES_DIR
        file_map = {
            "sales": template_dir / "system_prompt_sales.md",
            "interview": template_dir / "system_prompt_interview.md",
        }
        filepath = file_map.get(mode, file_map["sales"])
        if filepath.exists():
            prompt = filepath.read_text()
        else:
            prompt = "Anda adalah AI assistant yang membantu caller."
        prompt = prompt.replace("{caller_number}", caller)
        prompt = prompt.replace("{agent_name}", "Hafizi")
        return prompt

    # ─── Mode 1: Gemini Live Audio (Native Barge-in) ──────────────
    async def handle_call_mode1(self, call_id: int = 0):
        """
        Mode 1 (Sales): Gemini Live API — native audio.
        Barge-in built-in — tak perlu handling tambahan.
        """
        logger.info("Mode 1: Gemini Live Audio (Sales)")
        
        system_prompt = self.get_system_prompt("sales")
        await self.gemini.connect(system_prompt)

        input_stream = self.bt.open_input_stream(
            rate=config.AUDIO_RATE_BT,
            channels=config.AUDIO_CHANNELS,
            chunk=3200
        )
        output_stream = self.bt.open_output_stream(
            rate=config.AUDIO_RATE_BT,
            channels=config.AUDIO_CHANNELS,
            chunk=3200
        )

        try:
            call_start = time.time()

            async def capture_and_send():
                """Capture Bluetooth audio, resample, send to Gemini."""
                while True:
                    try:
                        data = input_stream.read(1600, exception_on_overflow=False)
                        # Resample 8kHz → 16kHz for Gemini
                        pcm_16k = resample_8k_to_16k(data)
                        await self.gemini.send_audio(pcm_16k)
                    except Exception as e:
                        logger.error(f"Capture error: {e}")
                        break

                    if not self.monitor.check_active_call():
                        logger.info("Call ended")
                        break

            async def receive_and_play():
                """Receive audio from Gemini, play to Bluetooth."""
                try:
                    async for audio_chunk in self.gemini.receive():
                        pcm_8k = resample_16k_to_8k(audio_chunk)
                        output_stream.write(pcm_8k)
                except Exception as e:
                    logger.error(f"Output error: {e}")

            # Run both — barge-in native via Gemini Live
            await asyncio.gather(capture_and_send(), receive_and_play())

        except Exception as e:
            logger.error(f"Call error: {e}")
        finally:
            input_stream.stop_stream()
            input_stream.close()
            output_stream.stop_stream()
            output_stream.close()
            await self.gemini.close()
            duration = int(time.time() - call_start)
            if call_id:
                self.call_logger.end_call(call_id, duration)
            logger.info(f"Call ended: duration={duration}s")

    # ─── Mode 2: Gemini Text → MiMo TTS (Dengan Barge-in) ────────
    async def handle_call_mode2(self, call_id: int = 0):
        """
        Mode 2 (Interview): Gemini text → MiMo TTS → Audio.
        Dengan barge-in handling — caller boleh interrupt MiMo TTS.
        """
        logger.info("Mode 2: Gemini → MiMo TTS (Interview) — dengan barge-in")

        # System prompt dengan knowledge base
        system_prompt = self.get_system_prompt("interview")
        kb_context = self.knowledge.query("about hafizi")
        if kb_context:
            system_prompt += f"\n\n--- Maklumat Peribadi ---\n{kb_context}"

        await self.gemini.connect(system_prompt)
        await self.tts.connect(voice_name="Hafizi")

        input_stream = self.bt.open_input_stream(
            rate=config.AUDIO_RATE_BT,
            channels=config.AUDIO_CHANNELS,
            chunk=3200
        )
        output_stream = self.bt.open_output_stream(
            rate=config.AUDIO_RATE_BT,
            channels=config.AUDIO_CHANNELS,
            chunk=3200
        )

        # Shared cancel event untuk barge-in
        cancel_event = asyncio.Event()

        try:
            call_start = time.time()
            text_buffer = ""

            async def capture_and_send():
                """Capture Bluetooth audio, send to Gemini.
                
                Bila caller start cakap, Gemini akan detect interrupt
                dan hantar signal ke receive_and_play().
                """
                while True:
                    try:
                        data = input_stream.read(1600, exception_on_overflow=False)
                        pcm_16k = resample_8k_to_16k(data)
                        
                        # Hantar audio ke Gemini
                        await self.gemini.send_audio(pcm_16k)
                        
                        # Reset cancel bila caller cakap
                        cancel_event.clear()
                        self.tts.clear_cancel()
                        
                    except Exception as e:
                        logger.error(f"Capture error: {e}")
                        break

                    if not self.monitor.check_active_call():
                        logger.info("Call ended")
                        break

            async def receive_and_play():
                """Receive text from Gemini, generate audio via MiMo TTS.
                
                dengan barge-in handling:
                - Gemini detect interrupt → hantar __INTERRUPT__ signal
                - Server stop MiMo TTS terus
                - Gemini generate jawapan baru
                """
                nonlocal text_buffer
                try:
                    async for chunk in self.gemini.receive_with_interrupt():
                        # Check for control signals
                        if chunk == b"__INTERRUPT__":
                            logger.info("⚡ Barge-in detected! Stopping MiMo TTS...")
                            cancel_event.set()
                            self.tts.cancel()
                            text_buffer = ""  # Clear buffer
                            continue
                        
                        if chunk == b"__TURN_COMPLETE__":
                            logger.info("Gemini turn complete")
                            # Flush remaining text
                            if text_buffer.strip():
                                async for audio in self.tts.generate_audio_stream_with_cancel(
                                    text_buffer, cancel_event
                                ):
                                    if cancel_event.is_set():
                                        break
                                    pcm_8k = resample_16k_to_8k(audio)
                                    output_stream.write(pcm_8k)
                                text_buffer = ""
                            continue
                        
                        # Normal text chunk
                        text = chunk.decode()
                        text_buffer += text
                        
                        # Process dalam chunks kecil untuk responsive barge-in
                        if len(text_buffer) > 30:  # 30 chars per chunk
                            if not cancel_event.is_set():
                                async for audio in self.tts.generate_audio_stream_with_cancel(
                                    text_buffer, cancel_event
                                ):
                                    if cancel_event.is_set():
                                        logger.info("MiMo TTS stopped — barge-in")
                                        break
                                    pcm_8k = resample_16k_to_8k(audio)
                                    output_stream.write(pcm_8k)
                            text_buffer = ""

                except Exception as e:
                    logger.error(f"Output error: {e}")

            # Run both tasks
            await asyncio.gather(capture_and_send(), receive_and_play())

        except Exception as e:
            logger.error(f"Call error: {e}")
        finally:
            cancel_event.set()  # Stop any ongoing TTS
            input_stream.stop_stream()
            input_stream.close()
            output_stream.stop_stream()
            output_stream.close()
            await self.gemini.close()
            await self.tts.close()
            duration = int(time.time() - call_start)
            if call_id:
                self.call_logger.end_call(call_id, duration)
            logger.info(f"Call ended: duration={duration}s")

    # ─── Main Call Handler ────────────────────────────────────────
    async def handle_call(self, call_id: int = 0):
        """Route call to correct mode handler."""
        if config.ACTIVE_MODE == "interview":
            await self.handle_call_mode2(call_id)
        else:
            await self.handle_call_mode1(call_id)

    async def run(self):
        """Main loop — monitor for incoming calls."""
        logger.info("=" * 60)
        logger.info("Voice Agent — Bluetooth HFP Gateway")
        logger.info(f"Mode: {config.ACTIVE_MODE}")
        logger.info("Waiting for incoming calls...")
        logger.info("=" * 60)

        self.running = True

        while self.running:
            try:
                # Check Bluetooth connection
                if not check_bluetooth_connection():
                    logger.warning("Bluetooth not connected. Waiting...")
                    await asyncio.sleep(5)
                    continue

                # Check ADB connection
                if not self.monitor.check_adb_connection():
                    logger.warning("ADB not connected. Waiting...")
                    await asyncio.sleep(5)
                    continue

                # Check for incoming call
                if self.monitor.check_incoming_call():
                    logger.info("Incoming call detected!")
                    self.monitor.answer_call()
                    await asyncio.sleep(1)  # Wait for call to connect

                    # Log call
                    call_id = self.call_logger.start_call(
                        f"call-{int(time.time())}",
                        "incoming",
                        config.ACTIVE_MODE
                    )

                    # Handle the call
                    await self.handle_call(call_id)

                await asyncio.sleep(0.5)  # Poll interval

            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.running = False
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)


# ─── FastAPI Status App ───────────────────────────────────────────
engine = VoiceAgentEngine()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start voice agent engine in background."""
    import asyncio as _asyncio
    task = _asyncio.create_task(engine.run())
    yield
    engine.running = False
    task.cancel()

fastapi_app = FastAPI(
    title="Voice Agent",
    version="2.1.0",
    lifespan=lifespan,
)

@fastapi_app.get("/")
async def root():
    return {
        "status": "running",
        "mode": config.ACTIVE_MODE,
        "bluetooth": check_bluetooth_connection(),
        "adb": engine.monitor.check_adb_connection(),
    }


# ─── Admin API auth (set ADMIN_API_KEY env var; fail closed) ────
import hmac as _hmac
import time as _time
from fastapi import Header, HTTPException, Request

_admin_buckets: dict = {}

def _require_admin(x_api_key: str | None = Header(default=None)):
    """Require X-API-Key header matching ADMIN_API_KEY. Fail closed."""
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=501, detail="ADMIN_API_KEY not configured")
    if not x_api_key or not _hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")

def _rate_limit(request: Request, limit: int = 30, window: int = 60):
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    hits = [t for t in _admin_buckets.get(ip, []) if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    hits.append(now)
    _admin_buckets[ip] = hits


@fastapi_app.get("/api/leads")
async def get_leads(request: Request, x_api_key: str | None = Header(default=None)):
    _rate_limit(request)
    _require_admin(x_api_key)
    return {"leads": engine.call_logger.get_leads()}

@fastapi_app.post("/api/mode")
async def set_mode(request: Request, mode: str, x_api_key: str | None = Header(default=None)):
    _rate_limit(request)
    _require_admin(x_api_key)
    if mode not in ("sales", "interview"):
        raise HTTPException(status_code=400, detail="mode must be 'sales' or 'interview'")
    config.ACTIVE_MODE = mode
    engine.gemini.mode = mode
    return {"mode": mode}


# ─── Main Entry Point ────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:fastapi_app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
    )
