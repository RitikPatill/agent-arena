"""Tests for Arena orchestrator."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from agent_arena.arena import Arena, CriterionStats
from agent_arena.models import AgentConfig, ArenaRun, Judgement, Run
from agent_arena.schemas import CriterionConfig, RubricConfig, TaskItem, TaskSuiteConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def two_configs(db_session: Session) -> list[AgentConfig]:
    configs = [
        AgentConfig(
            id=str(uuid.uuid4()),
            name=f"config-{i}",
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            system_prompt="You are helpful.",
        )
        for i in range(2)
    ]
    for c in configs:
        db_session.add(c)
    db_session.commit()
    return configs


@pytest.fixture
def simple_rubric() -> RubricConfig:
    return RubricConfig(
        name="test-rubric",
        criteria=[
            CriterionConfig(name="helpfulness", description="Is helpful?", weight=1.0, scale=5),
            CriterionConfig(name="accuracy", description="Is accurate?", weight=1.0, scale=5),
        ],
        content_hash="rubric-hash-abc",
    )


@pytest.fixture
def simple_suite() -> TaskSuiteConfig:
    return TaskSuiteConfig(
        name="test-suite",
        tasks=[
            TaskItem(id="task-1", input="What is 1+1?", reference="2"),
            TaskItem(id="task-2", input="What is 2+2?", reference="4"),
        ],
        content_hash="suite-hash-xyz",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_weighted_score_normalised(db_session: Session, simple_rubric: RubricConfig):
    """Weighted score must be in [0, 1]."""
    arena = Arena(db_session)
    run_id = str(uuid.uuid4())
    judgements = [
        Judgement(run_id=run_id, rubric_id="r", criterion="helpfulness", score=3.0, justification="ok", judge_model="m"),
        Judgement(run_id=run_id, rubric_id="r", criterion="accuracy", score=5.0, justification="great", judge_model="m"),
    ]
    score = arena._weighted_score(judgements, simple_rubric.criteria)
    assert 0.0 <= score <= 1.0
    # helpfulness: 3/5 * 1.0, accuracy: 5/5 * 1.0; total_weight = 2.0 -> (0.6+1.0)/2 = 0.8
    assert abs(score - 0.8) < 1e-9


def test_bootstrap_ci_contains_true_mean(db_session: Session):
    """Bootstrap CI should contain the true mean for a constant series."""
    arena = Arena(db_session)
    values = [0.5] * 100
    ci_low, ci_high = arena._bootstrap_ci(values)
    assert ci_low <= 0.5 <= ci_high


def test_win_rates_sum_to_one(db_session: Session, two_configs: list[AgentConfig], simple_rubric: RubricConfig):
    """For two configs with no ties, win_rates[a][b] + win_rates[b][a] == 1.0."""
    arena = Arena(db_session)
    a_id, b_id = two_configs[0].id, two_configs[1].id

    # Manufacture runs and judgements so config-0 always beats config-1
    task_id = "task-1"
    for config, score in [(two_configs[0], 5.0), (two_configs[1], 1.0)]:
        run = Run(
            id=str(uuid.uuid4()),
            config_id=config.id,
            task_id=task_id,
            output="answer",
            status="done",
            started_at=datetime.utcnow(),
        )
        db_session.add(run)
        db_session.commit()
        for crit in simple_rubric.criteria:
            j = Judgement(
                run_id=run.id,
                rubric_id=simple_rubric.content_hash,
                criterion=crit.name,
                score=score,
                justification="test",
                judge_model="test-model",
            )
            db_session.add(j)
        db_session.commit()

    runs = db_session.query(Run).all()
    judgements = db_session.query(Judgement).all()
    results = arena._aggregate(
        ArenaRun(
            id=str(uuid.uuid4()),
            config_ids=[a_id, b_id],
            task_suite_hash="s",
            rubric_hash="r",
            status="done",
        ),
        runs,
        judgements,
        two_configs,
        simple_rubric.criteria,
    )

    assert abs(results.win_rates[a_id][b_id] + results.win_rates[b_id][a_id] - 1.0) < 1e-9
    # config-0 has higher score → it should win
    assert results.win_rates[a_id][b_id] > results.win_rates[b_id][a_id]


def test_arena_run_end_to_end(
    db_session: Session,
    two_configs: list[AgentConfig],
    simple_rubric: RubricConfig,
    simple_suite: TaskSuiteConfig,
    mocker,
):
    """Arena.run + Arena.get_results should produce an ArenaResults with correct shape."""
    # Mock AgentRunner.run to return a synthetic done Run
    def _fake_runner_run(self, task):
        run = Run(
            id=str(uuid.uuid4()),
            config_id=self.config.id,
            task_id=task.id,
            output="fake output",
            status="done",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )
        db_session.add(run)
        db_session.commit()
        return run

    mocker.patch("agent_arena.runner.AgentRunner.run", _fake_runner_run)

    # Mock Judge.judge_run to return fixed Judgements
    def _fake_judge_run(self, run, task_input, reference, rubric):
        judgements = []
        for crit in rubric.criteria:
            j = Judgement(
                run_id=run.id,
                rubric_id=rubric.content_hash,
                criterion=crit.name,
                score=4.0,
                justification="mocked",
                judge_model=self.judge_model,
            )
            db_session.add(j)
            judgements.append(j)
        db_session.commit()
        return judgements

    mocker.patch("agent_arena.judge.Judge.judge_run", _fake_judge_run)

    arena = Arena(db_session)
    arena_id = arena.run(
        configs=two_configs,
        task_suite=simple_suite,
        rubric=simple_rubric,
        judge_model="claude-haiku-4-5-20251001",
        judge_provider="anthropic",
        max_turns=5,
    )

    assert arena_id is not None

    results = arena.get_results(arena_id)

    assert results.arena_id == arena_id
    assert set(results.config_ids) == {c.id for c in two_configs}
    # Should have per-task entries for each task
    assert set(results.per_task.keys()) == {"task-1", "task-2"}
    # Each config should appear in per_task
    for task_scores in results.per_task.values():
        for config in two_configs:
            assert config.id in task_scores
    # win_rates should be a complete matrix
    for a in two_configs:
        for b in two_configs:
            assert b.id in results.win_rates[a.id]
