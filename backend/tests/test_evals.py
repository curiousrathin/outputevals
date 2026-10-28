import dataclasses

import pytest

from app.config import settings
from app.evals.numbers import canonical, unsourced_numbers
from app.evals.pricing import cost_usd
from app.evals.registry import REGISTRY, Scorer, not_applicable, run_scorer, scored
from tests.test_workflow import FakeClaude, FakeClaudeCiting, FakeClaudeWithSQL, _big_experiment


def _ask(client, monkeypatch, fake, question="Top customer?"):
    exp = _big_experiment(client)
    monkeypatch.setattr("app.api.experiments.get_client", lambda: fake)
    trial = client.post(f"/api/experiments/{exp['id']}/trials", json={"question": question}).json()
    return exp, trial


def _by(trial):
    return {(s["arm"], s["scorer"]): s for s in trial["scores"]}


# ---- finding unsourced numbers ----


def test_numbers_from_the_question_are_allowed():
    assert unsourced_numbers("In July 2026 the top was {{ev:ab12cd}}.", "Top customer in July 2026?", []) == []


def test_references_code_and_list_markers_are_ignored():
    draft = "1. Customer {{ev:ab12cd}}\n2. Ran `LIMIT 5`:\n```sql\nSELECT 1\n```"
    assert unsourced_numbers(draft, "Who?", []) == []


def test_typed_and_invented_numbers_are_told_apart():
    found = unsourced_numbers("Noah Paul with $149,410.09 across 12 invoices.", "Who?", ["Noah Paul", "149410.09"])
    assert found == [
        {"number": "$149,410.09", "matches_query": True},  # typed instead of cited
        {"number": "12", "matches_query": False},  # in no query result
    ]


def test_dates_from_the_data_count_as_numbers():
    found = unsourced_numbers("The last order was on 7/13/2026.", "Last order in July 2026?", [])
    assert [f["number"] for f in found] == ["7", "13"]


def test_canonical_number_forms():
    assert canonical("$1,000.50") == "1000.5"
    assert canonical("12%") == "12"
    assert canonical("2,026") == "2026"
    assert canonical("abc") is None


# ---- pricing ----


def test_cost_prices_cache_reads_separately(monkeypatch):
    usd = cost_usd("claude-opus-5-5", 1_000_000, 100_000, 2_000_000, 0)
    assert usd["input"] == 4.0 and usd["output"] == 2.0 and usd["cache_read"] == pytest.approx(0.4)
    assert usd["total"] == pytest.approx(6.4)
    assert cost_usd("mystery-model", 1, 1, 0, 0) is None
    monkeypatch.setattr(settings, "model_prices", {"mystery-model": {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0}})
    assert cost_usd("mystery-model", 1_000_000, 0, 0, 0)["total"] == 1.0


# ---- the four states ----


def _fake_scorer(fn, requires=()):
    return Scorer(
        name="fake", title="Fake", family="test", level="response", kind="verdict", version=1,
        measures="m", how="h", caveat="c", fn=fn, requires=requires,
    )


def test_missing_requirement_locks_with_an_unlock_hint():
    res = run_scorer(_fake_scorer(lambda ctx: scored(1, True), requires=("golden",)), None, set())
    assert res.state == "locked" and "Set the correct answer" in res.reason
    assert run_scorer(_fake_scorer(lambda ctx: scored(1, True), requires=("golden",)), None, {"golden"}).state == "scored"


def test_a_crashing_or_malformed_scorer_is_not_computed_never_zero():
    crash = run_scorer(_fake_scorer(lambda ctx: 1 / 0), None, set())
    assert crash.state == "not_computed" and "ZeroDivisionError" in crash.reason and crash.value is None
    assert run_scorer(_fake_scorer(lambda ctx: 0.5), None, set()).state == "not_computed"
    assert run_scorer(_fake_scorer(lambda ctx: not_applicable("n/a")), None, set()).state == "not_applicable"


# ---- scoring runs ----


def test_every_run_is_scored_as_soon_as_it_exists(client, monkeypatch):
    _, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    s = _by(trial)
    for arm in ("baseline", "configured"):
        assert s[(arm, "completed")]["passed"] is True
        assert s[(arm, "refs_resolve")]["passed"] is True
        assert s[(arm, "unsourced_numbers")]["passed"] is True and s[(arm, "unsourced_numbers")]["value"] == 0
        assert s[(arm, "sql_health")]["passed"] is True and s[(arm, "sql_health")]["details"]["queries"] == 1
        assert s[(arm, "latency")]["state"] == "scored"
        assert s[(arm, "cost")]["value"] == pytest.approx((100 * 4 + 20 * 20) / 1e6)
    agree = s[("", "arms_agree")]
    assert agree["state"] == "scored" and agree["value"] == 1 and agree["passed"] is None  # a signal, not a verdict


def test_a_refused_answer_fails_with_the_reason(client, monkeypatch):
    _, trial = _ask(client, monkeypatch, FakeClaudeCiting(invent=True))
    s = _by(trial)
    refs = s[("configured", "refs_resolve")]
    assert refs["passed"] is False and "ev:000000000000" in refs["reason"]
    assert s[("", "arms_agree")]["state"] == "not_computed"  # nothing resolved to compare


def test_numbers_typed_into_the_answer_are_flagged(client, monkeypatch):
    _, trial = _ask(client, monkeypatch, FakeClaudeWithSQL())  # writes the values instead of citing them
    s = _by(trial)
    assert s[("baseline", "unsourced_numbers")]["passed"] is False
    assert s[("baseline", "refs_resolve")]["state"] == "not_applicable"  # no references to check


def test_an_answer_without_queries_or_numbers(client, monkeypatch):
    _, trial = _ask(client, monkeypatch, FakeClaude())
    s = _by(trial)
    assert s[("baseline", "sql_health")]["state"] == "not_applicable"
    assert s[("baseline", "unsourced_numbers")]["passed"] is True


def test_unpriced_model_is_not_computed_not_zero(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "mystery-model")
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    cost = _by(trial)[("baseline", "cost")]
    assert cost["state"] == "not_computed" and "mystery-model" in cost["reason"] and cost["value"] is None
    row = next(r for r in client.get(f"/api/experiments/{exp['id']}/evals").json()["scorecard"] if r["scorer"] == "cost" and r["arm"] == "baseline")
    assert row["scored"] == 0 and row["not_computed"] == 1 and row["mean"] is None


def test_new_evals_backfill_old_runs_and_versions_replace_results(client, monkeypatch):
    exp, _ = _ask(client, monkeypatch, FakeClaudeCiting())
    monkeypatch.setitem(REGISTRY, "fake", _fake_scorer(lambda ctx: scored(1, True, "added later")))
    trial = client.get(f"/api/experiments/{exp['id']}/trials").json()[0]
    assert _by(trial)[("baseline", "fake")]["reason"] == "added later"  # scored without re-running the model

    monkeypatch.setitem(REGISTRY, "fake", dataclasses.replace(REGISTRY["fake"], version=2, fn=lambda ctx: scored(0, False, "v2")))
    trial = client.get(f"/api/experiments/{exp['id']}/trials").json()[0]
    fakes = [s for s in trial["scores"] if s["scorer"] == "fake"]
    assert {s["scorer_version"] for s in fakes} == {2} and fakes[0]["reason"] == "v2"


def test_scorecard_counts_only_scored_results(client, monkeypatch):
    exp, _ = _ask(client, monkeypatch, FakeClaudeCiting())
    client.post(f"/api/experiments/{exp['id']}/trials", json={"question": "Top customer again?"})
    card = {(r["scorer"], r["arm"]): r for r in client.get(f"/api/experiments/{exp['id']}/evals").json()["scorecard"]}
    refs = card[("refs_resolve", "configured")]
    assert (refs["scored"], refs["judged"], refs["passed"]) == (2, 2, 2)
    assert card[("arms_agree", "")]["mean"] == 1
    assert card[("sql_health", "baseline")]["not_applicable"] == 0
    rescored = client.post(f"/api/experiments/{exp['id']}/evals/rescore").json()
    assert {(r["scorer"], r["arm"]): r["scored"] for r in rescored["scorecard"]} == {k: v["scored"] for k, v in card.items()}


def test_scorers_explain_themselves_and_experiments_still_delete(client, monkeypatch):
    info = client.get("/api/evals/scorers").json()["scorers"]
    assert [s["name"] for s in info] == [
        "completed", "refs_resolve", "unsourced_numbers", "sql_health", "arms_agree", "latency", "cost",
        "expected_numbers", "expected_text", "abstained", "right_columns", "execution_accuracy",
    ]
    assert all(s["requires"] == ["golden"] for s in info[7:])
    assert all(s["measures"] and s["how"] and s["caveat"] for s in info)
    exp, _ = _ask(client, monkeypatch, FakeClaudeCiting())
    assert client.delete(f"/api/experiments/{exp['id']}").status_code == 204
