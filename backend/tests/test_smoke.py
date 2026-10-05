from fastapi.testclient import TestClient

from app.core.ledger import build_snapshot
from app.main import app


def test_health():
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_snapshot_hashes():
    kwargs = {
        "function_name": "answer_query",
        "inputs": {"query": "How much does Acme owe?", "context": ["Invoice 1042: 5,000 USD"]},
        "outputs": {"response": "5,000 USD"},
        "model": "claude-opus-5-5",
        "params": {"temperature": 0.2},
    }
    a, b = build_snapshot(**kwargs), build_snapshot(**kwargs)
    assert a.content_hash() == b.content_hash()
    assert len(a.content_hash()) == 64

    # Different answer to the same question: same fingerprint (drift group),
    # different content_hash (distinct trace).
    c = build_snapshot(**{**kwargs, "outputs": {"response": "6,000 USD"}})
    assert c.fingerprint() == a.fingerprint()
    assert c.content_hash() != a.content_hash()
