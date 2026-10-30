"""Batches (eval step 3): the golden set asked N times, and the statistics over the repeats."""

import threading

import anthropic
import httpx
import numpy as np
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.core import batches
from app.evals.stats import paired_difference, rate
from app.models import Batch, Experiment
from tests.test_evals import _ask
from tests.test_golden import _golden
from tests.test_workflow import FakeClaude, FakeClaudeCiting


def _rng():
    return np.random.default_rng(0)


def _setup(client, monkeypatch, fake=None):
    """An experiment with one golden question ("Top customer?" -> Customer 4, 400600)."""
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    assert _golden(client, trial).status_code == 200
    monkeypatch.setattr("app.api.batches.get_client", lambda: fake or FakeClaudeCiting())
    return exp


def _run(client, exp, **body):
    resp = client.post(f"/api/experiments/{exp['id']}/batches", json={"repeats": 3, **body})
    assert resp.status_code == 200, resp.text
    batch = resp.json()
    batches.wait(batch["id"])
    return client.get(f"/api/batches/{batch['id']}").json()


# ---- statistics ----


def test_rate_weights_each_question_once():
    # 1 of 1 on one question, 0 of 3 on another: 50%, not 25%
    r = rate([[True], [False, False, False]], _rng())
    assert r["mean"] == 0.5 and r["questions"] == 2 and r["runs"] == 4
    assert 0 <= r["lo"] <= r["mean"] <= r["hi"] <= 1


def test_perfect_results_have_a_tight_interval_and_one_run_has_none():
    r = rate([[True] * 5, [True] * 5], _rng())
    assert (r["mean"], r["lo"], r["hi"]) == (1, 1, 1)
    assert rate([[True]], _rng())["lo"] is None
    assert rate([[], []], _rng()) is None


def test_fewer_questions_give_wider_intervals():
    few = rate([[True, False]] * 2, _rng())
    many = rate([[True, False]] * 40, _rng())
    assert few["hi"] - few["lo"] > many["hi"] - many["lo"]


def test_paired_difference_is_configured_minus_baseline():
    d = paired_difference([([False] * 5, [True] * 5)] * 4, _rng())
    assert d["mean"] == 1 and d["lo"] == d["hi"] == 1
    assert paired_difference([([True], [])], _rng()) is None  # needs both arms on a question


# ---- running a batch ----


def test_a_batch_asks_every_golden_question_n_times_and_reports(client, monkeypatch):
    exp = _setup(client, monkeypatch)
    out = _run(client, exp)
    b, report = out["batch"], out["report"]
    assert (b["status"], b["done"], b["total"], b["repeats"]) == ("done", 3, 3, 3)
    assert b["config_version"] and b["model"] == settings.llm_model
    assert report["runs_done"] == 3
    for arm in ("baseline", "configured"):
        a = report["arms"][arm]
        assert a["accuracy"]["mean"] == 1 and a["accuracy"]["runs"] == 3
        assert a["pass_all"] == {"count": 1, "of": 1} and a["pass_any"] == {"count": 1, "of": 1}
        assert a["consistent"] == {"count": 1, "of": 1}
        assert a["cost"]["total"] > 0 and a["latency"]["p50"] >= 0
    q = report["questions"][0]
    assert q["question"] == "Top customer?"
    assert [r["repeat"] for r in q["arms"]["configured"]["runs"]] == [0, 1, 2]
    assert q["arms"]["configured"]["distinct_answers"] == 1
    assert report["difference"]["mean"] == 0
    assert any(e["scorer"] == "correct" and e["arm"] == "baseline" for e in report["evals"])


def test_wrong_answers_lower_accuracy_and_pass_all(client, monkeypatch):
    exp = _setup(client, monkeypatch, fake=FakeClaude())  # answers in prose with no numbers
    report = _run(client, exp, repeats=2)["report"]
    a = report["arms"]["baseline"]
    assert a["accuracy"]["mean"] == 0 and a["pass_all"]["count"] == 0 and a["pass_any"]["count"] == 0
    run = report["questions"][0]["arms"]["baseline"]["runs"][0]
    assert run["correct"] is False and "400600" in run["reason"]


def test_batch_runs_stay_out_of_the_arena_but_count_in_evals(client, monkeypatch):
    exp = _setup(client, monkeypatch)
    b = _run(client, exp)["batch"]
    arena = client.get(f"/api/experiments/{exp['id']}/trials?scope=arena").json()
    in_batch = client.get(f"/api/experiments/{exp['id']}/trials?scope={b['id']}").json()
    assert len(arena) == 1 and len(in_batch) == 3
    assert all(t["batch_id"] == b["id"] and t["golden_case_id"] for t in in_batch)
    assert client.get(f"/api/experiments/{exp['id']}/evals?scope={b['id']}").json()["runs"] == 3
    assert client.get(f"/api/experiments/{exp['id']}/evals").json()["runs"] == 4


def test_estimate_uses_earlier_runs(client, monkeypatch):
    exp = _setup(client, monkeypatch)
    est = client.get(f"/api/experiments/{exp['id']}/batches/estimate?repeats=4").json()
    assert (est["questions"], est["runs"], est["model_calls_at_least"]) == (1, 4, 8)
    assert est["est_cost_usd"] > 0 and est["based_on_runs"] == 1


@pytest.mark.parametrize("body, status", [
    ({"repeats": 0}, 422),
    ({"repeats": 21}, 422),
    ({"golden_case_ids": ["nope"]}, 422),
    ({"golden_case_ids": []}, 422),
])
def test_batch_validation(client, monkeypatch, body, status):
    exp = _setup(client, monkeypatch)
    assert client.post(f"/api/experiments/{exp['id']}/batches", json={"repeats": 3, **body}).status_code == status


def test_no_golden_questions_and_the_run_limit(client, monkeypatch):
    exp, _ = _ask(client, monkeypatch, FakeClaudeCiting())
    resp = client.post(f"/api/experiments/{exp['id']}/batches", json={"repeats": 3})
    assert resp.status_code == 422 and "no golden questions" in resp.json()["detail"]
    exp = _setup(client, monkeypatch)
    monkeypatch.setattr(settings, "batch_max_runs", 2)
    resp = client.post(f"/api/experiments/{exp['id']}/batches", json={"repeats": 3})
    assert resp.status_code == 422 and "limit is 2" in resp.json()["detail"]


class Blocking(FakeClaudeCiting):
    """Waits for a signal before every model call, so a test can act mid-batch."""

    def __init__(self):
        super().__init__()
        self.go = threading.Event()

    def create(self, **kwargs):
        assert self.go.wait(10)
        return super().create(**kwargs)


def test_cancel_keeps_finished_runs_and_starts_nothing_new(client, monkeypatch):
    monkeypatch.setattr(settings, "batch_concurrency", 1)
    fake = Blocking()
    exp = _setup(client, monkeypatch, fake=fake)
    b = client.post(f"/api/experiments/{exp['id']}/batches", json={"repeats": 5}).json()
    assert client.post(f"/api/experiments/{exp['id']}/batches", json={"repeats": 1}).status_code == 409
    assert client.delete(f"/api/experiments/{exp['id']}").status_code == 409
    assert client.delete(f"/api/batches/{b['id']}").status_code == 409
    assert client.post(f"/api/batches/{b['id']}/cancel").status_code == 200
    fake.go.set()
    batches.wait(b["id"])
    out = client.get(f"/api/batches/{b['id']}").json()
    assert out["batch"]["status"] == "cancelled" and out["batch"]["done"] == 1
    assert out["report"]["runs_done"] == 1


class Unreachable:
    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))


def test_repeated_api_failures_stop_the_batch(client, monkeypatch):
    exp = _setup(client, monkeypatch, fake=Unreachable())
    b = _run(client, exp, repeats=10)["batch"]
    assert b["status"] == "failed" and "couldn't reach the model" in b["error"]
    assert b["done"] < 10


def test_deleting_a_batch_removes_its_runs(client, monkeypatch):
    exp = _setup(client, monkeypatch)
    b = _run(client, exp)["batch"]
    assert client.delete(f"/api/batches/{b['id']}").status_code == 204
    assert len(client.get(f"/api/experiments/{exp['id']}/trials").json()) == 1
    assert client.get(f"/api/batches/{b['id']}").status_code == 404


def test_batches_left_running_are_marked_interrupted(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Experiment(id="e1", name="e", configuration_id="c"))
        s.add(Batch(id="b1", experiment_id="e1", repeats=1, total=1))
        s.commit()
    batches.mark_interrupted(engine)
    with Session(engine) as s:
        assert s.exec(select(Batch)).one().status == "interrupted"
