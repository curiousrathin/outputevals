from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.api.configurations import get_configuration
from app.api.datasets import get_dataset
from app.core import arena, prompts
from app.core import datasets as ds
from app.core.llm import MissingAPIKeyError, get_client
from app.core.sqltool import DataQuery
from app.db import SessionDep
from app.models import ArmResponse, Experiment, Trial

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
    preference: str | None
    note: str
    created_at: datetime
    responses: list[ArmResponse]


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


def _trial_out(session: Session, trial: Trial) -> TrialOut:
    responses = session.exec(select(ArmResponse).where(ArmResponse.trial_id == trial.id)).all()
    order = {"baseline": 0, "configured": 1}
    return TrialOut(
        **trial.model_dump(), responses=sorted(responses, key=lambda r: order.get(r.arm, 9))
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
        session.delete(trial)
    session.delete(experiment)
    session.commit()


@router.get("/experiments/{experiment_id}/trials", response_model=list[TrialOut])
def list_trials(experiment_id: str, session: SessionDep):
    _get_experiment(session, experiment_id)
    trials = session.exec(
        select(Trial).where(Trial.experiment_id == experiment_id).order_by(Trial.created_at.desc())
    ).all()
    return [_trial_out(session, t) for t in trials]


@router.post("/experiments/{experiment_id}/trials", response_model=TrialOut)
def run_trial(experiment_id: str, body: TrialIn, session: SessionDep):
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Ask a question.")
    experiment = _get_experiment(session, experiment_id)
    config = get_configuration(session, experiment.configuration_id)
    dataset = get_dataset(session, config.dataset_id)
    try:
        client = get_client()
    except MissingAPIKeyError as e:
        raise HTTPException(400, str(e)) from e

    # Both arms always get the same data mode, so the configuration stays the only difference.
    csv_text = ds.read_text(dataset.id)
    csv_path = None
    if dataset.est_tokens <= ds.MAX_INLINE_TOKENS:
        data_text = prompts.inline_data_text(dataset, csv_text)
    else:
        csv_path = ds.dataset_path(dataset.id)
        query = DataQuery(csv_path)
        try:
            data_text = prompts.query_data_text(dataset, csv_text, query.schema())
        finally:
            query.close()

    config_text = prompts.configuration_text(config, dataset)
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
    )

    trial = Trial(
        experiment_id=experiment.id,
        question=question,
        config_version=prompts.config_version(config_text),
    )
    session.add(trial)
    for r in results:
        session.add(ArmResponse(trial_id=trial.id, **r))
    session.commit()
    session.refresh(trial)
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
