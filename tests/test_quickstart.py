"""Tests for examples/quickstart.py."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from agent_arena.models import AgentConfig, Judgement, Run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_db(tmp_path, monkeypatch):
    """Set up an in-memory SQLite DB and point ARENA_DB_URL at it."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("ARENA_DB_URL", db_url)
    # Re-import db module to pick up new URL
    import importlib
    import agent_arena.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    return db_mod.engine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_quickstart_runs_with_mocked_llm(mocker, tmp_path, monkeypatch):
    """main() should complete without raising when LLM calls are mocked."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("ARENA_DB_URL", db_url)

    # Reload db module so it picks up the new env var
    import importlib
    import agent_arena.db as db_mod
    importlib.reload(db_mod)

    # Patch AgentRunner.run to return a fake completed Run
    def _fake_runner_run(self, task):
        run = Run(
            id=str(uuid.uuid4()),
            config_id=self.config.id,
            task_id=task.id,
            output="Here is a helpful answer.",
            status="done",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            arena_run_id=self.arena_run_id,
        )
        self.session.add(run)
        self.session.commit()
        return run

    mocker.patch("agent_arena.runner.AgentRunner.run", _fake_runner_run)

    # Patch Judge.judge_run to return fixed Judgements (score=4 per criterion)
    def _fake_judge_run(self, run, task_input, reference, rubric):
        judgements = []
        for crit in rubric.criteria:
            j = Judgement(
                run_id=run.id,
                rubric_id=rubric.content_hash,
                criterion=crit.name,
                score=4.0,
                justification="mocked justification",
                judge_model=self.judge_model,
            )
            self.session.add(j)
            judgements.append(j)
        self.session.commit()
        return judgements

    mocker.patch("agent_arena.judge.Judge.judge_run", _fake_judge_run)

    # Import and run quickstart's main()
    import sys
    repo_root = Path(__file__).resolve().parent.parent
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Import quickstart from examples/
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "quickstart",
        repo_root / "examples" / "quickstart.py",
    )
    quickstart = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(quickstart)

    # Should not raise
    quickstart.main(n_tasks=2)


def test_quickstart_exits_without_api_key(monkeypatch, tmp_path):
    """main() should sys.exit(1) if ANTHROPIC_API_KEY is not set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ARENA_DB_URL", f"sqlite:///{tmp_path}/test.db")

    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "quickstart_nokey",
        repo_root / "examples" / "quickstart.py",
    )
    quickstart = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(quickstart)

    with pytest.raises(SystemExit) as exc_info:
        quickstart.main(n_tasks=1)

    assert exc_info.value.code == 1


def test_build_configs_idempotent(monkeypatch, tmp_path):
    """_build_configs() should not duplicate configs when called twice."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    db_url = f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("ARENA_DB_URL", db_url)

    import importlib
    import agent_arena.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    import sys
    from pathlib import Path
    from sqlmodel import Session, select

    repo_root = Path(__file__).resolve().parent.parent
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "quickstart_idem",
        repo_root / "examples" / "quickstart.py",
    )
    quickstart = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(quickstart)

    with Session(db_mod.engine) as session:
        quickstart._build_configs(session)
        quickstart._build_configs(session)  # second call must not create duplicates

        configs = session.exec(
            select(AgentConfig).where(
                AgentConfig.name.in_(["quickstart-baseline", "quickstart-cot"])
            )
        ).all()

    assert len(configs) == 2, f"Expected 2 configs, got {len(configs)}"
