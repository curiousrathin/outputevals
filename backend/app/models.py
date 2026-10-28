import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, Text, UniqueConstraint
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
    """Reusable context setup for one dataset: field graph, attached library
    files, and optional notes that apply to this configuration only."""

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    dataset_id: str = Field(foreign_key="dataset.id", index=True)
    # [{id (column name), description, x, y}]
    nodes: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    # [{id, source, target, description}]
    edges: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    # Library folders or files, included in full in the configured arm's prompt.
    attachments: list[str] = Field(default_factory=list, sa_column=Column(JSON, default=list))
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
    # [{path, sha256}] of every library file the configured arm saw.
    library_files: list[dict] = Field(default_factory=list, sa_column=Column(JSON, default=list))
    preference: str | None = None  # baseline | configured | tie | both_bad
    note: str = Field(default="", sa_column=Column(Text))
    # The golden case this question is graded against: "" until one is set or matched.
    golden_case_id: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class GoldenCase(SQLModel, table=True):
    """A question with a verified answer: the exam configurations are graded on.

    Pinned to the exact data it was verified against (dataset id + content hash),
    never to a configuration, so different configurations can be compared on it.
    `version` goes up on every edit, and results graded against an older version
    are re-scored.
    """

    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="dataset.id", index=True)
    dataset_sha: str
    workflow_id: str = ""  # set once workflows exist and this case belongs to one
    question: str = Field(sa_column=Column(Text))
    question_key: str = Field(index=True)  # normalized question, used to match runs
    params: dict = Field(default_factory=dict, sa_column=Column(JSON, default=dict))  # workflow inputs
    answerable: bool = True  # False: the right answer is to say the data can't answer it
    expected_values: list[str] = Field(default_factory=list, sa_column=Column(JSON, default=list))
    tolerance: float = 0.001  # relative tolerance for numeric values (0.001 = 0.1%)
    expected_columns: list[str] = Field(default_factory=list, sa_column=Column(JSON, default=list))
    reference_sql: str = Field(default="", sa_column=Column(Text))
    category: str = ""  # lookup | aggregation | multi-hop | unanswerable
    held_out: bool = False  # never tune knowledge against held-out cases
    notes: str = Field(default="", sa_column=Column(Text))
    version: int = 1
    created_from_trial_id: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Evidence(SQLModel, table=True):
    """Content-addressed fact. Append-only: rows are never edited, only marked
    superseded when a correction is appended."""

    row_id: int | None = Field(default=None, primary_key=True)
    ev_id: str = Field(index=True)
    value: str = Field(sa_column=Column(Text, nullable=False))
    source: str  # sha256 of the dataset the value was computed from
    query: str = Field(default="", sa_column=Column(Text))
    label: str = ""  # e.g. 'row 0 · "customer"'
    dataset_id: str = Field(default="", index=True)
    superseded_by: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ArmResponse(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    trial_id: str = Field(foreign_key="trial.id", index=True)
    arm: str  # baseline | configured
    model: str
    # Always "query" now; "inline" (CSV pasted into the prompt) only on old rows.
    mode: str = Field(default="query", sa_column_kwargs={"server_default": "inline"})
    # [{sql, error, row_count, result, evidence}] in the order the model ran them
    tool_calls: list[dict] = Field(default_factory=list, sa_column=Column(JSON, default=list))
    output: str = Field(default="", sa_column=Column(Text))  # raw draft with {{ev:*}} refs
    # Fail-closed render of the draft; None when there was no draft to render.
    render_ok: bool | None = None
    rendered_output: str = Field(default="", sa_column=Column(Text))
    missing_refs: list[str] = Field(default_factory=list, sa_column=Column(JSON, default=list))
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


class Score(SQLModel, table=True):
    """One eval result for one arm (or, for comparisons, one trial).

    Keyed by scorer *version*: changing a scorer adds new rows instead of
    overwriting, so earlier results stay inspectable. Only `scored` rows count
    toward averages; the other states say why there's no number.
    """

    __table_args__ = (UniqueConstraint("trial_id", "response_id", "scorer", "scorer_version"),)

    id: str = Field(default_factory=new_id, primary_key=True)
    trial_id: str = Field(foreign_key="trial.id", index=True)
    response_id: str = Field(default="", index=True)  # "" for trial-level scores
    arm: str = ""  # baseline | configured | "" for trial-level scores
    scorer: str = Field(index=True)
    scorer_version: int
    state: str  # scored | locked | not_applicable | not_computed
    value: float | None = None
    passed: bool | None = None  # None when the eval measures something instead of judging it
    reason: str = Field(default="", sa_column=Column(Text))
    details: dict = Field(default_factory=dict, sa_column=Column(JSON, default=dict))
    created_at: datetime = Field(default_factory=utcnow)
