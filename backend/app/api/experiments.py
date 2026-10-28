from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.api.configurations import get_configuration
from app.api.datasets import get_dataset
from app.core import arena, golden, library, prompts
from app.core import datasets as ds
from app.core.evidence import store_cited
from app.core.llm import MissingAPIKeyError, get_client
from app.core.resolver import DraftResolver
from app.core.sqltool import DataQuery
from app.db import SessionDep
from app.evals.service import current_scores, ensure_scores
from app.models import ArmResponse, Experiment, Score, Trial

router = APIRouter(prefix="/api", tags=["experiments"])


class ExperimentIn(BaseModel):
    name: str
    configuration_id: str
    description: str = ""


class ExperimentOut(BaseModel):
    id: str
    name: str
    description: str
    configuration_id: str
    configuration_name: str
    dataset_id: str
    dataset_name: str
    trial_count: int
    created_at: datetime


class TrialIn(BaseModel):
    question: str


class TrialPatch(BaseModel):
    preference: Literal["baseline", "configured", "tie", "both_bad"] | None = None
    note: str | None = None


class TrialOut(BaseModel):
    id: str
    experiment_id: str
    question: str
    config_version: str
    library_files: list[dict]  # [{path, sha256}] the configured arm saw
    golden_case_id: str  # "" until the question has a golden case
    preference: str | None
    note: str
    created_at: datetime
    responses: list[ArmResponse]
    scores: list[Score]  # current-version evals for both arms and the trial


def _get_experiment(session: Session, experiment_id: str) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if not experiment:
        raise HTTPException(404, "Experiment not found.")
    return experiment


def _experiment_out(session: Session, e: Experiment) -> ExperimentOut:
    config = get_configuration(session, e.configuration_id)
    dataset = get_dataset(session, config.dataset_id)
    count = session.exec(
        select(func.count()).select_from(Trial).where(Trial.experiment_id == e.id)
    ).one()
    return ExperimentOut(
        **e.model_dump(include={"id", "name", "description", "configuration_id", "created_at"}),
        configuration_name=config.name,
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        trial_count=count,
    )


def _trial_out(session: Session, trial: Trial, scores: list[Score] | None = None) -> TrialOut:
    responses = session.exec(select(ArmResponse).where(ArmResponse.trial_id == trial.id)).all()
    order = {"baseline": 0, "configured": 1}
    if scores is None:
        scores = current_scores(session, [trial.id])[trial.id]
    return TrialOut(
        **trial.model_dump(),
        responses=sorted(responses, key=lambda r: order.get(r.arm, 9)),
        scores=scores,
    )


@router.post("/experiments", response_model=ExperimentOut)
def create_experiment(body: ExperimentIn, session: SessionDep):
    get_configuration(session, body.configuration_id)
    experiment = Experiment(
        name=body.name.strip() or "Untitled experiment",
        configuration_id=body.configuration_id,
        description=body.description,
    )
    session.add(experiment)
    session.commit()
    session.refresh(experiment)
    return _experiment_out(session, experiment)


@router.get("/experiments", response_model=list[ExperimentOut])
def list_experiments(session: SessionDep):
    experiments = session.exec(select(Experiment).order_by(Experiment.created_at.desc())).all()
    return [_experiment_out(session, e) for e in experiments]


@router.get("/experiments/{experiment_id}", response_model=ExperimentOut)
def read_experiment(experiment_id: str, session: SessionDep):
    return _experiment_out(session, _get_experiment(session, experiment_id))


@router.delete("/experiments/{experiment_id}", status_code=204)
def delete_experiment(experiment_id: str, session: SessionDep):
    experiment = _get_experiment(session, experiment_id)
    for trial in session.exec(select(Trial).where(Trial.experiment_id == experiment_id)).all():
        for r in session.exec(select(ArmResponse).where(ArmResponse.trial_id == trial.id)).all():
            session.delete(r)
        for s in session.exec(select(Score).where(Score.trial_id == trial.id)).all():
            session.delete(s)
        session.delete(trial)
    session.delete(experiment)
    session.commit()


@router.get("/experiments/{experiment_id}/trials", response_model=list[TrialOut])
def list_trials(experiment_id: str, session: SessionDep):
    _get_experiment(session, experiment_id)
    trials = session.exec(
        select(Trial).where(Trial.experiment_id == experiment_id).order_by(Trial.created_at.desc())
    ).all()
    ensure_scores(session, list(trials))  # backfills runs from before an eval existed
    scores = current_scores(session, [t.id for t in trials])
    return [_trial_out(session, t, scores[t.id]) for t in trials]


@router.post("/experiments/{experiment_id}/trials", response_model=TrialOut)
def run_trial(experiment_id: str, body: TrialIn, session: SessionDep):
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Ask a question.")
    experiment = _get_experiment(session, experiment_id)
    config = get_configuration(session, experiment.configuration_id)
    dataset = get_dataset(session, config.dataset_id)
    try:
        files = library.resolve_attachments(config.attachments)
    except library.LibraryError as e:
        raise HTTPException(422, str(e)) from e
    try:
        client = get_client()
    except MissingAPIKeyError as e:
        raise HTTPException(400, str(e)) from e

    # Every dataset is queried, never pasted into the prompt, so every number can be cited.
    csv_text = ds.read_text(dataset.id)
    csv_path = ds.dataset_path(dataset.id)
    query = DataQuery(csv_path)
    try:
        data_text = prompts.query_data_text(dataset, csv_text, query.schema())
    finally:
        query.close()

    config_text = prompts.configuration_text(config, dataset, files)
    systems = {
        "baseline": prompts.build_system(data_text, None),
        "configured": prompts.build_system(data_text, config_text),
    }
    results = arena.run_both(
        client,
        systems,
        question,
        tags={"experiment_id": experiment.id, "dataset_id": dataset.id},
        csv_path=csv_path,
        source=dataset.sha256,
    )

    # Persist what each arm cited, then render every draft fail-closed:
    # one unknown {{ev:*}} reference and that arm's answer is refused, not shown.
    for r in results:
        store_cited(session, r["tool_calls"], dataset.sha256, dataset.id)
    resolver = DraftResolver(session)
    for r in results:
        if not r.get("output"):
            continue
        rendered = resolver.render(r["output"])
        r["render_ok"] = rendered.ok
        r["rendered_output"] = rendered.text or ""
        r["missing_refs"] = rendered.missing

    trial = Trial(
        experiment_id=experiment.id,
        question=question,
        config_version=prompts.config_version(config_text),
        library_files=[{"path": f["path"], "sha256": f["sha256"]} for f in files],
    )
    case = golden.match(session, dataset.id, question)  # exact match only; never "similar"
    if case:
        trial.golden_case_id = case.id
    session.add(trial)
    for r in results:
        session.add(ArmResponse(trial_id=trial.id, **r))
    session.commit()
    session.refresh(trial)
    ensure_scores(session, [trial])  # every run is scored as soon as it exists
    return _trial_out(session, trial)


@router.patch("/trials/{trial_id}", response_model=TrialOut)
def update_trial(trial_id: str, body: TrialPatch, session: SessionDep):
    trial = session.get(Trial, trial_id)
    if not trial:
        raise HTTPException(404, "Trial not found.")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(trial, key, value)
    session.add(trial)
    session.commit()
    session.refresh(trial)
    return _trial_out(session, trial)
