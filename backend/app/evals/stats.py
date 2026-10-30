"""Statistics across repeated runs: accuracy with error bars, pass^k, pass@k and consistency.

Batches ask each golden question k times per arm. Repeats of one question are not
independent (an easy question is right every time), so intervals come from a two-level
bootstrap: resample questions, then resample runs within each question. That widens the
interval when there are few questions, which is the honest answer.

Everything here is computed from stored scores, so it costs no model calls.
"""

import hashlib
from collections import defaultdict
from statistics import mean, median

import numpy as np
from sqlmodel import Session, select

from app.evals.builtin import _cited_values
from app.evals.registry import REGISTRY
from app.evals.service import current_scores
from app.models import ArmResponse, Batch, GoldenCase, Score, Trial

ARMS = ("baseline", "configured")
RESAMPLES = 2000
LEVEL = 0.95


def _rng(seed: str) -> np.random.Generator:
    """Seeded by the batch, so the same results always give the same interval."""
    return np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))


def _interval(samples: np.ndarray) -> tuple[float, float]:
    tail = (1 - LEVEL) / 2 * 100
    lo, hi = np.percentile(samples, [tail, 100 - tail])
    return float(lo), float(hi)


def _resample(groups: list[list[bool]], idx: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Mean of per-question pass rates for each bootstrap draw. idx: (draws, questions)."""
    n = np.array([len(g) for g in groups])
    p = np.array([sum(g) / len(g) for g in groups])
    inner = rng.binomial(n[idx], p[idx]) / n[idx]  # resample the runs within each picked question
    return inner.mean(axis=1)


def rate(groups: list[list[bool]], rng: np.random.Generator) -> dict | None:
    """Pass rate averaged over questions (each question counts once), with a 95% interval.
    groups: one list of pass/fail results per question."""
    groups = [g for g in groups if g]
    if not groups:
        return None
    point = mean(sum(g) / len(g) for g in groups)
    runs = sum(len(g) for g in groups)
    out = {"mean": point, "lo": None, "hi": None, "questions": len(groups), "runs": runs}
    if runs >= 2:
        idx = rng.integers(0, len(groups), size=(RESAMPLES, len(groups)))
        out["lo"], out["hi"] = _interval(_resample(groups, idx, rng))
    return out


def paired_difference(pairs: list[tuple[list[bool], list[bool]]], rng: np.random.Generator) -> dict | None:
    """Configured minus baseline, paired by question: both arms are resampled on the same questions."""
    pairs = [(a, b) for a, b in pairs if a and b]
    if not pairs:
        return None
    base, conf = [a for a, _ in pairs], [b for _, b in pairs]
    point = mean(sum(b) / len(b) - sum(a) / len(a) for a, b in pairs)
    out = {"mean": point, "lo": None, "hi": None, "questions": len(pairs)}
    if sum(len(a) + len(b) for a, b in pairs) >= 4:
        idx = rng.integers(0, len(pairs), size=(RESAMPLES, len(pairs)))
        out["lo"], out["hi"] = _interval(_resample(conf, idx, rng) - _resample(base, idx, rng))
    return out


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def _answer_key(session: Session, r: ArmResponse | None) -> str:
    """What the run answered, for consistency: the values it cited, or a marker for no answer."""
    if r is None:
        return "∅ no response"
    values = _cited_values(session, r)
    if values is None:
        return "∅ no rendered answer"
    return " · ".join(sorted(values)) if values else "(cites nothing)"


def batch_report(session: Session, batch: Batch) -> dict:
    trials = list(session.exec(select(Trial).where(Trial.batch_id == batch.id).order_by(Trial.repeat, Trial.created_at)).all())
    scores = current_scores(session, [t.id for t in trials])
    responses: dict[str, dict[str, ArmResponse]] = defaultdict(dict)
    if trials:
        for r in session.exec(select(ArmResponse).where(ArmResponse.trial_id.in_([t.id for t in trials]))).all():
            responses[r.trial_id][r.arm] = r
    cases = {c.id: c for c in session.exec(select(GoldenCase).where(GoldenCase.id.in_(batch.golden_case_ids))).all()}
    rng = _rng(batch.id)

    def score(t: Trial, arm: str, name: str) -> Score | None:
        return next((s for s in scores[t.id] if s.arm == arm and s.scorer == name), None)

    # Per question: each run's verdict and what it answered.
    by_case: dict[str, list[Trial]] = defaultdict(list)
    for t in trials:
        by_case[t.golden_case_id].append(t)
    rows = []
    for case_id in batch.golden_case_ids:
        case = cases.get(case_id)
        row = {
            "golden_case_id": case_id,
            "question": case.question if case else "(golden answer deleted)",
            "category": case.category if case else "",
            "held_out": case.held_out if case else False,
            "arms": {},
        }
        for arm in ARMS:
            runs = []
            for t in by_case.get(case_id, []):
                s = score(t, arm, "correct")
                runs.append({
                    "trial_id": t.id, "repeat": t.repeat,
                    "correct": s.passed if s and s.state == "scored" else None,
                    "reason": s.reason if s else "Not scored yet.",
                    "answer": _answer_key(session, responses[t.id].get(arm)),
                })
            judged = [r["correct"] for r in runs if r["correct"] is not None]
            answers = [r["answer"] for r in runs]
            top = max((answers.count(a) for a in set(answers)), default=0)
            row["arms"][arm] = {
                "runs": runs,
                "judged": len(judged),
                "passed": sum(judged),
                "distinct_answers": len(set(answers)),
                "same_answer_share": top / len(answers) if answers else None,
            }
        rows.append(row)

    def groups(arm: str, name: str = "correct") -> list[list[bool]]:
        out = []
        for case_id in batch.golden_case_ids:
            g = []
            for t in by_case.get(case_id, []):
                s = score(t, arm, name)
                if s and s.state == "scored" and s.passed is not None:
                    g.append(bool(s.passed))
            out.append(g)
        return out

    arms = {}
    for arm in ARMS:
        correct = [g for g in groups(arm) if g]
        repeated = [r["arms"][arm] for r in rows if len(r["arms"][arm]["runs"]) >= 2]
        arm_responses = [responses[t.id][arm] for t in trials if arm in responses[t.id]]
        latencies = [r.latency_ms / 1000 for r in arm_responses if r.latency_ms]
        costs = [s.value for t in trials if (s := score(t, arm, "cost")) and s.state == "scored" and s.value is not None]
        arms[arm] = {
            "accuracy": rate(correct, rng),
            # pass^k: right on every run · pass@k: right at least once
            "pass_all": {"count": sum(all(g) for g in correct), "of": len(correct)},
            "pass_any": {"count": sum(any(g) for g in correct), "of": len(correct)},
            "consistent": {"count": sum(r["distinct_answers"] == 1 for r in repeated), "of": len(repeated)},
            "errors": sum(1 for r in arm_responses if r.error),
            "latency": {"p50": median(latencies), "p95": _percentile(latencies, 95)} if latencies else None,
            "cost": {"total": sum(costs), "per_run": mean(costs)} if costs else None,
        }

    evals = []
    for s in REGISTRY.values():
        if s.kind != "verdict" or s.level != "response":
            continue
        for arm in ARMS:
            r = rate(groups(arm, s.name), rng)
            if r:
                evals.append({"scorer": s.name, "arm": arm, **r})

    return {
        "repeats": batch.repeats,
        "runs_done": len(trials),
        "arms": arms,
        "difference": paired_difference(list(zip(groups("baseline"), groups("configured"), strict=True)), rng),
        "questions": rows,
        "evals": evals,
    }
