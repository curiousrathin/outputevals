"""Asking one question of both arms, and saving the result. Used by the arena and by batches.

`prepare` freezes everything a run depends on (prompts, attached files, config version),
so a batch can prepare once and every run in it sees exactly the same configuration.
"""

import threading
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from app.core import arena, golden, library, prompts
from app.core import datasets as ds
from app.core.evidence import store_cited
from app.core.resolver import DraftResolver
from app.core.sqltool import DataQuery
from app.evals.service import ensure_scores
from app.models import ArmResponse, Configuration, Dataset, Experiment, Trial

# Runs happen in parallel during a batch; saving evidence is check-then-insert,
# so writes are serialized. Model calls (the slow part) stay parallel.
WRITE_LOCK = threading.Lock()


class RunError(Exception):
    """The run can't start, e.g. an attached library file is missing."""


@dataclass(frozen=True)
class RunSetup:
    experiment_id: str
    dataset_id: str
    dataset_sha: str
    csv_path: Path
    systems: dict[str, list[dict]]
    config_version: str
    library_files: list[dict]  # [{path, sha256}]


def prepare(experiment: Experiment, config: Configuration, dataset: Dataset) -> RunSetup:
    try:
        files = library.resolve_attachments(config.attachments)
    except library.LibraryError as e:
        raise RunError(str(e)) from e

    # Every dataset is queried, never pasted into the prompt, so every number can be cited.
    csv_path = ds.dataset_path(dataset.id)
    query = DataQuery(csv_path)
    try:
        data_text = prompts.query_data_text(dataset, ds.read_text(dataset.id), query.schema())
    finally:
        query.close()

    config_text = prompts.configuration_text(config, dataset, files)
    return RunSetup(
        experiment_id=experiment.id,
        dataset_id=dataset.id,
        dataset_sha=dataset.sha256,
        csv_path=csv_path,
        systems={
            "baseline": prompts.build_system(data_text, None),
            "configured": prompts.build_system(data_text, config_text),
        },
        config_version=prompts.config_version(config_text),
        library_files=[{"path": f["path"], "sha256": f["sha256"]} for f in files],
    )


def execute(session: Session, client, setup: RunSetup, question: str, batch_id: str = "", repeat: int = 0) -> Trial:
    """Ask both arms, render each draft fail-closed, save the trial and score it.
    Safe to call from a batch thread: `setup` holds plain values, no database objects."""
    results = arena.run_both(
        client,
        setup.systems,
        question,
        tags={"experiment_id": setup.experiment_id, "dataset_id": setup.dataset_id, **({"batch_id": batch_id} if batch_id else {})},
        csv_path=setup.csv_path,
        source=setup.dataset_sha,
    )
    with WRITE_LOCK:
        # Persist what each arm cited, then render every draft fail-closed:
        # one unknown {{ev:*}} reference and that arm's answer is refused, not shown.
        for r in results:
            store_cited(session, r["tool_calls"], setup.dataset_sha, setup.dataset_id)
        resolver = DraftResolver(session)
        for r in results:
            if not r.get("output"):
                continue
            rendered = resolver.render(r["output"])
            r["render_ok"] = rendered.ok
            r["rendered_output"] = rendered.text or ""
            r["missing_refs"] = rendered.missing

        trial = Trial(
            experiment_id=setup.experiment_id,
            question=question,
            config_version=setup.config_version,
            library_files=list(setup.library_files),
            batch_id=batch_id,
            repeat=repeat,
        )
        case = golden.match(session, setup.dataset_id, question)  # exact match only; never "similar"
        if case:
            trial.golden_case_id = case.id
        session.add(trial)
        for r in results:
            session.add(ArmResponse(trial_id=trial.id, **r))
        session.commit()
        session.refresh(trial)
        ensure_scores(session, [trial])  # every run is scored as soon as it exists
    return trial
