from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401
from app.config import settings
from app.db import get_session
from app.main import app

CSV = b"invoice_id,customer,amount,approved_by\n1042,Acme Corp,5000,E17\n1043,Globex,1200,E09\n"


class FakeClaude:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        configured = len(kwargs["system"]) > 1
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(
                    type="text", text="configured answer" if configured else "baseline answer"
                ),
            ],
            stop_reason="end_turn",
            stop_details=None,
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=20,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
        )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_csv_to_arena(client, monkeypatch):
    # 1. Ingest
    resp = client.post("/api/datasets", files={"file": ("invoices.csv", CSV, "text/csv")})
    assert resp.status_code == 200, resp.text
    dataset = resp.json()
    assert dataset["row_count"] == 2
    assert [c["name"] for c in dataset["columns"]] == [
        "invoice_id",
        "customer",
        "amount",
        "approved_by",
    ]
    assert client.get(f"/api/datasets/{dataset['id']}/preview").json()["rows"][0][1] == "Acme Corp"

    # 2. Configure: describe a field, connect two fields, add context
    resp = client.post(
        "/api/configurations",
        json={
            "name": "Invoice semantics",
            "dataset_id": dataset["id"],
            "nodes": [{"id": "amount", "description": "Invoice total in USD"}],
            "edges": [
                {
                    "source": "approved_by",
                    "target": "invoice_id",
                    "description": "Employee who approved the invoice",
                }
            ],
            "context_markdown": "# Policy\nInvoices over 4000 need two approvals.",
        },
    )
    assert resp.status_code == 200, resp.text
    config = resp.json()
    assert len(config["nodes"]) == 4  # every column becomes a node
    assert "Invoice total in USD" in config["prompt_preview"]
    assert "two approvals" in config["prompt_preview"]

    # 3. Experiment
    exp = client.post(
        "/api/experiments", json={"name": "Invoice QA", "configuration_id": config["id"]}
    ).json()
    assert exp["dataset_name"] == "invoices"

    # 4. Arena
    fake = FakeClaude()
    monkeypatch.setattr("app.api.experiments.get_client", lambda: fake)
    resp = client.post(
        f"/api/experiments/{exp['id']}/trials", json={"question": "Who owes the most?"}
    )
    assert resp.status_code == 200, resp.text
    trial = resp.json()
    baseline, configured = trial["responses"]
    assert (baseline["arm"], configured["arm"]) == ("baseline", "configured")
    assert baseline["output"] == "baseline answer"
    assert configured["output"] == "configured answer"

    # The baseline sees the original CSV and nothing from the configuration.
    assert "Acme Corp" in baseline["system_prompt"]
    assert "Invoice total in USD" not in baseline["system_prompt"]
    assert "two approvals" not in baseline["system_prompt"]
    assert "two approvals" in configured["system_prompt"]

    # Both arms share an identical, cacheable CSV prefix.
    sys_b, sys_c = (call["system"] for call in fake.calls)
    assert sys_b[0] == sys_c[0] and "cache_control" in sys_b[0]
    assert all(call["model"] == settings.llm_model for call in fake.calls)

    # Traces are fingerprinted; same question but different context -> different traces.
    assert baseline["content_hash"] != configured["content_hash"]

    # 5. Human preference + open-coding note
    resp = client.patch(
        f"/api/trials/{trial['id']}",
        json={"preference": "configured", "note": "Baseline ignored approvals"},
    )
    assert resp.json()["preference"] == "configured"
    assert client.get(f"/api/experiments/{exp['id']}").json()["trial_count"] == 1


def test_rejects_bad_uploads(client):
    assert (
        client.post(
            "/api/datasets", files={"file": ("x.txt", b"a,b\n1,2", "text/plain")}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/datasets", files={"file": ("x.csv", b"", "text/csv")}).status_code == 422
    )


def test_config_validation(client):
    ds = client.post("/api/datasets", files={"file": ("i.csv", CSV, "text/csv")}).json()
    base = {"name": "c", "dataset_id": ds["id"]}
    bad_edge = {**base, "edges": [{"source": "amount", "target": "nope", "description": "x"}]}
    assert client.post("/api/configurations", json=bad_edge).status_code == 422
    blank = {**base, "edges": [{"source": "amount", "target": "customer", "description": " "}]}
    assert client.post("/api/configurations", json=blank).status_code == 422
    self_loop = {**base, "edges": [{"source": "amount", "target": "amount", "description": "x"}]}
    assert client.post("/api/configurations", json=self_loop).status_code == 422


class FakeClaudeWithSQL:
    """Runs one query_data call, then answers using the query result."""

    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(
            input_tokens=50,
            output_tokens=10,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        last = kwargs["messages"][-1]
        if isinstance(last["content"], str):  # first turn: ask for data
            sql = (
                "SELECT customer, SUM(amount) AS total FROM data GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
            )
            block = SimpleNamespace(
                type="tool_use", id="tu_1", name="query_data", input={"sql": sql}
            )
            return SimpleNamespace(
                content=[block], stop_reason="tool_use", stop_details=None, usage=usage
            )
        result = last["content"][0]["content"]
        text = SimpleNamespace(type="text", text=f"Top customer: {result.splitlines()[1]}")
        return SimpleNamespace(
            content=[text], stop_reason="end_turn", stop_details=None, usage=usage
        )


def test_large_csv_uses_sql_mode(client, monkeypatch):
    monkeypatch.setattr("app.core.datasets.MAX_INLINE_TOKENS", 0)  # force query mode
    rows = "\n".join(f"{i},Customer {i % 5},{i}" for i in range(2000))
    csv = f"invoice_id,customer,amount\n{rows}\n".encode()
    ds = client.post("/api/datasets", files={"file": ("big.csv", csv, "text/csv")}).json()
    cfg = client.post("/api/configurations", json={"name": "c", "dataset_id": ds["id"]}).json()
    exp = client.post("/api/experiments", json={"name": "e", "configuration_id": cfg["id"]}).json()

    fake = FakeClaudeWithSQL()
    monkeypatch.setattr("app.api.experiments.get_client", lambda: fake)
    trial = client.post(
        f"/api/experiments/{exp['id']}/trials", json={"question": "Top customer?"}
    ).json()

    for r in trial["responses"]:
        assert r["mode"] == "query" and r["error"] is None
        assert r["output"].startswith("Top customer: Customer 4,")  # computed over all 2000 rows
        assert len(r["tool_calls"]) == 1 and r["tool_calls"][0]["row_count"] == 1
        assert r["input_tokens"] == 100  # usage summed across both turns
        # Prompt has the schema and a sample, not all 2000 rows
        assert '"customer" VARCHAR' in r["system_prompt"]
        assert "1999,Customer 4" not in r["system_prompt"]
    assert all(call["tools"][0]["name"] == "query_data" for call in fake.calls)
