# Contributing

Thanks for helping improve the Voice Agent!

## Development setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env
export VOICE_AGENT_DISABLE_ENGINE=1   # API-only: no Bluetooth/audio needed
pytest tests/ -q
```

The test suite is fully offline — no API keys, no audio hardware, no network.

## Conventions

- Keep the admin API fail-closed: any new endpoint must require `ADMIN_API_KEY`
  and be added to `tests/test_security.py`.
- Web UI assets must stay self-hosted (no CDN). Design tokens live in the
  Fixzy product-standards (`design-tokens.md`): dark-first, Inter, 8px radius.
- One-off experiments and hardware probes go in `examples/`, not the app root.
- Run `bandit -r app.py voice_agent_phone.py bluetooth_audio.py` before pushing.

## Pull requests

- Branch from `main`, keep commits focused, update `CHANGELOG.md` under
  `[Unreleased]`.
- CI runs pytest, bandit, pip-audit, and gitleaks on every push — keep it green.
