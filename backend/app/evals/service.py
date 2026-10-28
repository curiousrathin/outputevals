"""Running evals: score each run as it happens, and backfill runs from before an eval existed.

Scores are stored per scorer version, so `ensure_scores` only computes what's
missing: a new trial, a newly added eval, or a bumped scorer version. Code evals
read only the stored trace, so backfilling costs nothing.
"""

from collections import defaultdict
from statistics import mean

from sqlmodel import Session, select

from app.core import datasets as ds
from app.core.golden import dataset_for
from app.core.sqltool import DataQuery
from app.evals import builtin, reference  # noqa: F401  (register the evals)
from app.evals.builtin import Ctx
from app.evals.registry import REGISTRY, run_scorer
from app.models import ArmResponse, GoldenCase, Score, Trial

STATES = ("scored", "locked", "not_applicable", "not_computed")


def provided(trial: Trial, golden: GoldenCase | None) -> set[str]:
    """What a run can offer evals that need more than its own trace.
    Repeated questions and pinned batches come in later steps; until then those evals stay locked."""
    return {"golden"} if golden else set()


def golden_dependent() -> set[str]:
    """Evals whose results change when a golden case is set, edited or removed."""
    return {name for name, s in REGISTRY.items() if "golden" in s.requires}


class _Datasets:
    """Load each dataset into DuckDB at most once per scoring pass, and only if an eval needs it."""

    def __init__(self):
        self._open: dict[str, DataQuery] = {}

    def loader(self, dataset_id: str):
        def load() -> DataQuery:
            if dataset_id not in self._open:
                self._open[dataset_id] = DataQuery(ds.dataset_path(dataset_id))
            return self._open[dataset_id]

        return load

    def close(self) -> None:
        for q in self._open.values():
            q.close()
        self._open.clear()


def _is_current(s: Score) -> bool:
    reg = REGISTRY.get(s.scorer)
    return reg is not None and reg.version == s.scorer_version


def _responses(session: Session, trial_ids: list[str]) -> dict[str, list[ArmResponse]]:
    out: dict[str, list[ArmResponse]] = defaultdict(list)
    for r in session.exec(select(ArmResponse).where(ArmResponse.trial_id.in_(trial_ids))).all():
        out[r.trial_id].append(r)
    return out


def ensure_scores(session: Session, trials: list[Trial]) -> None:
    """Compute every missing (trial, arm, eval, version) score and save it."""
    if not trials:
        return
    ids = [t.id for t in trials]
    have = {
        (s.trial_id, s.response_id, s.scorer, s.scorer_version)
        for s in session.exec(select(Score).where(Score.trial_id.in_(ids))).all()
    }
    responses = _responses(session, ids)
    data = _Datasets()
    added = False
    try:
        for t in trials:
            by_arm = {r.arm: r for r in responses[t.id]}
            golden = session.get(GoldenCase, t.golden_case_id) if t.golden_case_id else None
            dataset = None
            caps = provided(t, golden)
            for s in REGISTRY.values():
                targets = responses[t.id] if s.level == "response" else [None]
                for r in targets:
                    rid = r.id if r else ""
                    if (t.id, rid, s.name, s.version) in have:
                        continue
                    if dataset is None:
                        dataset = dataset_for(session, t)
                    ctx = Ctx(session, t, by_arm, r, golden, dataset, data.loader(dataset.id) if dataset else None)
                    res = run_scorer(s, ctx, caps)
                    details = {**res.details, "golden_version": golden.version} if golden and "golden" in s.requires else res.details
                    session.add(Score(
                        trial_id=t.id, response_id=rid, arm=r.arm if r else "",
                        scorer=s.name, scorer_version=s.version, state=res.state,
                        value=res.value, passed=res.passed, reason=res.reason, details=details,
                    ))
                    added = True
    finally:
        data.close()
    if added:
        session.commit()


def current_scores(session: Session, trial_ids: list[str]) -> dict[str, list[Score]]:
    out: dict[str, list[Score]] = defaultdict(list)
    if not trial_ids:
        return out
    for s in session.exec(select(Score).where(Score.trial_id.in_(trial_ids))).all():
        if _is_current(s):
            out[s.trial_id].append(s)
    return out


def rescore(session: Session, trials: list[Trial]) -> None:
    """Recompute current-version scores, e.g. after changing a scorer without bumping its version.
    Older versions' rows are kept."""
    for s in session.exec(select(Score).where(Score.trial_id.in_([t.id for t in trials]))).all():
        if _is_current(s):
            session.delete(s)
    session.commit()
    ensure_scores(session, trials)


def scorecard(session: Session, trials: list[Trial]) -> list[dict]:
    """One row per eval and arm. Only `scored` results count toward pass rates and averages."""
    scores = current_scores(session, [t.id for t in trials])
    flat = [s for t in trials for s in scores[t.id]]
    rows = []
    for s in REGISTRY.values():
        for arm in (["baseline", "configured"] if s.level == "response" else [""]):
            items = [x for x in flat if x.scorer == s.name and x.arm == arm]
            done = [x for x in items if x.state == "scored"]
            values = [x.value for x in done if x.value is not None]
            judged = [x for x in done if x.passed is not None]
            reasons = sorted({x.reason for x in items if x.state == "not_computed"})
            rows.append({
                "scorer": s.name, "arm": arm, "total": len(items),
                **{state: sum(1 for x in items if x.state == state) for state in STATES},
                "judged": len(judged), "passed": sum(1 for x in judged if x.passed),
                "mean": mean(values) if values else None, "sum": sum(values) if values else None,
                "not_computed_reasons": reasons[:3],
            })
    return rows
