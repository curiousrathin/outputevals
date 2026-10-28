"""Fail-closed draft resolver, ported from OutputTracker.

Finds every {{ev:*}} reference in a draft, checks they all resolve, and only
then substitutes values. One missing reference and nothing renders: a draft
with one invented number is more dangerous than one that obviously refused.
"""

import re
from dataclasses import dataclass, field

from sqlmodel import Session

from app.core.evidence import current_value

REF_PATTERN = re.compile(r"\{\{(ev:[0-9a-f]+)\}\}")


@dataclass
class RenderResult:
    ok: bool
    text: str | None
    missing: list[str] = field(default_factory=list)


class DraftResolver:
    def __init__(self, session: Session):
        self.session = session

    def extract_refs(self, draft: str) -> list[str]:
        return REF_PATTERN.findall(draft)

    def validate(self, draft: str) -> list[str]:
        missing = []
        for ref in dict.fromkeys(self.extract_refs(draft)):
            try:
                current_value(self.session, ref)
            except KeyError:
                missing.append(ref)
        return missing

    def render(self, draft: str) -> RenderResult:
        missing = self.validate(draft)
        if missing:
            return RenderResult(ok=False, text=None, missing=missing)
        text = REF_PATTERN.sub(lambda m: current_value(self.session, m.group(1)), draft)
        return RenderResult(ok=True, text=text)
