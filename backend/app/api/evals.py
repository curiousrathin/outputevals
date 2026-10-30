from fastapi import APIRouter, HTTPException
from sqlmodel import Session

from app.api.experiments import scoped_trials
from app.db import SessionDep
from app.evals.registry import REGISTRY, UNLOCK_HINTS
from app.evals.service import ensure_scores, rescore, scorecard
from app.models import Experiment, Trial

router = APIRouter(prefix="/api", tags=["evals"])


def _trials(session: Session, experiment_id: str, scope: str = "all") -> list[Trial]:
    if not session.get(Experiment, experiment_id):
        raise HTTPException(404, "Experiment not found.")
    return scoped_trials(session, experiment_id, scope)


@router.get("/evals/scorers")
def list_scorers() -> dict:
    """Every registered eval, with what it measures, how it decides and when it's misleading."""
    return {"scorers": [s.info() for s in REGISTRY.values()], "unlock_hints": UNLOCK_HINTS}


@router.get("/experiments/{experiment_id}/evals")
def experiment_evals(experiment_id: str, session: SessionDep, scope: str = "all") -> dict:
    """scope: "all" runs, "arena" (asked by hand) or one batch's id."""
    trials = _trials(session, experiment_id, scope)
    ensure_scores(session, trials)
    return {"runs": len(trials), "scorecard": scorecard(session, trials)}


@router.post("/experiments/{experiment_id}/evals/rescore")
def rescore_experiment(experiment_id: str, session: SessionDep) -> dict:
    trials = _trials(session, experiment_id)
    rescore(session, trials)
    return {"runs": len(trials), "scorecard": scorecard(session, trials)}
