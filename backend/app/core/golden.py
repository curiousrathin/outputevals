"""Golden cases: questions with verified answers, and how runs get matched to them.

Matching is exact on purpose: a run is graded against a case only when its
question matches the case after normalizing case, spacing and trailing
punctuation, or when someone links it explicitly. Similar-but-different
questions ("…in July" vs "…in June") must never be graded against each other.
"""

import re

from sqlmodel import Session, select

from app.core.evidence import current_value
from app.core.resolver import REF_PATTERN
from app.evals.numbers import canonical, unsourced_numbers
from app.models import ArmResponse, Configuration, Dataset, Experiment, GoldenCase, Score, Trial

# Bare (unquoted) words that look like column names but are usually SQL.
_SQL_WORDS = {"date", "time", "year", "month", "day", "count", "sum", "min", "max", "avg", "total", "data", "value", "name"}
_AGGREGATE = re.compile(r"\b(sum|count|avg|min|max|group\s+by)\b", re.IGNORECASE)


def question_key(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().casefold()).rstrip("?.!: ")


def columns_used(sql: str, columns: list[str]) -> list[str]:
    """Dataset columns a query mentions: quoted ("Untaxed Total") or, for simple names, bare (amount)."""
    low = sql.casefold()
    used = []
    for col in columns:
        c = col.casefold()
        quoted = f'"{c}"' in low
        bare = (
            re.fullmatch(r"[a-z_][a-z0-9_]*", c) is not None
            and c not in _SQL_WORDS
            and re.search(rf"(?<![\w\"]){re.escape(c)}(?![\w\"])", low) is not None
        )
        if quoted or bare:
            used.append(col)
    return used


def dataset_for(session: Session, trial: Trial) -> Dataset | None:
    exp = session.get(Experiment, trial.experiment_id)
    config = session.get(Configuration, exp.configuration_id) if exp else None
    return session.get(Dataset, config.dataset_id) if config else None


def cited_values(session: Session, r: ArmResponse) -> list[str]:
    """Values the answer cites, in the order it cites them."""
    known = {c["ev_id"]: c["value"] for call in r.tool_calls or [] for c in call.get("evidence", [])}
    out = []
    for ref in dict.fromkeys(REF_PATTERN.findall(r.output or "")):
        try:
            out.append(known.get(ref) or current_value(session, ref))
        except KeyError:
            continue
    return out


def draft_from_run(session: Session, trial: Trial, arm: str) -> dict:
    """Pre-fill a golden case from one arm's run. Everything here is a guess for a person to check."""
    r = session.exec(select(ArmResponse).where(ArmResponse.trial_id == trial.id, ArmResponse.arm == arm)).first()
    dataset = dataset_for(session, trial)
    columns = [c["name"] for c in dataset.columns] if dataset else []
    if r is None:
        return {"question": trial.question, "dataset_columns": columns}
    good = [c["sql"] for c in r.tool_calls or [] if not c.get("error")]
    values = cited_values(session, r) if r.render_ok is not False else []
    typed = unsourced_numbers(r.output or "", trial.question, []) if not values else []
    answerable = bool(values or typed)
    used = [c for c in columns if any(c in columns_used(sql, columns) for sql in good)]
    sql = good[-1] if good else ""
    category = "unanswerable" if not answerable else "aggregation" if _AGGREGATE.search(sql) else "lookup"
    return {
        "question": trial.question,
        "answerable": answerable,
        "expected_values": values or [t["number"] for t in typed],
        "tolerance": 0.001,
        "expected_columns": used,
        "reference_sql": sql,
        "category": category,
        "source_arm": arm,
        "dataset_columns": columns,
    }


def match(session: Session, dataset_id: str, question: str) -> GoldenCase | None:
    return session.exec(
        select(GoldenCase).where(GoldenCase.dataset_id == dataset_id, GoldenCase.question_key == question_key(question))
    ).first()


def _trials_on_dataset(session: Session, dataset_id: str) -> list[Trial]:
    configs = session.exec(select(Configuration.id).where(Configuration.dataset_id == dataset_id)).all()
    exps = session.exec(select(Experiment.id).where(Experiment.configuration_id.in_(configs))).all() if configs else []
    return list(session.exec(select(Trial).where(Trial.experiment_id.in_(exps))).all()) if exps else []


def relink(session: Session, case: GoldenCase, extra_trial_id: str = "") -> list[Trial]:
    """Point every run of this question at the case; unlink runs that no longer match.
    Returns every trial whose link changed or that is linked, so their scores can be redone."""
    touched = []
    for t in _trials_on_dataset(session, case.dataset_id):
        should = question_key(t.question) == case.question_key or t.id in (extra_trial_id, case.created_from_trial_id)
        if should:
            if t.golden_case_id != case.id:
                t.golden_case_id = case.id
                session.add(t)
            touched.append(t)
        elif t.golden_case_id == case.id:
            t.golden_case_id = ""
            session.add(t)
            touched.append(t)
    return touched


def unlink_all(session: Session, case: GoldenCase) -> list[Trial]:
    trials = list(session.exec(select(Trial).where(Trial.golden_case_id == case.id)).all())
    for t in trials:
        t.golden_case_id = ""
        session.add(t)
    return trials


def clear_scores(session: Session, trial_ids: list[str], scorer_names: set[str]) -> None:
    """Drop results that depend on a golden case so they're recomputed against the current one."""
    if not trial_ids or not scorer_names:
        return
    for s in session.exec(select(Score).where(Score.trial_id.in_(trial_ids), Score.scorer.in_(scorer_names))).all():
        session.delete(s)


def numeric(value: str) -> bool:
    return canonical(value) is not None
