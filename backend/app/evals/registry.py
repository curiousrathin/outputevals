"""Scorer registry: every eval declares what it measures and what it needs.

Each eval, for each run, ends in one of four states:

  scored          it ran; `value` is set, and `passed` too when the eval gives a verdict
  locked          it applies, but something it needs doesn't exist yet; shown with how to unlock it
  not_applicable  it can never apply to this run; hidden in tables
  not_computed    it should have run but couldn't; shown with the reason

Only `scored` results count toward averages, so a missing number is never a zero.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

State = Literal["scored", "locked", "not_applicable", "not_computed"]
Level = Literal["response", "trial"]
# verdict: pass/fail · measure: a quantity (seconds, dollars) · signal: 0/1 that's neither good nor bad
Kind = Literal["verdict", "measure", "signal"]


@dataclass
class Result:
    state: State
    value: float | None = None
    passed: bool | None = None
    reason: str = ""
    details: dict = field(default_factory=dict)


def scored(value: float, passed: bool | None = None, reason: str = "", **details) -> Result:
    return Result("scored", float(value), passed, reason, details)


def not_applicable(reason: str) -> Result:
    return Result("not_applicable", reason=reason)


def not_computed(reason: str) -> Result:
    return Result("not_computed", reason=reason)


# What would unlock an eval that needs something the run doesn't have yet.
UNLOCK_HINTS = {
    "golden": "Set the correct answer for this question",
    "repeats": "Ask this question again",
    "pinned": "Pin a batch to compare against",
}


@dataclass(frozen=True)
class Scorer:
    name: str
    title: str
    family: str
    level: Level
    kind: Kind
    version: int
    measures: str  # what it measures
    how: str  # how it decides
    caveat: str  # when it's wrong or misleading
    fn: Callable
    unit: str = ""
    requires: tuple[str, ...] = ()

    def info(self) -> dict:
        return {k: getattr(self, k) for k in ("name", "title", "family", "level", "kind", "version", "measures", "how", "caveat", "unit", "requires")}


REGISTRY: dict[str, Scorer] = {}


def scorer(**meta) -> Callable:
    """Register a scoring function: @scorer(name=..., title=..., ...)."""

    def register(fn: Callable) -> Callable:
        s = Scorer(fn=fn, **meta)
        if s.name in REGISTRY:
            raise ValueError(f"Scorer {s.name!r} is already registered.")
        REGISTRY[s.name] = s
        return fn

    return register


def run_scorer(s: Scorer, ctx, provided: set[str]) -> Result:
    """Apply eligibility, then the scorer. A scorer that crashes is `not_computed`, never a zero."""
    missing = [r for r in s.requires if r not in provided]
    if missing:
        return Result("locked", reason=" · ".join(UNLOCK_HINTS.get(r, f"Needs {r}") for r in missing))
    try:
        result = s.fn(ctx)
    except Exception as e:  # noqa: BLE001 - a broken scorer must not break a run
        return not_computed(f"The scorer failed: {type(e).__name__}: {e}")
    if not isinstance(result, Result):
        return not_computed(f"The scorer returned {type(result).__name__}, not a Result.")
    return result
