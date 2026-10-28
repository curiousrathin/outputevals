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


def test_serves_built_frontend_with_spa_fallback(tmp_path):
    from fastapi import FastAPI

    from app.main import mount_frontend

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path.parent / "secret.txt").write_text("nope")
    spa = FastAPI()
    mount_frontend(spa, tmp_path)
    client = TestClient(spa)

    assert client.get("/").text == "<div id=root></div>"
    assert client.get("/experiments/abc123").text == "<div id=root></div>"  # deep link
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/api/nope").status_code == 404
    assert "nope" not in client.get("/..%2Fsecret.txt").text


def test_no_build_means_no_frontend_routes(tmp_path):
    from fastapi import FastAPI

    from app.main import mount_frontend

    spa = FastAPI()
    mount_frontend(spa, tmp_path)
    assert TestClient(spa).get("/").status_code == 404
