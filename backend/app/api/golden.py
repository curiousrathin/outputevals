from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.core import golden
from app.db import SessionDep
from app.evals.service import golden_dependent
from app.models import Dataset, GoldenCase, Trial, utcnow

router = APIRouter(prefix="/api", tags=["golden"])


class GoldenIn(BaseModel):
    question: str
    answerable: bool = True
    expected_values: list[str] = []
    tolerance: float = 0.001
    expected_columns: list[str] = []
    reference_sql: str = ""
    category: Literal["", "lookup", "aggregation", "multi-hop", "unanswerable"] = ""
    held_out: bool = False
    notes: str = ""
    # Creating from a run: the trial it came from (its dataset is used).
    trial_id: str = ""
    dataset_id: str = ""


class GoldenOut(BaseModel):
    id: str
    dataset_id: str
    dataset_sha: str
    question: str
    answerable: bool
    expected_values: list[str]
    tolerance: float
    expected_columns: list[str]
    reference_sql: str
    category: str
    held_out: bool
    notes: str
    version: int
    created_from_trial_id: str
    linked_runs: int
    created_at: datetime
    updated_at: datetime


def _out(session: Session, case: GoldenCase) -> GoldenOut:
    n = session.exec(select(func.count()).select_from(Trial).where(Trial.golden_case_id == case.id)).one()
    return GoldenOut(**case.model_dump(exclude={"workflow_id", "question_key", "params"}), linked_runs=n)


def _get(session: Session, case_id: str) -> GoldenCase:
    case = session.get(GoldenCase, case_id)
    if not case:
        raise HTTPException(404, "Golden case not found.")
    return case


def _validate(session: Session, body: GoldenIn, dataset: Dataset, case_id: str = "") -> None:
    if not body.question.strip():
        raise HTTPException(422, "Write the question.")
    values = [v for v in body.expected_values if v.strip()]
    if body.answerable and not values:
        raise HTTPException(422, "Add at least one expected value, or mark the question as unanswerable.")
    columns = {c["name"] for c in dataset.columns}
    unknown = [c for c in body.expected_columns if c not in columns]
    if unknown:
        raise HTTPException(422, f"Not columns in this dataset: {', '.join(unknown)}.")
    if not 0 <= body.tolerance <= 0.5:
        raise HTTPException(422, "Tolerance must be between 0 and 0.5 (50%).")
    dup = golden.match(session, dataset.id, body.question)
    if dup and dup.id != case_id:
        raise HTTPException(409, f"This question already has a golden case ({dup.id}). Edit that one instead.")


def _apply(case: GoldenCase, body: GoldenIn) -> None:
    case.question = body.question.strip()
    case.question_key = golden.question_key(body.question)
    case.answerable = body.answerable
    case.expected_values = [v.strip() for v in body.expected_values if v.strip()] if body.answerable else []
    case.tolerance = body.tolerance
    case.expected_columns = body.expected_columns
    case.reference_sql = body.reference_sql.strip()
    case.category = "unanswerable" if not body.answerable else ("" if body.category == "unanswerable" else body.category)
    case.held_out = body.held_out
    case.notes = body.notes


def _rescore(session: Session, trials: list[Trial]) -> None:
    golden.clear_scores(session, [t.id for t in trials], golden_dependent())


@router.get("/datasets/{dataset_id}/golden", response_model=list[GoldenOut])
def list_golden(dataset_id: str, session: SessionDep):
    cases = session.exec(select(GoldenCase).where(GoldenCase.dataset_id == dataset_id).order_by(GoldenCase.created_at)).all()
    return [_out(session, c) for c in cases]


@router.get("/trials/{trial_id}/golden-draft")
def golden_draft(trial_id: str, session: SessionDep, arm: Literal["baseline", "configured"] = "configured") -> dict:
    """A pre-filled golden case from one arm's run: values it cited, columns its SQL used,
    its last successful query. Everything is a suggestion to check against the data."""
    trial = session.get(Trial, trial_id)
    if not trial:
        raise HTTPException(404, "Trial not found.")
    return golden.draft_from_run(session, trial, arm)


@router.post("/golden", response_model=GoldenOut)
def create_golden(body: GoldenIn, session: SessionDep):
    trial = session.get(Trial, body.trial_id) if body.trial_id else None
    if body.trial_id and not trial:
        raise HTTPException(404, "Trial not found.")
    dataset = golden.dataset_for(session, trial) if trial else session.get(Dataset, body.dataset_id)
    if not dataset:
        raise HTTPException(422, "Say which dataset this golden case is for.")
    _validate(session, body, dataset)
    case = GoldenCase(dataset_id=dataset.id, dataset_sha=dataset.sha256, question="", question_key="",
                      created_from_trial_id=trial.id if trial else "")
    _apply(case, body)
    session.add(case)
    session.flush()
    _rescore(session, golden.relink(session, case, extra_trial_id=trial.id if trial else ""))
    session.commit()
    session.refresh(case)
    return _out(session, case)


@router.put("/golden/{case_id}", response_model=GoldenOut)
def update_golden(case_id: str, body: GoldenIn, session: SessionDep):
    case = _get(session, case_id)
    dataset = session.get(Dataset, case.dataset_id)
    _validate(session, body, dataset, case_id=case.id)
    before = golden.unlink_all(session, case)
    _apply(case, body)
    case.version += 1
    case.updated_at = utcnow()
    session.add(case)
    session.flush()
    after = golden.relink(session, case)
    _rescore(session, before + after)
    session.commit()
    session.refresh(case)
    return _out(session, case)


@router.delete("/golden/{case_id}", status_code=204)
def delete_golden(case_id: str, session: SessionDep):
    case = _get(session, case_id)
    _rescore(session, golden.unlink_all(session, case))
    session.delete(case)
    session.commit()
