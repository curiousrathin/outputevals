"""Store and resolver tests, ported from OutputTracker's test_phase0 / test_phase1."""

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.evidence import (
    MAX_CITED_CELLS,
    append_evidence,
    citation_block,
    cite_result,
    correct_evidence,
    current_value,
    evidence_id,
    value_history,
)
from app.core.resolver import DraftResolver
from app.models import Evidence

QC_CT = evidence_id("invoices_29", "qc_unowned_ct", {})
QC_REV = evidence_id("invoices_29", "qc_unowned_rev", {"window": "2wk"})
AF12K = evidence_id("invoices_29", "af12k_yoy", {})
MISSING = evidence_id("invoices_29", "allo_unowned", {})


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def seeded(session):
    append_evidence(session, QC_CT, "34 accounts", source="invoices_29")
    append_evidence(session, QC_REV, "$59,852", source="invoices_29")
    append_evidence(session, AF12K, "+23.9%", source="bad_dataset")
    correct_evidence(session, AF12K, "-17.9%", source="external_only")
    return session


# ---- content addressing ----


def test_same_inputs_same_id():
    assert evidence_id("s", "q", {"window": "2wk"}) == evidence_id("s", "q", {"window": "2wk"})


def test_param_order_does_not_change_id():
    assert evidence_id("s", "q", {"a": 1, "b": 2}) == evidence_id("s", "q", {"b": 2, "a": 1})


def test_different_source_different_id():
    assert evidence_id("external_only", "af12k", {}) != evidence_id("with_transfers", "af12k", {})


def test_id_is_stable_and_prefixed():
    ev = evidence_id("s", "q", {})
    assert ev.startswith("ev:") and len(ev) == 15


# ---- append-only ----


def test_correction_appends_and_retains_history(seeded):
    assert current_value(seeded, AF12K) == "-17.9%"
    assert value_history(seeded, AF12K) == ["+23.9%", "-17.9%"]


def test_only_one_current_row_after_corrections(session):
    for v in ("1", "2", "3"):
        correct_evidence(session, QC_CT, v, source="s")
    current = session.exec(
        select(Evidence).where(Evidence.ev_id == QC_CT, Evidence.superseded_by.is_(None))
    ).all()
    assert len(current) == 1 and current[0].value == "3"


def test_value_column_is_never_mutated(session):
    append_evidence(session, QC_CT, "original", source="s")
    correct_evidence(session, QC_CT, "new", source="s")
    first = session.exec(select(Evidence).where(Evidence.ev_id == QC_CT).order_by(Evidence.row_id)).first()
    assert first.value == "original"


def test_recording_the_current_value_again_is_a_no_op(session):
    a = append_evidence(session, QC_CT, "34 accounts", source="s")
    b = append_evidence(session, QC_CT, "34 accounts", source="s")
    assert a.row_id == b.row_id and value_history(session, QC_CT) == ["34 accounts"]


def test_unknown_id_raises(session):
    with pytest.raises(KeyError):
        current_value(session, MISSING)


# ---- draft resolver ----


def test_extract_finds_all_refs_in_order(session):
    d = f"unowned across {{{{{QC_CT}}}}}, worth {{{{{QC_REV}}}}}."
    assert DraftResolver(session).extract_refs(d) == [QC_CT, QC_REV]


def test_extract_returns_empty_on_plain_text(session):
    assert DraftResolver(session).extract_refs("no references here") == []


def test_validate_reports_only_missing_ids(seeded):
    r = DraftResolver(seeded)
    assert r.validate(f"{{{{{QC_CT}}}}} at {{{{{QC_REV}}}}}") == []
    assert r.validate(f"{{{{{QC_CT}}}}} and {{{{{MISSING}}}}}") == [MISSING]


def test_render_substitutes_and_leaves_no_refs(seeded):
    res = DraftResolver(seeded).render(f"unowned across {{{{{QC_CT}}}}}, worth {{{{{QC_REV}}}}}.")
    assert res.ok and res.text == "unowned across 34 accounts, worth $59,852."


def test_render_uses_corrected_value_not_stale(seeded):
    res = DraftResolver(seeded).render(f"AF12K at {{{{{AF12K}}}}} YoY.")
    assert "-17.9%" in res.text and "+23.9%" not in res.text


def test_render_resolves_repeated_reference_everywhere(seeded):
    res = DraftResolver(seeded).render(f"{{{{{QC_CT}}}}} and again {{{{{QC_CT}}}}}")
    assert res.text.count("34 accounts") == 2


def test_render_holds_entirely_on_one_missing_ref(seeded):
    # The load-bearing test: the good ref must not leak through when another is missing.
    res = DraftResolver(seeded).render(f"Quebec {{{{{QC_CT}}}}} but Allo {{{{{MISSING}}}}}")
    assert res.ok is False and res.text is None and res.missing == [MISSING]


# ---- citing query results ----


def test_cite_result_is_deterministic_and_ignores_sql_whitespace():
    a = cite_result("sha", "SELECT 1 AS n", ["n"], [["1"]])
    b = cite_result("sha", "  SELECT 1   AS n ; ", ["n"], [["1"]])
    assert a == b and a[0]["value"] == "1" and a[0]["label"] == 'row 0 · "n"'


def test_cite_result_skips_nulls_and_large_results():
    assert [c["value"] for c in cite_result("s", "q", ["a", "b"], [["x", None]])] == ["x"]
    too_many = [["v"]] * (MAX_CITED_CELLS + 1)
    assert cite_result("s", "q", ["a"], too_many) == []


def test_citation_block_tells_the_model_what_to_do():
    cited = cite_result("s", "q", ["total"], [["400600"]])
    assert f"{{{{{cited[0]['ev_id']}}}}}" in citation_block(cited, truncated=False)
    assert "Aggregate further" in citation_block([], truncated=True)
