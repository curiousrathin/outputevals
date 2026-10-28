import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401
from app.config import settings
from app.db import get_session
from app.main import app
from tests.test_workflow import CSV, FakeClaude

DEFS = "# Definitions\n\nRevenue = amount, before tax."


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "library_dir", None)
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


def _write(client, path, content):
    return client.put("/api/library/file", json={"path": path, "content": content})


def _config(client, attachments):
    ds = client.post("/api/datasets", files={"file": ("invoices.csv", CSV, "text/csv")}).json()
    return client.post(
        "/api/configurations",
        json={"name": "c", "dataset_id": ds["id"], "attachments": attachments},
    )


# ---- files and folders ----


def test_files_and_folders_round_trip(client):
    assert client.post("/api/library/folder", json={"path": "sales"}).status_code == 204
    assert _write(client, "sales/definitions.md", DEFS).status_code == 200
    assert _write(client, "sales/notes.txt", "plain text").status_code == 200

    tree = client.get("/api/library/tree").json()
    assert tree[0]["path"] == "sales" and tree[0]["type"] == "folder"
    assert [c["name"] for c in tree[0]["children"]] == ["definitions.md", "notes.txt"]
    assert client.get("/api/library/file", params={"path": "sales/definitions.md"}).json()[
        "content"
    ] == DEFS


@pytest.mark.parametrize(
    "path", ["../escape.md", "/etc/passwd.md", ".git/config.md", "sales/../../x.md", ""]
)
def test_paths_cannot_leave_the_library(client, path):
    assert _write(client, path, "x").status_code == 422


def test_only_markdown_and_text(client):
    assert _write(client, "script.py", "print(1)").status_code == 422


def test_symlinks_are_ignored(client, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    (tmp_path / "library").mkdir(exist_ok=True)
    (tmp_path / "library" / "link.md").symlink_to(outside)
    assert client.get("/api/library/tree").json() == []
    assert client.get("/api/library/file", params={"path": "link.md"}).status_code == 422


def test_only_empty_folders_can_be_deleted(client):
    _write(client, "sales/definitions.md", DEFS)
    assert client.delete("/api/library/item", params={"path": "sales"}).status_code == 422
    assert client.delete("/api/library/item", params={"path": "sales/definitions.md"}).status_code == 204
    assert client.delete("/api/library/item", params={"path": "sales"}).status_code == 204
    assert client.get("/api/library/tree").json() == []


# ---- attachments ----


def test_folder_attachment_resolves_at_run_time(client):
    _write(client, "sales/definitions.md", DEFS)
    _write(client, "style/deck.md", "# Deck style")
    config = _config(client, ["sales"]).json()
    assert config["attachments"] == ["sales"]
    assert '<file path="sales/definitions.md">' in config["prompt_preview"]
    assert "Deck style" not in config["prompt_preview"]  # only what's attached

    _write(client, "sales/approvals.md", "Invoices over 4000 need two approvals.")
    preview = client.get(f"/api/configurations/{config['id']}").json()["prompt_preview"]
    assert "two approvals" in preview  # new file in an attached folder is picked up


def test_cannot_attach_what_does_not_exist(client):
    assert _config(client, ["nope.md"]).status_code == 422


def test_attached_items_cannot_be_deleted(client):
    _write(client, "sales/definitions.md", DEFS)
    _config(client, ["sales/definitions.md"])
    resp = client.delete("/api/library/item", params={"path": "sales/definitions.md"})
    assert resp.status_code == 409 and "attached" in resp.json()["detail"]


def test_missing_attachment_fails_the_run_instead_of_skipping(client, tmp_path, monkeypatch):
    _write(client, "sales/definitions.md", DEFS)
    config = _config(client, ["sales/definitions.md"]).json()
    (tmp_path / "library" / "sales" / "definitions.md").unlink()  # removed outside the app

    assert "no longer exists" in client.get(f"/api/configurations/{config['id']}").json()[
        "attachment_error"
    ]
    exp = client.post("/api/experiments", json={"name": "e", "configuration_id": config["id"]}).json()
    monkeypatch.setattr("app.api.experiments.get_client", lambda: FakeClaude())
    resp = client.post(f"/api/experiments/{exp['id']}/trials", json={"question": "Q"})
    assert resp.status_code == 422 and "no longer exists" in resp.json()["detail"]


def test_trials_record_file_hashes_and_versions_track_edits(client, monkeypatch):
    _write(client, "sales/definitions.md", DEFS)
    config = _config(client, ["sales"]).json()
    exp = client.post("/api/experiments", json={"name": "e", "configuration_id": config["id"]}).json()
    monkeypatch.setattr("app.api.experiments.get_client", lambda: FakeClaude())

    def ask():
        return client.post(f"/api/experiments/{exp['id']}/trials", json={"question": "Q"}).json()

    first = ask()
    baseline, configured = first["responses"]
    assert "Revenue = amount" in configured["system_prompt"]
    assert "Revenue = amount" not in baseline["system_prompt"]
    assert [f["path"] for f in first["library_files"]] == ["sales/definitions.md"]

    _write(client, "sales/definitions.md", DEFS + "\nDates are M/D/YYYY.")
    second = ask()
    assert second["library_files"][0]["sha256"] != first["library_files"][0]["sha256"]
    assert second["config_version"] != first["config_version"]  # an edit is a new version
