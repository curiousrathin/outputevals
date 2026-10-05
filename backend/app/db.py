from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import JSON, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


def _add_missing_columns() -> None:
    """Minimal forward migration: add columns that new model fields introduced."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                default = getattr(col.server_default, "arg", None) or getattr(
                    col.default, "arg", None
                )
                if isinstance(col.type, JSON):
                    ddl += " DEFAULT '[]'"
                elif isinstance(default, str | int | float):
                    ddl += (
                        f" DEFAULT '{default}'"
                        if isinstance(default, str)
                        else f" DEFAULT {default}"
                    )
                conn.execute(text(ddl))


def create_db() -> None:
    from app import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
