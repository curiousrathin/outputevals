"""Local secret storage for API keys.

Lookup order: ANTHROPIC_API_KEY in the project .env file (re-read on every
call, so edits apply without a restart), then the process environment, then a
key saved from the Settings page (data/secrets.json, chmod 600). Keys never
leave the backend: the API only ever returns a masked form.
"""

import json
import os
from typing import Literal

from dotenv import dotenv_values

from app.config import ROOT, settings

KeySource = Literal["dotenv", "env", "saved", "none"]
PLACEHOLDER = "sk-ant-your-key-here"


def _path():
    return settings.data_dir / "secrets.json"


def _load() -> dict[str, str]:
    try:
        return json.loads(_path().read_text())
    except FileNotFoundError:
        return {}


def _write(data: dict[str, str]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def _real(key: str | None) -> str | None:
    key = (key or "").strip()
    return key if key and key != PLACEHOLDER else None


def get_anthropic_key() -> tuple[str | None, KeySource]:
    if key := _real(dotenv_values(ROOT / ".env").get("ANTHROPIC_API_KEY")):
        return key, "dotenv"
    if key := _real(os.environ.get("ANTHROPIC_API_KEY")):
        return key, "env"
    if key := _real(_load().get("anthropic_api_key")):
        return key, "saved"
    return None, "none"


def save_anthropic_key(key: str) -> None:
    _write({**_load(), "anthropic_api_key": key})


def delete_anthropic_key() -> None:
    data = _load()
    data.pop("anthropic_api_key", None)
    _write(data)


def mask(key: str) -> str:
    return f"{key[:10]}…{key[-4:]}" if len(key) > 16 else "…"
