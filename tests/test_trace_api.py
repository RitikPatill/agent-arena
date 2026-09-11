"""Tests for the M7 trace-viewer API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from agent_arena.api import app
from agent_arena.db import get_session
from agent_arena.models import AgentConfig, Judgement, Run, Span


# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture(name="seeded_config")
def seeded_config_fixture(db_engine) -> AgentConfig:
    with Session(db_engine) as session:
        config = AgentConfig(
            id=str(uuid.uuid4()),
            name="test-config",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            system_prompt="You are helpful.",
            tools=[],
            params={},
        )
        session.add(config)
        session.commit()
        session.refresh(config)
        return config


@pytest.fixture(name="seeded_run")
def seeded_run_fixture(db_engine, seeded_config) -> Run:
    with Session(db_engine) as session:
        run = Run(
            id=str(uuid.uuid4()),
            arena_run_id=str(uuid.uuid4()),
            config_id=seeded_config.id,
            task_id="task-1",
            status="done",
            started_at=datetime.utcnow(),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run


@pytest.fixture(name="seeded_run_with_spans")
def seeded_run_with_spans_fixture(db_engine, seeded_config) -> Run:
    with Session(db_engine) as session:
        run = Run(
            id=str(uuid.uuid4()),
            arena_run_id=str(uuid.uuid4()),
            config_id=seeded_config.id,
            task_id="task-2",
            status="done",
            started_at=datetime.utcnow(),
        )
        session.add(run)
        session.flush()

        span1 = Span(
            id=str(uuid.uuid4()),
            run_id=run.id,
            kind="llm",
            name="chat_completion",
            input='{"messages": []}',
            output='{"text": "hello"}',
            latency_ms=100,
            tokens=50,
        )
        span2 = Span(
            id=str(uuid.uuid4()),
            run_id=run.id,
            kind="tool",
            name="calculator",
            input='{"expr": "1+1"}',
            output='{"result": 2}',
            latency_ms=5,
            tokens=None,
        )
        span3 = Span(
            id=str(uuid.uuid4()),
            run_id=run.id,
            kind="llm",
            name="chat_completion",
            input='{"messages": [{"role": "user", "content": "ok"}]}',
            output='{"text": "done"}',
            latency_ms=80,
            tokens=30,
        )
        session.add_all([span1, span2, span3])
        session.commit()
        session.refresh(run)
        return run


@pytest.fixture(name="seeded_run_with_judgements")
def seeded_run_with_judgements_fixture(db_engine, seeded_config) -> Run:
    with Session(db_engine) as session:
        run = Run(
            id=str(uuid.uuid4()),
            arena_run_id=str(uuid.uuid4()),
            config_id=seeded_config.id,
            task_id="task-3",
            status="done",
            started_at=datetime.utcnow(),
        )
        session.add(run)
        session.flush()

        j1 = Judgement(
            id=str(uuid.uuid4()),
            run_id=run.id,
            rubric_id="rubric-hash-abc",
            criterion="helpfulness",
            score=4.0,
            justification="Very helpful response.",
            judge_model="claude-haiku-4-5-20251001",
        )
        j2 = Judgement(
            id=str(uuid.uuid4()),
            run_id=run.id,
            rubric_id="rubric-hash-abc",
            criterion="accuracy",
            score=3.5,
            justification="Mostly accurate.",
            judge_model="claude-haiku-4-5-20251001",
        )
        session.add_all([j1, j2])
        session.commit()
        session.refresh(run)
        return run


@pytest.fixture(name="seeded_arena")
def seeded_arena_fixture(db_engine, seeded_config) -> Run:
    """Returns the first of two runs sharing the same arena_run_id."""
    arena_run_id = str(uuid.uuid4())
    with Session(db_engine) as session:
        run1 = Run(
            id=str(uuid.uuid4()),
            arena_run_id=arena_run_id,
            config_id=seeded_config.id,
            task_id="task-a",
            status="done",
            started_at=datetime.utcnow(),
        )
        run2 = Run(
            id=str(uuid.uuid4()),
            arena_run_id=arena_run_id,
            config_id=seeded_config.id,
            task_id="task-b",
            status="done",
            started_at=datetime.utcnow(),
        )
        session.add_all([run1, run2])
        session.commit()
        session.refresh(run1)
        # Attach arena_id to run1 for use in tests
        run1.arena_run_id = arena_run_id  # type: ignore[misc]
        return run1


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------


def test_get_run_not_found(client: TestClient):
    r = client.get("/runs/nonexistent-id")
    assert r.status_code == 404


def test_get_run_found(client: TestClient, seeded_run: Run):
    r = client.get(f"/runs/{seeded_run.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == seeded_run.id
    assert data["task_id"] == "task-1"
    assert data["config_name"] == "test-config"
    assert data["status"] == "done"


def test_get_run_config_name_fallback(client: TestClient, db_engine):
    """When config is deleted, config_name falls back to config_id[:8]."""
    orphan_config_id = str(uuid.uuid4())
    with Session(db_engine) as session:
        run = Run(
            id=str(uuid.uuid4()),
            config_id=orphan_config_id,
            task_id="task-orphan",
            status="done",
            started_at=datetime.utcnow(),
        )
        session.add(run)
        session.commit()
        run_id = run.id

    r = client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["config_name"] == orphan_config_id[:8]


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/spans
# ---------------------------------------------------------------------------


def test_get_run_spans_empty(client: TestClient, seeded_run: Run):
    r = client.get(f"/runs/{seeded_run.id}/spans")
    assert r.status_code == 200
    assert r.json() == []


def test_get_run_spans_returns_in_order(
    client: TestClient, seeded_run_with_spans: Run
):
    r = client.get(f"/runs/{seeded_run_with_spans.id}/spans")
    assert r.status_code == 200
    spans = r.json()
    assert len(spans) == 3
    assert spans[0]["kind"] == "llm"
    assert spans[1]["kind"] == "tool"
    assert spans[2]["kind"] == "llm"


def test_get_run_spans_fields(client: TestClient, seeded_run_with_spans: Run):
    r = client.get(f"/runs/{seeded_run_with_spans.id}/spans")
    span = r.json()[0]
    assert all(k in span for k in ("id", "run_id", "kind", "name", "input", "output", "latency_ms", "tokens"))


def test_get_run_spans_not_found(client: TestClient):
    r = client.get("/runs/missing-run/spans")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/judgements
# ---------------------------------------------------------------------------


def test_get_run_judgements(client: TestClient, seeded_run_with_judgements: Run):
    r = client.get(f"/runs/{seeded_run_with_judgements.id}/judgements")
    assert r.status_code == 200
    j = r.json()
    assert len(j) == 2
    assert all("criterion" in x and "score" in x and "justification" in x for x in j)


def test_get_run_judgements_empty(client: TestClient, seeded_run: Run):
    r = client.get(f"/runs/{seeded_run.id}/judgements")
    assert r.status_code == 200
    assert r.json() == []


def test_get_run_judgements_not_found(client: TestClient):
    r = client.get("/runs/missing-run/judgements")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /arena/{arena_id}/runs
# ---------------------------------------------------------------------------


def test_get_arena_runs(client: TestClient, seeded_arena: Run):
    arena_id = seeded_arena.arena_run_id
    r = client.get(f"/arena/{arena_id}/runs")
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 2
    assert all("config_name" in x for x in runs)
    assert all(x["config_name"] == "test-config" for x in runs)


def test_get_arena_runs_not_found(client: TestClient):
    r = client.get("/arena/nonexistent-arena/runs")
    assert r.status_code == 404
