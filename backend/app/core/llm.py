from dataclasses import dataclass

import anthropic

from app.config import settings
from app.core.secrets import get_anthropic_key


class MissingAPIKeyError(RuntimeError):
    pass


def get_client(api_key: str | None = None) -> anthropic.Anthropic:
    key = api_key or get_anthropic_key()[0]
    if not key:
        raise MissingAPIKeyError("No Anthropic API key configured. Add one in Settings.")
    return anthropic.Anthropic(api_key=key)


@dataclass
class KeyCheck:
    ok: bool
    message: str
    model: str | None = None
    model_display_name: str | None = None
    context_window: int | None = None


def check_key(api_key: str | None = None, model: str | None = None) -> KeyCheck:
    """Validate a key via the Models API: costs no tokens and confirms model access."""
    model = model or settings.llm_model
    try:
        info = get_client(api_key).models.retrieve(model)
    except MissingAPIKeyError as e:
        return KeyCheck(False, str(e))
    except anthropic.AuthenticationError:
        return KeyCheck(False, "Invalid API key.")
    except anthropic.PermissionDeniedError:
        return KeyCheck(False, "This key doesn't have permission to use the API.")
    except anthropic.NotFoundError:
        return KeyCheck(False, f"Key is valid but has no access to {model}.")
    except anthropic.RateLimitError:
        return KeyCheck(False, "Rate limited while checking the key. Try again shortly.")
    except anthropic.APIStatusError as e:
        return KeyCheck(False, f"Anthropic API error ({e.status_code}): {e.type or 'unknown'}.")
    except anthropic.APIConnectionError:
        return KeyCheck(False, "Couldn't reach the Anthropic API. Check your network.")
    return KeyCheck(
        True,
        f"Connected. {info.display_name} is available.",
        model=info.id,
        model_display_name=info.display_name,
        context_window=info.max_input_tokens,
    )
