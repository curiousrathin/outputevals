from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core import secrets
from app.core.llm import check_key

router = APIRouter(prefix="/api/settings", tags=["settings"])


class AnthropicStatus(BaseModel):
    configured: bool
    source: secrets.KeySource
    masked_key: str | None
    model: str


class KeyCheckResult(BaseModel):
    ok: bool
    message: str
    model: str | None = None
    model_display_name: str | None = None
    context_window: int | None = None


class SaveKeyRequest(BaseModel):
    api_key: str


def _status() -> AnthropicStatus:
    key, source = secrets.get_anthropic_key()
    return AnthropicStatus(
        configured=key is not None,
        source=source,
        masked_key=secrets.mask(key) if key else None,
        model=settings.llm_model,
    )


@router.get("/anthropic", response_model=AnthropicStatus)
def get_anthropic_status():
    return _status()


@router.put("/anthropic", response_model=KeyCheckResult)
def save_anthropic_key(body: SaveKeyRequest):
    key = body.api_key.strip()
    if not key.startswith("sk-ant-"):
        raise HTTPException(422, "Anthropic API keys start with 'sk-ant-'.")
    result = check_key(key)
    if result.ok:  # only persist keys that actually work
        secrets.save_anthropic_key(key)
    return KeyCheckResult(**vars(result))


@router.post("/anthropic/test", response_model=KeyCheckResult)
def test_anthropic_key():
    return KeyCheckResult(**vars(check_key()))


@router.delete("/anthropic", response_model=AnthropicStatus)
def delete_anthropic_key():
    secrets.delete_anthropic_key()
    return _status()
