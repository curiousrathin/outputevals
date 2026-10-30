from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from app.core import library
from app.db import SessionDep
from app.models import Configuration

router = APIRouter(prefix="/api/library", tags=["library"])


class FileIn(BaseModel):
    path: str
    content: str


class FolderIn(BaseModel):
    path: str


class FileOut(BaseModel):
    path: str
    content: str


def _guard(fn, *args):
    try:
        return fn(*args)
    except library.LibraryError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/tree")
def read_tree() -> list[dict]:
    return library.tree()


@router.get("/file", response_model=FileOut)
def read_file(path: str):
    norm = _guard(library.normalize, path)
    return FileOut(path=norm, content=_guard(library.read_file, norm))


@router.put("/file", response_model=FileOut)
def write_file(body: FileIn):
    norm = _guard(library.normalize, body.path)
    _guard(library.write_file, norm, body.content)
    return FileOut(path=norm, content=body.content)


@router.post("/folder", status_code=204)
def make_folder(body: FolderIn):
    _guard(library.make_folder, body.path)


@router.delete("/item", status_code=204)
def delete_item(path: str, session: SessionDep):
    norm = _guard(library.normalize, path)
    users = [
        c.name
        for c in session.exec(select(Configuration)).all()
        if any(library.is_used_by(a, norm) for a in c.attachments)
    ]
    if users:
        raise HTTPException(
            409, f"{norm} is attached to {', '.join(sorted(users))}. Remove it there first."
        )
    _guard(library.delete, norm)
