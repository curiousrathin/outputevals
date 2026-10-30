"""Batches (eval step 3): ask the golden set N times per arm, then report accuracy with
error bars, pass^k, pass@k and consistency."""

from datetime import datetime
from statistics import mean

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.configurations import get_configuration
from app.api.datasets import get_dataset
from app.config import settings
from app.core import batches, runner
from app.core.llm import MissingAPIKeyError, get_client
from app.db import SessionDep
from app.evals.service import current_scores
from app.evals.stats import batch_report
from app.models import ArmResponse, Batch, Experiment, GoldenCase, Score, Trial

router = APIRouter(prefix="/api", tags=["batches"])

MAX_REPEATS = 20


class BatchIn(BaseModel):
    repeats: int = 5
    golden_case_ids: list[str] | None = None  # None: every golden question on the dataset


class BatchOut(BaseModel):
    id: str
    experiment_id: str
    golden_case_ids: list[str]
    repeats: int
    total: int
    done: int
    status: str
    error: str
    config_version: str
    model: str
    settings: dict
    created_at: datetime
    finished_at: datetime | None


def _experiment(session: Session, experiment_id: str) -> Experiment:
    e = session.get(Experiment, experiment_id)
    if not e:
        raise HTTPException(404, "Experiment not found.")
    return e


def _batch(session: Session, batch_id: str) -> Batch:
    b = session.get(Batch, batch_id)
    if not b:
        raise HTTPException(404, "Batch not found.")
    return b


def _cases(session: Session, dataset_id: str, ids: list[str] | None) -> list[GoldenCase]:
    all_cases = list(session.exec(select(GoldenCase).where(GoldenCase.dataset_id == dataset_id).order_by(GoldenCase.created_at)).all())
    if ids is None:
        return all_cases
    by_id = {c.id: c for c in all_cases}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise HTTPException(422, f"Not golden questions on this dataset: {', '.join(unknown)}.")
    return [by_id[i] for i in dict.fromkeys(ids)]


def _check_size(questions: int, repeats: int) -> None:
    if not 1 <= repeats <= MAX_REPEATS:
        raise HTTPException(422, f"Repeats must be between 1 and {MAX_REPEATS}.")
    if questions == 0:
        raise HTTPException(422, "There are no golden questions to run. Set a correct answer on the Evals tab first.")
    if questions * repeats > settings.batch_max_runs:
        raise HTTPException(
            422, f"{questions} questions × {repeats} repeats is {questions * repeats} runs; the limit is "
            f"{settings.batch_max_runs} (OT_BATCH_MAX_RUNS).",
        )


@router.get("/experiments/{experiment_id}/batches", response_model=list[BatchOut])
def list_batches(experiment_id: str, session: SessionDep):
    _experiment(session, experiment_id)
    return session.exec(select(Batch).where(Batch.experiment_id == experiment_id).order_by(Batch.created_at.desc())).all()


@router.get("/experiments/{experiment_id}/batches/estimate")
def estimate(experiment_id: str, session: SessionDep, repeats: int = 5, cases: str | None = None) -> dict:
    """What a batch would cost, from the average cost and time of this experiment's earlier runs."""
    e = _experiment(session, experiment_id)
    config = get_configuration(session, e.configuration_id)
    chosen = _cases(session, config.dataset_id, cases.split(",") if cases else None)
    runs = len(chosen) * repeats
    trial_ids = list(session.exec(select(Trial.id).where(Trial.experiment_id == e.id)).all())
    per_arm: dict[str, list[float]] = {"baseline": [], "configured": []}
    for scores in current_scores(session, trial_ids).values():
        for s in scores:
            if s.scorer == "cost" and s.state == "scored" and s.value is not None and s.arm in per_arm:
                per_arm[s.arm].append(s.value)
    latencies = [
        r.latency_ms for r in session.exec(select(ArmResponse).where(ArmResponse.trial_id.in_(trial_ids))).all() if r.latency_ms
    ] if trial_ids else []
    cost = sum(mean(v) for v in per_arm.values() if v) * runs if all(per_arm.values()) else None
    waves = -(-runs // max(1, settings.batch_concurrency))  # ceiling division
    return {
        "questions": len(chosen),
        "repeats": repeats,
        "runs": runs,
        "model_calls_at_least": runs * 2,
        "est_cost_usd": cost,
        "est_minutes": waves * mean(latencies) / 60000 if latencies else None,
        "based_on_runs": len(trial_ids),
        "max_runs": settings.batch_max_runs,
        "max_repeats": MAX_REPEATS,
        "concurrency": settings.batch_concurrency,
    }


@router.post("/experiments/{experiment_id}/batches", response_model=BatchOut)
def start_batch(experiment_id: str, body: BatchIn, session: SessionDep):
    e = _experiment(session, experiment_id)
    if session.exec(select(Batch).where(Batch.experiment_id == e.id, Batch.status == "running")).first():
        raise HTTPException(409, "A batch is already running for this experiment. Wait for it, or cancel it.")
    config = get_configuration(session, e.configuration_id)
    dataset = get_dataset(session, config.dataset_id)
    chosen = _cases(session, dataset.id, body.golden_case_ids)
    _check_size(len(chosen), body.repeats)
    try:
        setup = runner.prepare(e, config, dataset)
    except runner.RunError as err:
        raise HTTPException(422, str(err)) from err
    try:
        client = get_client()
    except MissingAPIKeyError as err:
        raise HTTPException(400, str(err)) from err

    batch = Batch(
        experiment_id=e.id,
        golden_case_ids=[c.id for c in chosen],
        repeats=body.repeats,
        total=len(chosen) * body.repeats,
        config_version=setup.config_version,
        model=settings.llm_model,
        settings={"effort": settings.llm_effort, "concurrency": settings.batch_concurrency},
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    batches.start(session.get_bind(), batch, setup, client, [c.question for c in chosen])
    return batch


@router.get("/batches/{batch_id}")
def read_batch(batch_id: str, session: SessionDep) -> dict:
    b = _batch(session, batch_id)
    return {"batch": BatchOut.model_validate(b, from_attributes=True), "report": batch_report(session, b)}


@router.post("/batches/{batch_id}/cancel", response_model=BatchOut)
def cancel_batch(batch_id: str, session: SessionDep):
    b = _batch(session, batch_id)
    if b.status != "running":
        raise HTTPException(409, f"This batch isn't running (it's {b.status}).")
    batches.cancel(b.id)
    if not batches.is_running(b.id):  # left over from a previous server process
        b.status = "interrupted"
        session.add(b)
        session.commit()
        session.refresh(b)
    return b


@router.delete("/batches/{batch_id}", status_code=204)
def delete_batch(batch_id: str, session: SessionDep):
    """Removes the batch and every run in it."""
    b = _batch(session, batch_id)
    if batches.is_running(b.id):
        raise HTTPException(409, "Cancel the batch before deleting it.")
    with runner.WRITE_LOCK:
        for t in session.exec(select(Trial).where(Trial.batch_id == b.id)).all():
            for r in session.exec(select(ArmResponse).where(ArmResponse.trial_id == t.id)).all():
                session.delete(r)
            for s in session.exec(select(Score).where(Score.trial_id == t.id)).all():
                session.delete(s)
            session.delete(t)
        session.delete(b)
        session.commit()
