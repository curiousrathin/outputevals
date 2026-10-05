from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.datasets import get_dataset
from app.core.prompts import configuration_text
from app.db import SessionDep
from app.models import Configuration, Experiment, new_id, utcnow

router = APIRouter(prefix="/api/configurations", tags=["configurations"])


class ConfigNode(BaseModel):
    id: str
    description: str = ""
    x: float = 0
    y: float = 0


class ConfigEdge(BaseModel):
    id: str | None = None
    source: str
    target: str
    description: str


class ConfigurationIn(BaseModel):
    name: str
    dataset_id: str
    nodes: list[ConfigNode] = []
    edges: list[ConfigEdge] = []
    context_markdown: str = ""


class ConfigurationOut(BaseModel):
    id: str
    name: str
    dataset_id: str
    nodes: list[dict]
    edges: list[dict]
    context_markdown: str
    prompt_preview: str  # exactly what the configured arm adds to the prompt


def get_configuration(session: Session, config_id: str) -> Configuration:
    config = session.get(Configuration, config_id)
    if not config:
        raise HTTPException(404, "Configuration not found.")
    return config


def _out(session: Session, config: Configuration) -> ConfigurationOut:
    dataset = get_dataset(session, config.dataset_id)
    return ConfigurationOut(
        **config.model_dump(
            include={"id", "name", "dataset_id", "nodes", "edges", "context_markdown"}
        ),
        prompt_preview=configuration_text(config, dataset),
    )


def _apply(session: Session, config: Configuration, body: ConfigurationIn) -> None:
    dataset = get_dataset(session, body.dataset_id)
    columns = [c["name"] for c in dataset.columns]
    given = {n.id: n for n in body.nodes}
    unknown = set(given) - set(columns)
    if unknown:
        raise HTTPException(422, f"Unknown fields: {', '.join(sorted(unknown))}")

    # Every column is a node; lay out any that weren't positioned yet in a grid.
    nodes = []
    for i, col in enumerate(columns):
        node = given.get(col) or ConfigNode(id=col, x=(i % 4) * 240, y=(i // 4) * 130)
        nodes.append(node.model_dump())

    edges = []
    for e in body.edges:
        if e.source not in columns or e.target not in columns:
            raise HTTPException(
                422, f"Connection {e.source} → {e.target} references an unknown field."
            )
        if e.source == e.target:
            raise HTTPException(422, "A field can't be connected to itself.")
        if not e.description.strip():
            raise HTTPException(422, f"Describe the connection {e.source} → {e.target}.")
        edges.append({**e.model_dump(), "id": e.id or new_id()})

    config.name = body.name.strip() or "Untitled configuration"
    config.dataset_id = body.dataset_id
    config.nodes = nodes
    config.edges = edges
    config.context_markdown = body.context_markdown
    config.updated_at = utcnow()


@router.post("", response_model=ConfigurationOut)
def create_configuration(body: ConfigurationIn, session: SessionDep):
    config = Configuration(name=body.name, dataset_id=body.dataset_id)
    _apply(session, config, body)
    session.add(config)
    session.commit()
    session.refresh(config)
    return _out(session, config)


@router.get("", response_model=list[ConfigurationOut])
def list_configurations(session: SessionDep):
    configs = session.exec(select(Configuration).order_by(Configuration.updated_at.desc())).all()
    return [_out(session, c) for c in configs]


@router.get("/{config_id}", response_model=ConfigurationOut)
def read_configuration(config_id: str, session: SessionDep):
    return _out(session, get_configuration(session, config_id))


@router.put("/{config_id}", response_model=ConfigurationOut)
def update_configuration(config_id: str, body: ConfigurationIn, session: SessionDep):
    config = get_configuration(session, config_id)
    _apply(session, config, body)
    session.add(config)
    session.commit()
    session.refresh(config)
    return _out(session, config)


@router.delete("/{config_id}", status_code=204)
def delete_configuration(config_id: str, session: SessionDep):
    config = get_configuration(session, config_id)
    if session.exec(select(Experiment).where(Experiment.configuration_id == config_id)).first():
        raise HTTPException(409, "Configuration is used by an experiment. Delete those first.")
    session.delete(config)
    session.commit()
