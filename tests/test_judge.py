"""Tests for the Judge class."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine

from agent_arena.judge import Judge
from agent_arena.models import AgentConfig, Judgement, Run
from agent_arena.schemas import CriterionConfig, RubricConfig


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
def simple_rubric() -> RubricConfig:
    return RubricConfig(
        name="test-rubric",
        criteria=[
            CriterionConfig(name="helpfulness", description="Is the response helpful?", weight=1.0, scale=5),
            CriterionConfig(name="accuracy", description="Is the response accurate?", weight=2.0, scale=5),
        ],
        content_hash="abc123",
    )


@pytest.fixture
def dummy_run(db_session: Session) -> Run:
    config = AgentConfig(
        id=str(uuid.uuid4()),
        name="test-config",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        system_prompt="You are helpful.",
    )
    db_session.add(config)
    run = Run(
        id=str(uuid.uuid4()),
        config_id=config.id,
        task_id="task-1",
        output="The answer is 42.",
        status="done",
    )
    db_session.add(run)
    db_session.commit()
    return run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_score_criterion_parses_valid_json(db_session: Session, mocker):
    """Judge should parse a well-formed JSON response from the LLM."""
    judge = Judge(judge_model="claude-haiku-4-5-20251001", provider="anthropic", db_session=db_session)
    mocker.patch.object(judge, "_call_llm", return_value='{"score": 4, "justification": "good"}')

    criterion = CriterionConfig(name="helpfulness", description="Is helpful?", scale=5)
    score, justification = judge._score_criterion(
        task_input="What is 2+2?",
        output="The answer is 4.",
        reference=None,
        criterion=criterion,
    )

    assert score == 4.0
    assert justification == "good"


def test_score_criterion_retries_on_bad_json(db_session: Session, mocker):
    """Judge should retry once when first LLM response is not valid JSON."""
    judge = Judge(judge_model="claude-haiku-4-5-20251001", provider="anthropic", db_session=db_session)
    call_count = [0]
    valid_json = '{"score": 3, "justification": "acceptable"}'

    def _side_effect(prompt, correction_message=None):
        call_count[0] += 1
        if correction_message is None:
            return "this is not json at all"
        return valid_json

    mocker.patch.object(judge, "_call_llm", side_effect=_side_effect)

    criterion = CriterionConfig(name="accuracy", description="Is accurate?", scale=5)
    score, justification = judge._score_criterion(
        task_input="Compute 10/2",
        output="The result is 5.",
        reference="5",
        criterion=criterion,
    )

    assert call_count[0] == 2  # initial + retry
    assert score == 3.0
    assert justification == "acceptable"


def test_judge_run_persists_judgements(db_session: Session, dummy_run: Run, simple_rubric: RubricConfig, mocker):
    """judge_run should persist one Judgement row per criterion."""
    judge = Judge(judge_model="claude-haiku-4-5-20251001", provider="anthropic", db_session=db_session)
    mocker.patch.object(
        judge,
        "_score_criterion",
        return_value=(4.0, "looks good"),
    )

    judge.judge_run(
        run=dummy_run,
        task_input="What is the capital of France?",
        reference="Paris",
        rubric=simple_rubric,
    )

    judgements = db_session.query(Judgement).filter(Judgement.run_id == dummy_run.id).all()
    assert len(judgements) == len(simple_rubric.criteria)
    for j in judgements:
        assert j.run_id == dummy_run.id
        assert j.score == 4.0
        assert j.justification == "looks good"
        assert j.judge_model == "claude-haiku-4-5-20251001"


def test_judge_run_sets_correct_rubric_id(db_session: Session, dummy_run: Run, simple_rubric: RubricConfig, mocker):
    """rubric_id on each Judgement must match rubric.content_hash."""
    judge = Judge(judge_model="claude-haiku-4-5-20251001", provider="anthropic", db_session=db_session)
    mocker.patch.object(judge, "_score_criterion", return_value=(5.0, "perfect"))

    judge.judge_run(
        run=dummy_run,
        task_input="Test input",
        reference=None,
        rubric=simple_rubric,
    )

    judgements = db_session.query(Judgement).filter(Judgement.run_id == dummy_run.id).all()
    for j in judgements:
        assert j.rubric_id == simple_rubric.content_hash
