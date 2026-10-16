# Voice Agent — admin API + web UI.
#
# NOTE: the Bluetooth HFP audio path (BlueZ + PulseAudio + ADB) CANNOT run in
# this container — it needs host Bluetooth/audio devices. The image serves the
# FastAPI admin API and the /admin panel only; run the call engine natively
# (see docs/bluetooth-hfp.md). VOICE_AGENT_DISABLE_ENGINE=1 is baked in so the
# container never attempts the hardware call loop.
#
# Templat: product-standards/templates/docker/Dockerfile.python (multi-stage
# variant — pyaudio needs libportaudio at runtime and headers at build time).

FROM python:3.12-slim AS builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends portaudio19-dev gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends libportaudio2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8765 \
    VOICE_AGENT_DISABLE_ENGINE=1

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/', timeout=5).status==200 else 1)"

CMD ["python", "app.py"]
