from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from app.core import datasets as ds
from app.db import SessionDep
from app.models import Configuration, Dataset

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def get_dataset(session: Session, dataset_id: str) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(404, "Dataset not found.")
    return dataset


@router.post("", response_model=Dataset)
async def upload_dataset(
    file: UploadFile, session: SessionDep, name: Annotated[str | None, Form()] = None
):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(422, "Only .csv files are supported for now.")
    raw = await file.read()
    try:
        df, columns = ds.profile(raw)
    except ds.CSVError as e:
        raise HTTPException(422, str(e)) from e

    filename = Path(file.filename).name
    dataset = Dataset(
        name=(name or "").strip() or Path(filename).stem,
        filename=filename,
        sha256=ds.sha256(raw),
        size_bytes=len(raw),
        row_count=len(df),
        est_tokens=ds.estimate_tokens(ds.decode(raw)),
        columns=columns,
    )
    path = ds.dataset_path(dataset.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)  # stored untouched: this is the baseline
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset


@router.get("", response_model=list[Dataset])
def list_datasets(session: SessionDep):
    return session.exec(select(Dataset).order_by(Dataset.created_at.desc())).all()


@router.get("/{dataset_id}", response_model=Dataset)
def read_dataset(dataset_id: str, session: SessionDep):
    return get_dataset(session, dataset_id)


@router.get("/{dataset_id}/preview")
def preview_dataset(dataset_id: str, session: SessionDep, limit: int = 50):
    get_dataset(session, dataset_id)
    return ds.preview(dataset_id, min(limit, 500))


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, session: SessionDep):
    dataset = get_dataset(session, dataset_id)
    if session.exec(select(Configuration).where(Configuration.dataset_id == dataset_id)).first():
        raise HTTPException(409, "Dataset is used by a configuration. Delete those first.")
    session.delete(dataset)
    session.commit()
    ds.dataset_path(dataset_id).unlink(missing_ok=True)
