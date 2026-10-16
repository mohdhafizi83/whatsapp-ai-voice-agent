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

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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
        self._bt = None
        self.monitor = PhoneCallMonitor()
        self.gemini = GeminiLiveClient()
        self.tts = MiMoTTSClient()
        self.call_logger = CallLogger()
        self.knowledge = KnowledgeBase()
        self.running = False

    @property
    def bt(self) -> BluetoothAudioBridge:
        """Lazily open the audio bridge so API-only use needs no sound card."""
        if self._bt is None:
            self._bt = BluetoothAudioBridge()
        return self._bt

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
_engine: "VoiceAgentEngine | None" = None


def get_engine() -> VoiceAgentEngine:
    """Lazily construct the engine (audio hardware not needed for API-only use)."""
    global _engine
    if _engine is None:
        _engine = VoiceAgentEngine()
    return _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start voice agent engine in background.

    Set VOICE_AGENT_DISABLE_ENGINE=1 to serve the API without the call
    loop (tests/CI or API-only deployments — no audio hardware needed).
    """
    import asyncio as _asyncio
    task = None
    if os.getenv("VOICE_AGENT_DISABLE_ENGINE", "") == "1":
        logger.warning("Engine loop disabled via VOICE_AGENT_DISABLE_ENGINE=1")
    else:
        try:
            task = _asyncio.create_task(get_engine().run())
        except Exception:
            logger.exception("Engine failed to start — API-only mode")
    yield
    if _engine is not None:
        _engine.running = False
    if task is not None:
        task.cancel()

fastapi_app = FastAPI(
    title="Voice Agent",
    version="2.1.0",
    lifespan=lifespan,
)

# ─── Security hardening ───────────────────────────────────────────
MAX_BODY_BYTES = 1_048_576  # 1 MB request body cap

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

# Applied instead of the JSON CSP on HTML documents (the /admin panel).
# Everything is self-hosted under 'self' — no CDN, no inline scripts/styles.
UI_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "font-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'"
)


class BodyLimitMiddleware:
    """Reject oversized request bodies (413).

    Content-Length is checked up front; chunked bodies without
    Content-Length are truncated at the cap so handlers see an
    incomplete body (→ 4xx validation) instead of unbounded memory.
    """

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = None
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    content_length = int(value)
                except ValueError:
                    content_length = None
        if content_length is not None and content_length > self.max_bytes:
            response = JSONResponse({"error": "request body too large"}, status_code=413)
            await response(scope, receive, send)
            return
        if content_length is None and scope.get("method") in ("POST", "PUT", "PATCH"):
            state = {"count": 0}

            async def limited_receive():
                message = await receive()
                if message["type"] == "http.request":
                    state["count"] += len(message.get("body", b""))
                    if state["count"] > self.max_bytes:
                        return {"type": "http.request", "body": b"", "more_body": False}
                return message

            await self.app(scope, limited_receive, send)
            return
        await self.app(scope, receive, send)


# Added first so the security-headers middleware below wraps it (413s get headers too).
fastapi_app.add_middleware(BodyLimitMiddleware)


@fastapi_app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Apply hardening headers to every HTTP response."""
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Content-Security-Policy"] = UI_CSP
    return response


@fastapi_app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """Generic 500 — full traceback goes to server logs, never to the client."""
    logger.exception("Unhandled error while processing request")
    return JSONResponse(
        status_code=500,
        content={"error": "internal server error"},
        headers=SECURITY_HEADERS,
    )


@fastapi_app.get("/")
async def root():
    return {
        "status": "running",
        "mode": config.ACTIVE_MODE,
        "bluetooth": check_bluetooth_connection(),
        "adb": get_engine().monitor.check_adb_connection(),
    }


# ─── Admin web UI (self-hosted assets, no CDN) ──────────────────
fastapi_app.mount(
    "/assets",
    StaticFiles(directory=config.BASE_DIR / "assets"),
    name="assets",
)


@fastapi_app.get("/admin", include_in_schema=False)
async def admin_ui():
    """Single-page admin panel: status, mode switch, captured leads."""
    return FileResponse(
        config.TEMPLATES_DIR / "admin.html", media_type="text/html"
    )


# ─── Admin API auth (set ADMIN_API_KEY env var; fail closed) ────
import hmac as _hmac
import time as _time
from urllib.parse import parse_qs as _parse_qs

from pydantic import BaseModel, field_validator
from pydantic import ValidationError as _ValidationError

_admin_buckets: dict = {}

def _key_matches(provided: str, expected: str) -> bool:
    """Constant-time compare; encode to bytes so non-ASCII input can't raise."""
    try:
        return _hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
    except TypeError:  # pragma: no cover - defensive
        return False


def _require_admin(x_api_key: str | None = Header(default=None)):
    """Require X-API-Key header matching ADMIN_API_KEY. Fail closed."""
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=501, detail="ADMIN_API_KEY not configured")
    if not x_api_key or not _key_matches(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")

def _ws_api_key(scope) -> str:
    params = _parse_qs(scope.get("query_string", b"").decode("utf-8", "replace"))
    return (params.get("api_key") or [""])[0]


class WebSocketAuthGuard:
    """Reject every WebSocket upgrade without a valid ``?api_key=`` query param.

    The app exposes no WebSocket endpoints today; this guard is defense-in-depth
    so no future ``/ws`` route can ever be reachable unauthenticated.
    Auth choice: query-parameter ``api_key`` (browser WebSocket clients cannot
    set custom headers). Fail closed: ADMIN_API_KEY unset => all upgrades
    rejected (close code 1011); wrong key => 1008 policy violation.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            expected = os.getenv("ADMIN_API_KEY", "")
            provided = _ws_api_key(scope)
            if not expected:
                await send({"type": "websocket.close", "code": 1011,
                            "reason": "ADMIN_API_KEY not configured"})
                return
            if not _key_matches(provided, expected):
                await send({"type": "websocket.close", "code": 1008,
                            "reason": "unauthorized"})
                return
        await self.app(scope, receive, send)


fastapi_app.add_middleware(WebSocketAuthGuard)


def _rate_limit(request: Request, limit: int = 30, window: int = 60):
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    hits = [t for t in _admin_buckets.get(ip, []) if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    hits.append(now)
    _admin_buckets[ip] = hits


# ─── Lead capture input hygiene ───────────────────────────────────
_LEAD_LIMITS = {"name": 120, "phone": 32, "company": 120, "interest": 48, "notes": 2000}


class LeadIn(BaseModel):
    """Validated lead payload: control chars stripped, hard length caps."""

    name: str
    phone: str
    company: str = ""
    interest: str = ""
    notes: str = ""

    @field_validator("name", "phone", "company", "interest", "notes")
    @classmethod
    def _sanitize(cls, value: str, info) -> str:
        # Strip all control chars (incl. DEL); keep printable text only.
        value = "".join(ch for ch in value if 32 <= ord(ch) < 127)
        if len(value) > _LEAD_LIMITS[info.field_name]:
            raise ValueError(f"{info.field_name} too long")
        return value

    @field_validator("name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name required")
        return value.strip()

    @field_validator("phone")
    @classmethod
    def _phone_charset(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("phone required")
        if not all(ch.isdigit() or ch in "+-() .x" for ch in value):
            raise ValueError("phone contains invalid characters")
        return value.strip()


@fastapi_app.get("/api/leads")
async def get_leads(request: Request, x_api_key: str | None = Header(default=None)):
    _rate_limit(request)
    _require_admin(x_api_key)
    return {"leads": get_engine().call_logger.get_leads()}


@fastapi_app.post("/api/leads", status_code=201)
async def create_lead(request: Request, x_api_key: str | None = Header(default=None)):
    """Capture a lead. Auth is checked BEFORE body parsing; errors are generic."""
    _rate_limit(request)
    _require_admin(x_api_key)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid lead payload")
    try:
        lead = LeadIn.model_validate(body)
    except _ValidationError:
        raise HTTPException(status_code=422, detail="invalid lead payload")
    lead_id = get_engine().call_logger.save_lead(
        lead.name, lead.phone, lead.company, lead.interest, lead.notes
    )
    return {"id": lead_id}


@fastapi_app.post("/api/mode")
async def set_mode(request: Request, mode: str, x_api_key: str | None = Header(default=None)):
    _rate_limit(request)
    _require_admin(x_api_key)
    if mode not in ("sales", "interview"):
        raise HTTPException(status_code=400, detail="mode must be 'sales' or 'interview'")
    config.ACTIVE_MODE = mode
    get_engine().gemini.mode = mode
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
