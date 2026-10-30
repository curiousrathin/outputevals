"""Golden cases (eval step 2): drafting from a run, exact matching, re-scoring, and the reference evals."""

import pytest

from app.core.golden import columns_used, question_key
from tests.test_evals import _ask, _by
from tests.test_workflow import FakeClaude, FakeClaudeCiting, FakeClaudeWithSQL

REFERENCE = ["expected_numbers", "expected_text", "abstained", "right_columns", "execution_accuracy"]
TOP_SQL = "SELECT customer, SUM(amount) AS total FROM data GROUP BY 1 ORDER BY 2 DESC LIMIT 1"


def _golden(client, trial, **overrides):
    body = {
        "trial_id": trial["id"], "question": trial["question"], "answerable": True,
        "expected_values": ["Customer 4", "400600"], "expected_columns": ["customer", "amount"],
        "reference_sql": TOP_SQL, "category": "aggregation", **overrides,
    }
    return client.post("/api/golden", json=body)


def _trial(client, exp_id):
    return client.get(f"/api/experiments/{exp_id}/trials").json()[0]


# ---- helpers ----


def test_question_key_ignores_case_spacing_and_trailing_punctuation():
    assert question_key("  Top   Customer? ") == question_key("top customer") == "top customer"
    assert question_key("Top customer in July") != question_key("Top customer in June")


def test_columns_used_reads_quoted_and_simple_bare_names():
    cols = ["customer", "amount", "Untaxed Total", "Date"]
    sql = 'SELECT customer, SUM("Untaxed Total") FROM data WHERE DATE \'2026-07-01\' < now()'
    assert columns_used(sql, cols) == ["customer", "Untaxed Total"]  # bare DATE is SQL, not the column


# ---- before a golden case exists ----


def test_reference_evals_are_locked_with_the_unlock_hint(client, monkeypatch):
    _, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    s = _by(trial)
    for name in REFERENCE:
        assert s[("configured", name)]["state"] == "locked"
        assert "Set the correct answer" in s[("configured", name)]["reason"]


def test_draft_infers_values_columns_and_query_from_the_run(client, monkeypatch):
    _, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    draft = client.get(f"/api/trials/{trial['id']}/golden-draft", params={"arm": "configured"}).json()
    assert draft["expected_values"] == ["Customer 4", "400600"]
    assert draft["expected_columns"] == ["customer", "amount"]
    assert draft["reference_sql"] == TOP_SQL
    assert draft["answerable"] is True and draft["category"] == "aggregation"
    assert draft["dataset_columns"] == ["invoice_id", "customer", "amount"]


# ---- with a golden case ----


def test_setting_the_answer_unlocks_and_scores_past_runs(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    case = _golden(client, trial).json()
    assert case["linked_runs"] == 1 and case["version"] == 1 and len(case["dataset_sha"]) == 64

    s = _by(_trial(client, exp["id"]))  # re-scored from the stored trace, no model call
    for arm in ("baseline", "configured"):
        assert s[(arm, "expected_numbers")]["passed"] is True
        assert s[(arm, "expected_text")]["passed"] is True
        assert s[(arm, "right_columns")]["passed"] is True
        assert s[(arm, "execution_accuracy")]["passed"] is True
        assert s[(arm, "abstained")]["state"] == "not_applicable"  # the question has an answer


def test_new_runs_of_the_same_question_match_exactly_never_similar(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting(), question="Top customer?")
    case = _golden(client, trial).json()
    client.post(f"/api/experiments/{exp['id']}/trials", json={"question": "TOP   customer"})
    client.post(f"/api/experiments/{exp['id']}/trials", json={"question": "Top customer in June?"})
    trials = {t["question"]: t for t in client.get(f"/api/experiments/{exp['id']}/trials").json()}
    assert trials["TOP   customer"]["golden_case_id"] == case["id"]
    assert trials["Top customer in June?"]["golden_case_id"] == ""
    assert _by(trials["Top customer in June?"])[("configured", "expected_numbers")]["state"] == "locked"


def test_wrong_numbers_and_wrong_columns_fail_with_reasons(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    _golden(client, trial, expected_values=["Customer 4", "999999"], expected_columns=["customer", "invoice_id"],
            reference_sql="SELECT COUNT(*) FROM data")
    s = _by(_trial(client, exp["id"]))[("configured", "expected_numbers")]
    assert s["passed"] is False and "999999" in s["reason"]
    cols = _by(_trial(client, exp["id"]))[("configured", "right_columns")]
    assert cols["passed"] is False and cols["value"] == 0.5 and "invoice_id" in cols["reason"]
    assert _by(_trial(client, exp["id"]))[("configured", "execution_accuracy")]["passed"] is False


def test_tolerance_decides_close_numbers(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    case = _golden(client, trial, expected_values=["400700"], tolerance=0.001).json()  # 400600 is 0.025% off
    assert _by(_trial(client, exp["id"]))[("configured", "expected_numbers")]["passed"] is True
    client.put(f"/api/golden/{case['id']}", json={**case, "tolerance": 0.0001})
    assert _by(_trial(client, exp["id"]))[("configured", "expected_numbers")]["passed"] is False


def test_editing_bumps_the_version_and_regrades(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    case = _golden(client, trial, expected_values=["Customer 3"]).json()
    first = _by(_trial(client, exp["id"]))[("configured", "expected_text")]
    assert first["passed"] is False and first["details"]["golden_version"] == 1

    case = client.put(f"/api/golden/{case['id']}", json={**case, "expected_values": ["Customer 4"]}).json()
    again = _by(_trial(client, exp["id"]))[("configured", "expected_text")]
    assert case["version"] == 2 and again["passed"] is True and again["details"]["golden_version"] == 2


def test_unanswerable_questions_grade_honesty(client, monkeypatch):
    _, trial = _ask(client, monkeypatch, FakeClaude())  # answers "baseline answer" with no numbers or decline
    case = _golden(client, trial, answerable=False, expected_values=[], expected_columns=[], reference_sql="").json()
    assert case["category"] == "unanswerable"
    s = _by(client.get(f"/api/experiments/{trial['experiment_id']}/trials").json()[0])
    assert s[("baseline", "abstained")]["passed"] is False  # no numbers, but never said it can't answer
    assert s[("baseline", "expected_numbers")]["state"] == "not_applicable"


def test_typed_numbers_still_count_for_correctness(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeWithSQL())  # types "Customer 4,400600"
    _golden(client, trial, expected_values=["Customer 4"], expected_columns=[], reference_sql="")
    s = _by(_trial(client, exp["id"]))
    assert s[("baseline", "expected_text")]["passed"] is True
    assert s[("baseline", "unsourced_numbers")]["passed"] is False  # grounding is graded separately


def test_deleting_a_case_locks_its_runs_again(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    case = _golden(client, trial).json()
    assert client.delete(f"/api/golden/{case['id']}").status_code == 204
    t = _trial(client, exp["id"])
    assert t["golden_case_id"] == "" and _by(t)[("configured", "expected_numbers")]["state"] == "locked"


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"expected_values": []}, 422),  # answerable but nothing to check
        ({"expected_columns": ["nope"]}, 422),  # not a column
        ({"tolerance": 0.9}, 422),
    ],
)
def test_golden_validation(client, monkeypatch, overrides, status):
    _, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    assert _golden(client, trial, **overrides).status_code == status


def test_one_case_per_question_and_datasets_keep_their_cases(client, monkeypatch):
    exp, trial = _ask(client, monkeypatch, FakeClaudeCiting())
    assert _golden(client, trial).status_code == 200
    assert _golden(client, trial).status_code == 409
    listed = client.get(f"/api/datasets/{exp['dataset_id']}/golden").json()
    assert len(listed) == 1 and listed[0]["linked_runs"] == 1
