"""Tests for the dashboard-specific FastAPI endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from agent_arena.api import app
from agent_arena.db import get_session
from agent_arena.models import AgentConfig, ArenaRun


# ---------------------------------------------------------------------------
# Fixtures — engine is shared; each request gets its own Session
# ---------------------------------------------------------------------------


@pytest.fixture(name="db_engine")
def db_engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="client")
def client_fixture(db_engine):
    def override_get_session():
        with Session(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /task-suites
# ---------------------------------------------------------------------------


def test_list_task_suites(client: TestClient, tmp_path: Path, monkeypatch):
    """Returns list of dicts with name, path, task_count."""
    suite_dir = tmp_path / "task_suites"
    suite_dir.mkdir()
    (suite_dir / "my_suite.yaml").write_text(
        "name: my_suite\nversion: '1.0'\ntasks:\n  - id: t1\n    input: hello\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_arena.api.EXAMPLES_DIR", tmp_path)

    resp = client.get("/task-suites")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["name"] == "my_suite"
    assert "path" in item
    assert item["task_count"] == 1


def test_list_task_suites_empty(client: TestClient, tmp_path: Path, monkeypatch):
    """Returns [] when no YAML files exist."""
    monkeypatch.setattr("agent_arena.api.EXAMPLES_DIR", tmp_path)
    resp = client.get("/task-suites")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# /rubrics
# ---------------------------------------------------------------------------


def test_list_rubrics(client: TestClient, tmp_path: Path, monkeypatch):
    """Returns list of dicts with name, path, criterion_count."""
    rubric_dir = tmp_path / "rubrics"
    rubric_dir.mkdir()
    (rubric_dir / "my_rubric.yaml").write_text(
        "name: my_rubric\ncriteria:\n  - name: accuracy\n    weight: 1.0\n    scale: 5\n    description: foo\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_arena.api.EXAMPLES_DIR", tmp_path)

    resp = client.get("/rubrics")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["name"] == "my_rubric"
    assert item["criterion_count"] == 1


def test_list_rubrics_empty(client: TestClient, tmp_path: Path, monkeypatch):
    """Returns [] when directory is missing."""
    monkeypatch.setattr("agent_arena.api.EXAMPLES_DIR", tmp_path)
    resp = client.get("/rubrics")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# DELETE /configs/{config_id}
# ---------------------------------------------------------------------------


def test_delete_config_ok(client: TestClient):
    """Create a config, delete it, assert 204 then gone from list."""
    created = client.post(
        "/configs",
        json={
            "name": "to-delete",
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "system_prompt": "hello",
            "tools": [],
            "params": {},
        },
    )
    assert created.status_code == 200
    config_id = created.json()["id"]

    resp = client.delete(f"/configs/{config_id}")
    assert resp.status_code == 204

    configs_resp = client.get("/configs")
    ids = [c["id"] for c in configs_resp.json()]
    assert config_id not in ids


def test_delete_config_not_found(client: TestClient):
    """DELETE /configs/nonexistent returns 404."""
    resp = client.delete("/configs/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /arena/runs/{arena_id}
# ---------------------------------------------------------------------------


def test_get_arena_run_found(client: TestClient, db_engine):
    """Insert an ArenaRun directly, GET it, assert fields match."""
    run_id = str(uuid.uuid4())
    with Session(db_engine) as session:
        arena_run = ArenaRun(
            id=run_id,
            config_ids=["cfg-1", "cfg-2"],
            task_suite_hash="hash-suite",
            rubric_hash="hash-rubric",
            status="done",
            created_at=datetime.utcnow(),
        )
        session.add(arena_run)
        session.commit()

    resp = client.get(f"/arena/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run_id
    assert data["status"] == "done"
    assert "cfg-1" in data["config_ids"]


def test_get_arena_run_not_found(client: TestClient):
    """GET /arena/runs/bad-id returns 404."""
    resp = client.get("/arena/runs/bad-id-that-does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /arena/demo
# ---------------------------------------------------------------------------


def test_run_demo_seeds_configs(client: TestClient, monkeypatch, tmp_path):
    """POST /arena/demo seeds two configs and returns arena_id."""
    suite_dir = tmp_path / "task_suites"
    suite_dir.mkdir()
    (suite_dir / "customer_support.yaml").write_text(
        "name: customer_support\nversion: '1.0'\ntasks:\n  - id: t1\n    input: How do I return an item?\n",
        encoding="utf-8",
    )
    rubric_dir = tmp_path / "rubrics"
    rubric_dir.mkdir()
    (rubric_dir / "helpfulness.yaml").write_text(
        "name: helpfulness\ncriteria:\n  - name: accuracy\n    description: Is it correct?\n    weight: 1.0\n    scale: 5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_arena.api.EXAMPLES_DIR", tmp_path)

    mock_arena_id = str(uuid.uuid4())
    with patch("agent_arena.api.Arena") as MockArena:
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_arena_id
        MockArena.return_value = mock_instance

        resp = client.post("/arena/demo")

    assert resp.status_code == 200
    data = resp.json()
    assert "arena_id" in data
    assert data["arena_id"] == mock_arena_id

    configs_resp = client.get("/configs")
    names = [c["name"] for c in configs_resp.json()]
    assert "claude-baseline" in names
    assert "claude-cot" in names


def test_run_demo_idempotent(client: TestClient, monkeypatch, tmp_path):
    """Calling POST /arena/demo twice should not duplicate configs."""
    suite_dir = tmp_path / "task_suites"
    suite_dir.mkdir()
    (suite_dir / "customer_support.yaml").write_text(
        "name: customer_support\nversion: '1.0'\ntasks:\n  - id: t1\n    input: hello\n",
        encoding="utf-8",
    )
    rubric_dir = tmp_path / "rubrics"
    rubric_dir.mkdir()
    (rubric_dir / "helpfulness.yaml").write_text(
        "name: helpfulness\ncriteria:\n  - name: accuracy\n    description: ok\n    weight: 1.0\n    scale: 5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agent_arena.api.EXAMPLES_DIR", tmp_path)

    with patch("agent_arena.api.Arena") as MockArena:
        mock_instance = MagicMock()
        mock_instance.run.return_value = str(uuid.uuid4())
        MockArena.return_value = mock_instance
        client.post("/arena/demo")

    with patch("agent_arena.api.Arena") as MockArena:
        mock_instance = MagicMock()
        mock_instance.run.return_value = str(uuid.uuid4())
        MockArena.return_value = mock_instance
        client.post("/arena/demo")

    configs_resp = client.get("/configs")
    names = [c["name"] for c in configs_resp.json()]
    assert names.count("claude-baseline") == 1
    assert names.count("claude-cot") == 1
