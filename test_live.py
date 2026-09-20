#!/usr/bin/env python3
"""Test Gemini Live API response handling."""
import asyncio, logging
from google import genai
from google.genai import types

logging.basicConfig(level=logging.DEBUG, format="%(message)s")
log = logging.getLogger("test")

async def main():
    client = genai.Client(http_options={"api_version": "v1alpha"})
    config = {
        "response_modalities": ["AUDIO"],
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": "Charon"}
            }
        }
    }
    
    log.info("Connecting...")
    async with client.aio.live.connect(
        model="gemini-3.1-flash-live-preview",
        config=config,
    ) as session:
        log.info("Sending text...")
        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text="Count 1,2,3")]
            ),
            turn_complete=True
        )
        
        async for resp in session.receive():
            sc = resp.server_content
            if sc:
                log.info(f"server_content: mt={bool(sc.model_turn)} tc={sc.turn_complete} intr={sc.interrupted}")
                if sc.model_turn:
                    for part in sc.model_turn.parts:
                        log.info(f"  part: inline={bool(part.inline_data)} text={bool(part.text)}")
                        if part.inline_data:
                            log.info(f"    data={len(part.inline_data.data)}B")
            if sc and sc.turn_complete:
                log.info("TURN COMPLETE")
                break
    
    log.info("Done")

asyncio.run(main())
