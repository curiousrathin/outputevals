from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.evidence import current_row, value_history
from app.db import SessionDep

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


class EvidenceOut(BaseModel):
    ev_id: str
    value: str
    label: str
    query: str
    source: str
    dataset_id: str
    created_at: datetime
    history: list[str]  # every value ever recorded for this id, oldest first


@router.get("/{ev_id}", response_model=EvidenceOut)
def read_evidence(ev_id: str, session: SessionDep):
    """Where a number came from: its current value, the query that produced it, and its history."""
    row = current_row(session, ev_id)
    if row is None:
        raise HTTPException(404, "Evidence not found.")
    return EvidenceOut(
        **row.model_dump(include={"ev_id", "value", "label", "query", "source", "dataset_id", "created_at"}),
        history=value_history(session, ev_id),
    )
