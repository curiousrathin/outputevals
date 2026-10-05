import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Dataset(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    filename: str
    sha256: str
    size_bytes: int
    row_count: int
    est_tokens: int
    # [{name, dtype, non_null, unique, samples}]
    columns: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Configuration(SQLModel, table=True):
    """Reusable context setup: field graph + extra Markdown context for one dataset."""

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    dataset_id: str = Field(foreign_key="dataset.id", index=True)
    # [{id (column name), description, x, y}]
    nodes: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    # [{id, source, target, description}]
    edges: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    context_markdown: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Experiment(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    description: str = ""
    configuration_id: str = Field(foreign_key="configuration.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Trial(SQLModel, table=True):
    """One question asked in the arena; answered by both arms."""

    id: str = Field(default_factory=new_id, primary_key=True)
    experiment_id: str = Field(foreign_key="experiment.id", index=True)
    question: str = Field(sa_column=Column(Text))
    # Hash of the configuration text the configured arm saw, so later edits
    # to the configuration don't blur history.
    config_version: str
    preference: str | None = None  # baseline | configured | tie | both_bad
    note: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)


class ArmResponse(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    trial_id: str = Field(foreign_key="trial.id", index=True)
    arm: str  # baseline | configured
    model: str
    # inline (CSV in prompt) | query (SQL tool)
    mode: str = Field(default="inline", sa_column_kwargs={"server_default": "inline"})
    # [{sql, error, row_count, result}] in the order the model ran them
    tool_calls: list[dict] = Field(default_factory=list, sa_column=Column(JSON, default=list))
    output: str = Field(default="", sa_column=Column(Text))
    system_prompt: str = Field(default="", sa_column=Column(Text))
    stop_reason: str | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0
    fingerprint: str = ""
    content_hash: str = ""
    created_at: datetime = Field(default_factory=utcnow)
