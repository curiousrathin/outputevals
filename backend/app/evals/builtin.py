"""The always-on evals: they need nothing beyond the run's own trace, so every run gets them.

Each one says what it measures, how it decides, and when it's misleading; the
Evals page shows that text so the scores teach you what they mean.
"""

from collections.abc import Callable

from sqlmodel import Session

from app.core.evidence import current_value
from app.core.resolver import REF_PATTERN, DraftResolver
from app.core.sqltool import DataQuery
from app.evals.numbers import canonical, unsourced_numbers
from app.evals.pricing import cost_usd
from app.evals.registry import not_applicable, not_computed, scored, scorer
from app.models import ArmResponse, Dataset, GoldenCase, Trial


class Ctx:
    """What a scorer can look at: the trial, both arms, (for response-level evals) one arm,
    the golden case the question is graded against, and the dataset."""

    def __init__(
        self,
        session: Session,
        trial: Trial,
        responses: dict[str, ArmResponse],
        response: ArmResponse | None = None,
        golden: GoldenCase | None = None,
        dataset: Dataset | None = None,
        data: Callable[[], DataQuery] | None = None,
    ):
        self.session = session
        self.trial = trial
        self.responses = responses
        self.response = response
        self.golden = golden
        self.dataset = dataset
        self._data = data

    def data_query(self) -> DataQuery:
        """The dataset loaded for re-running queries; shared across evals and loaded at most once."""
        if self._data is None:
            raise RuntimeError("No dataset is available to query.")
        return self._data()


def _evidence_map(r: ArmResponse) -> dict[str, str]:
    return {c["ev_id"]: c["value"] for call in r.tool_calls or [] for c in call.get("evidence", [])}


def _query_values(r: ArmResponse) -> list[str]:
    return [c["value"] for call in r.tool_calls or [] for c in call.get("evidence", [])]


def _render_ok(session: Session, r: ArmResponse) -> tuple[bool, list[str]]:
    """Stored verdict when there is one; older runs are rendered now (read-only)."""
    if r.render_ok is not None:
        return r.render_ok, list(r.missing_refs or [])
    res = DraftResolver(session).render(r.output)
    return res.ok, res.missing


def _cited_values(session: Session, r: ArmResponse) -> set[str] | None:
    """Normalized values the answer cites, or None if it has no resolved answer."""
    if r.error or not r.output.strip() or not _render_ok(session, r)[0]:
        return None
    known = _evidence_map(r)
    values = set()
    for ref in REF_PATTERN.findall(r.output):
        v = known.get(ref) or current_value(session, ref)
        values.add(canonical(v) or v.strip().casefold())
    return values


@scorer(
    name="completed", title="Completed", family="reliability", level="response", kind="verdict", version=1,
    measures="Whether the arm finished with an answer.",
    how="Fails on an API error, a refusal, hitting the token limit, running out of query rounds, or an empty reply.",
    caveat="A completed answer can still be wrong. This only checks that one arrived.",
)
def completed(ctx: Ctx):
    r = ctx.response
    if r.error:
        return scored(0, False, r.error)
    if not r.output.strip():
        return scored(0, False, "The model returned no text.")
    return scored(1, True, "Finished normally.")


@scorer(
    name="refs_resolve", title="References resolve", family="grounding", level="response", kind="verdict", version=1,
    measures="Whether every {{ev:…}} reference in the answer points to stored evidence.",
    how="The fail-closed resolver's verdict: one unknown reference fails the whole answer.",
    caveat="Says nothing about numbers typed without a reference. Unsourced numbers covers those.",
)
def refs_resolve(ctx: Ctx):
    r = ctx.response
    if not r.output.strip():
        return not_applicable("There's no answer to check.")
    refs = set(REF_PATTERN.findall(r.output))
    if not refs:
        return not_applicable("The answer has no references.")
    ok, missing = _render_ok(ctx.session, r)
    if ok:
        return scored(1, True, f"All {len(refs)} reference(s) resolved.", references=len(refs))
    return scored(
        0, False, f"{len(missing)} of {len(refs)} reference(s) don't exist: {', '.join(missing)}.",
        references=len(refs), missing=missing,
    )


@scorer(
    name="unsourced_numbers", title="Unsourced numbers", family="grounding", level="response", kind="verdict", version=1,
    measures="Numbers written straight into the answer instead of cited as evidence.",
    how="Scans the draft outside references, code and list markers, ignoring numbers that appear in the question. Passes at zero.",
    caveat="Can flag harmless numbers (\"top 3\") and misses numbers written as words (\"three\").",
)
def unsourced(ctx: Ctx):
    r = ctx.response
    if not r.output.strip():
        return not_applicable("There's no answer to check.")
    found = unsourced_numbers(r.output, ctx.trial.question, _query_values(r))
    if not found:
        return scored(0, True, "Every number in the answer is cited.", numbers=[])
    typed = [f["number"] for f in found if f["matches_query"]]
    invented = [f["number"] for f in found if not f["matches_query"]]
    parts = []
    if typed:
        parts.append(f"typed instead of cited: {', '.join(typed)}")
    if invented:
        parts.append(f"not in any query result: {', '.join(invented)}")
    return scored(len(found), False, f"{len(found)} unsourced: " + "; ".join(parts) + ".", numbers=found)


@scorer(
    name="sql_health", title="SQL health", family="sql", level="response", kind="verdict", version=1,
    measures="Whether the arm's queries ran, or it fixed the ones that failed.",
    how="Passes when every failed query is followed by a successful one. The value is the share of queries that succeeded.",
    caveat="A query can run perfectly and still compute the wrong thing; execution accuracy (with a golden answer) checks that.",
)
def sql_health(ctx: Ctx):
    calls = ctx.response.tool_calls or []
    if not calls:
        return not_applicable("The arm didn't query the data.")
    failed = [i for i, c in enumerate(calls) if c.get("error")]
    fixed = [i for i in failed if any(not c.get("error") for c in calls[i + 1:])]
    ok = len(calls) - len(failed)
    summary = f"{len(calls)} quer{'y' if len(calls) == 1 else 'ies'}"
    if failed:
        summary += f" · {len(failed)} failed, {len(fixed)} fixed by a later query"
    return scored(
        ok / len(calls), len(fixed) == len(failed), summary + ".",
        queries=len(calls), failed=len(failed), fixed=len(fixed),
        errors=[calls[i]["error"] for i in failed],
    )


@scorer(
    name="arms_agree", title="Arms agree", family="comparison", level="trial", kind="signal", version=1,
    measures="Whether baseline and configured cite the same values.",
    how="Compares the set of values each answer cites (numbers normalized, text case-folded).",
    caveat="Agreement isn't correctness: both arms can agree on a wrong answer. Disagreement marks the questions worth reading.",
)
def arms_agree(ctx: Ctx):
    b, c = ctx.responses.get("baseline"), ctx.responses.get("configured")
    if not b or not c:
        return not_applicable("Needs both arms.")
    vb, vc = _cited_values(ctx.session, b), _cited_values(ctx.session, c)
    if vb is None or vc is None:
        which = "baseline" if vb is None else "configured"
        return not_computed(f"The {which} arm has no resolved answer to compare.")
    if not vb and not vc:
        return not_applicable("Neither answer cites any values.")
    same = vb == vc
    reason = "Both arms cite the same values." if same else "The arms cite different values."
    return scored(1 if same else 0, None, reason, baseline=sorted(vb), configured=sorted(vc))


@scorer(
    name="latency", title="Latency", family="operational", level="response", kind="measure", version=1, unit="s",
    measures="Wall-clock time for the arm, including every query round.",
    how="Measured around the whole tool loop.",
    caveat="Includes network and API queueing, so it varies between identical runs.",
)
def latency(ctx: Ctx):
    ms = ctx.response.latency_ms
    if not ms:
        return not_computed("No timing was recorded.")
    return scored(ms / 1000, None, f"{ms / 1000:.1f} s")


@scorer(
    name="cost", title="Cost", family="operational", level="response", kind="measure", version=1, unit="$",
    measures="What the arm's model calls cost, in USD.",
    how="Token counts times list prices, with cache reads and cache writes priced separately.",
    caveat="List prices only: no discounts, batch or regional rates. Prices change; see evals/pricing.py.",
)
def cost(ctx: Ctx):
    r = ctx.response
    tokens = {
        "input": r.input_tokens, "output": r.output_tokens,
        "cache_read": r.cache_read_tokens, "cache_write": r.cache_creation_tokens,
    }
    usd = cost_usd(r.model, r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_creation_tokens)
    if usd is None:
        return not_computed(f"No price is set for {r.model}. Add one with OT_MODEL_PRICES.")
    total_in = r.input_tokens + r.cache_read_tokens + r.cache_creation_tokens
    return scored(
        usd["total"], None, f"${usd['total']:.4f} · {total_in:,} in ({r.cache_read_tokens:,} cached) · {r.output_tokens:,} out",
        tokens=tokens, usd=usd,
    )
