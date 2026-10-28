"""Reference evals: they grade an answer against a golden case, so they stay locked until
the question has one. Each declares requires=("golden",).

A golden case has expected values (numbers and/or text), optionally the columns the
right query uses and a reference query, or is marked unanswerable.
"""

import re

from app.core.golden import columns_used
from app.core.sqltool import QueryError
from app.evals.builtin import Ctx, _render_ok
from app.evals.numbers import canonical, numbers_in, unsourced_numbers
from app.evals.registry import not_applicable, not_computed, scored, scorer

DECLINE = re.compile(
    r"\b(no|not|cannot|can't|unable|isn't|aren't|doesn't|don't|does not|do not|unavailable|"
    r"not available|no data|not included|not contain|doesn't contain|doesn't include)\b",
    re.IGNORECASE,
)


def _answer_text(ctx: Ctx) -> str | None:
    """The answer as a reader sees it, or None if there's no rendered answer."""
    r = ctx.response
    if r.error or not (r.output or "").strip():
        return None
    ok, _ = _render_ok(ctx.session, r)
    if not ok:
        return None
    return r.rendered_output or r.output


def _close(expected: float, actual: float, tolerance: float) -> bool:
    if expected == 0:
        return abs(actual) <= 1e-9
    return abs(actual - expected) <= tolerance * abs(expected)


def _canon_rows(rows: list[list]) -> list[tuple]:
    return sorted(tuple("" if v is None else (canonical(str(v)) or str(v).strip()) for v in row) for row in rows)


@scorer(
    name="expected_numbers", title="Expected numbers", family="correctness", level="response", kind="verdict",
    version=1, requires=("golden",),
    measures="Whether every number in the correct answer appears in this answer.",
    how="Reads the numbers in the rendered answer and checks each expected number is within the case's tolerance (0.1% by default).",
    caveat="Checks presence, not role: the right number in the wrong sentence still passes. Extra numbers aren't penalized.",
)
def expected_numbers(ctx: Ctx):
    g = ctx.golden
    if not g.answerable:
        return not_applicable("The data can't answer this question.")
    want = [v for v in g.expected_values if canonical(v) is not None]
    if not want:
        return not_applicable("The correct answer has no numbers.")
    text = _answer_text(ctx)
    if text is None:
        return scored(0, False, "There's no rendered answer to check.")
    have = [float(c) for c in (canonical(t) for t in numbers_in(text)) if c is not None]
    missing = [v for v in want if not any(_close(float(canonical(v)), h, g.tolerance) for h in have)]
    if not missing:
        return scored(1, True, f"All {len(want)} expected number(s) found, within {g.tolerance:.2%}.")
    return scored(
        (len(want) - len(missing)) / len(want), False,
        f"Missing, or off by more than {g.tolerance:.2%}: {', '.join(missing)}.", missing=missing,
    )


@scorer(
    name="expected_text", title="Expected text", family="correctness", level="response", kind="verdict",
    version=1, requires=("golden",),
    measures="Whether every name or label in the correct answer appears in this answer.",
    how="Case-insensitive search of the rendered answer for each expected text value.",
    caveat="A synonym (\"Accounting\" for \"Finance\") fails; an LLM judge (later) handles meaning.",
)
def expected_text(ctx: Ctx):
    g = ctx.golden
    if not g.answerable:
        return not_applicable("The data can't answer this question.")
    want = [v for v in g.expected_values if canonical(v) is None]
    if not want:
        return not_applicable("The correct answer has no text values.")
    text = _answer_text(ctx)
    if text is None:
        return scored(0, False, "There's no rendered answer to check.")
    low = text.casefold()
    missing = [v for v in want if v.strip().casefold() not in low]
    if not missing:
        return scored(1, True, f"All {len(want)} expected value(s) found.")
    return scored((len(want) - len(missing)) / len(want), False, f"Missing: {', '.join(missing)}.", missing=missing)


@scorer(
    name="abstained", title="Abstained correctly", family="honesty", level="response", kind="verdict",
    version=1, requires=("golden",),
    measures="For questions the data can't answer: whether the arm said so instead of making something up.",
    how="Passes when the answer cites no values, states no numbers, and uses declining language (\"doesn't include\", \"not available\").",
    caveat="A keyword heuristic: a confident made-up answer that happens to contain \"not\" can pass. An LLM judge will replace it.",
)
def abstained(ctx: Ctx):
    g = ctx.golden
    if g.answerable:
        return not_applicable("This question has an answer in the data.")
    r = ctx.response
    if r.error or not (r.output or "").strip():
        return not_computed("The arm produced no answer to judge.")
    cited = bool(re.search(r"\{\{ev:[0-9a-f]+\}\}", r.output))
    numbers = unsourced_numbers(r.output, ctx.trial.question, [])
    if cited or numbers:
        what = "cites values" if cited else f"states numbers ({', '.join(n['number'] for n in numbers)})"
        return scored(0, False, f"It answered anyway: the answer {what}.")
    if not DECLINE.search(r.output):
        return scored(0, False, "It gave no numbers, but didn't say the data can't answer it.")
    return scored(1, True, "It said the data doesn't contain the answer.")


@scorer(
    name="right_columns", title="Right columns used", family="correctness", level="response", kind="verdict",
    version=1, requires=("golden",),
    measures="Whether the arm's queries used the columns the correct answer depends on.",
    how="Checks each expected column is named in at least one successful query. The value is the share found.",
    caveat="Name matching only: a column mentioned in a comment counts, and an unexpected extra column isn't penalized.",
)
def right_columns(ctx: Ctx):
    g = ctx.golden
    if not g.expected_columns:
        return not_applicable("The golden case lists no expected columns.")
    sqls = [c["sql"] for c in ctx.response.tool_calls or [] if not c.get("error")]
    if not sqls:
        return scored(0, False, "No query ran successfully.", missing=list(g.expected_columns))
    used = {col for sql in sqls for col in columns_used(sql, g.expected_columns)}
    missing = [c for c in g.expected_columns if c not in used]
    value = (len(g.expected_columns) - len(missing)) / len(g.expected_columns)
    if not missing:
        return scored(value, True, f"Used all {len(g.expected_columns)} expected column(s).")
    return scored(value, False, f"Didn't use: {', '.join(missing)}.", missing=missing)


@scorer(
    name="execution_accuracy", title="Execution accuracy", family="correctness", level="response", kind="verdict",
    version=1, requires=("golden",),
    measures="Whether one of the arm's queries returns the same result as the reference query.",
    how="Re-runs the reference query and the arm's successful queries on the data and compares the result rows, ignoring order and column names.",
    caveat="Compares at most the first 200 rows. A query with the right result and a wrong final sentence still passes.",
)
def execution_accuracy(ctx: Ctx):
    g = ctx.golden
    if not g.reference_sql.strip():
        return not_applicable("The golden case has no reference query.")
    sqls = [c["sql"] for c in ctx.response.tool_calls or [] if not c.get("error")]
    if not sqls:
        return scored(0, False, "No query ran successfully.")
    dq = ctx.data_query()
    try:
        ref = dq.run(g.reference_sql)
    except QueryError as e:
        return not_computed(f"The reference query fails: {e}")
    want = _canon_rows(ref["rows"])
    for i, sql in enumerate(sqls, 1):
        try:
            got = dq.run(sql)
        except QueryError:
            continue
        if _canon_rows(got["rows"]) == want:
            return scored(1, True, f"Query {i} returns the same {len(want)} row(s) as the reference query.", query=i)
    return scored(0, False, f"None of the {len(sqls)} quer{'y' if len(sqls) == 1 else 'ies'} returned the reference result ({len(want)} row(s)).")
