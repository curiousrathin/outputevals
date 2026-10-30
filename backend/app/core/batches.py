"""Running a batch: every chosen golden question, `repeats` times, both arms, in the background.

Runs go in rounds (every question once, then every question again), so a batch that's
cancelled or fails part-way still covers each question about equally. A few runs happen
at once (OT_BATCH_CONCURRENCY); each one asks both arms in parallel.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.config import settings
from app.core import runner
from app.models import ArmResponse, Batch, utcnow

# A run whose arms both failed to reach the API; this many in a row stops the batch.
API_FAILURES_TO_STOP = 3

_threads: dict[str, threading.Thread] = {}
_cancel: set[str] = set()


def _api_failure(error: str | None) -> bool:
    return bool(error) and error.startswith(("Anthropic API error", "Couldn't reach"))


def _finish(bind: Engine, batch_id: str, status: str, error: str = "") -> None:
    with runner.WRITE_LOCK, Session(bind) as s:
        b = s.get(Batch, batch_id)
        if b is None:
            return
        b.status, b.error, b.finished_at = status, error, utcnow()
        s.add(b)
        s.commit()


def _run(bind: Engine, batch_id: str, setup: runner.RunSetup, client, jobs: list[tuple[str, int]]) -> None:
    failures = 0
    error = ""

    def one(question: str, repeat: int) -> list[str | None] | None:
        """Ask one run; returns each arm's error (None when it answered), or None if skipped."""
        if batch_id in _cancel:
            return None
        with Session(bind) as s:
            trial = runner.execute(s, client, setup, question, batch_id=batch_id, repeat=repeat)
            errors = list(s.exec(select(ArmResponse.error).where(ArmResponse.trial_id == trial.id)).all())
            with runner.WRITE_LOCK:
                s.execute(update(Batch).where(Batch.id == batch_id).values(done=Batch.done + 1))
                s.commit()
            return errors

    try:
        with ThreadPoolExecutor(max_workers=max(1, settings.batch_concurrency)) as pool:
            futures = [pool.submit(one, q, rep) for q, rep in jobs]
            for f in as_completed(futures):
                try:
                    errors = f.result()
                except Exception as e:  # noqa: BLE001 - record it and stop
                    error = error or f"A run failed: {type(e).__name__}: {e}"
                    _cancel.add(batch_id)
                    continue
                if errors is None:
                    continue
                if errors and all(_api_failure(e) for e in errors):
                    failures += 1
                    if failures >= API_FAILURES_TO_STOP and not error:
                        error = f"Stopped after {failures} runs in a row couldn't reach the model: {errors[0]}"
                        _cancel.add(batch_id)
                else:
                    failures = 0
    except Exception as e:  # noqa: BLE001 - never leave a batch "running"
        error = error or f"The batch stopped: {type(e).__name__}: {e}"
    finally:
        cancelled = batch_id in _cancel
        try:
            _finish(bind, batch_id, "failed" if error else "cancelled" if cancelled else "done", error)
        finally:
            _cancel.discard(batch_id)
            _threads.pop(batch_id, None)


def start(bind: Engine, batch: Batch, setup: runner.RunSetup, client, questions: list[str]) -> None:
    jobs = [(q, rep) for rep in range(batch.repeats) for q in questions]
    t = threading.Thread(target=_run, args=(bind, batch.id, setup, client, jobs), name=f"batch-{batch.id}", daemon=True)
    _threads[batch.id] = t
    t.start()


def is_running(batch_id: str) -> bool:
    return batch_id in _threads


def cancel(batch_id: str) -> None:
    """Runs already asked finish and are kept; nothing new starts."""
    if batch_id in _threads:
        _cancel.add(batch_id)


def wait(batch_id: str, timeout: float = 60) -> None:
    t = _threads.get(batch_id)
    if t:
        t.join(timeout)


def mark_interrupted(bind: Engine) -> None:
    """On startup: batches left "running" by a previous process will never finish."""
    with Session(bind) as s:
        s.execute(update(Batch).where(Batch.status == "running").values(status="interrupted", finished_at=utcnow()))
        s.commit()
