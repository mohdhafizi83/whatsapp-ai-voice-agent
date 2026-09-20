#!/bin/bash
# Voice agent wrapper - loads .env then runs the phone agent
cd /home/fizi/projects/voice-agent || exit 1
source .venv/bin/activate
set -a
source .env
set +a
export PYTHONUNBUFFERED=1
exec python3 -u voice_agent_phone.py
