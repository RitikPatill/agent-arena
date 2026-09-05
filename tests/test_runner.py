"""Unit tests for AgentRunner with mocked LLM providers."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine

from agent_arena.models import AgentConfig, Run, Span, Task
from agent_arena.runner import AgentRunner

# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def anthropic_config():
    return AgentConfig(
        name="test-anthropic",
        provider="anthropic",
        model="claude-3-haiku-20240307",
        system_prompt="You are a helpful assistant.",
        tools=[],
        params={"max_tokens": 256},
    )


@pytest.fixture()
def openai_config():
    return AgentConfig(
        name="test-openai",
        provider="openai",
        model="gpt-4o-mini",
        system_prompt="You are a helpful assistant.",
        tools=[],
        params={"max_tokens": 256},
    )


@pytest.fixture()
def simple_task():
    return Task(id="task-1", input="What is 6*7?")


# ---------------------------------------------------------------------------
# Helpers to build mock response objects
# ---------------------------------------------------------------------------


def _anthropic_text_response(text: str):
    """Mimics anthropic.types.Message with a single TextBlock."""
    text_block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    return SimpleNamespace(content=[text_block], stop_reason="end_turn", usage=usage)


def _anthropic_tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "tu_1"):
    """Mimics a Message containing a tool_use block."""
    tool_block = SimpleNamespace(type="tool_use", id=tool_id, name=tool_name, input=tool_input)
    usage = SimpleNamespace(input_tokens=20, output_tokens=10)
    return SimpleNamespace(content=[tool_block], stop_reason="tool_use", usage=usage)


def _openai_text_response(text: str):
    """Mimics openai ChatCompletion with a simple text message."""
    message = MagicMock()
    message.content = text
    message.tool_calls = None
    message.model_dump.return_value = {"role": "assistant", "content": text}

    choice = SimpleNamespace(finish_reason="stop", message=message)
    usage = SimpleNamespace(total_tokens=30)
    return SimpleNamespace(choices=[choice], usage=usage)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_anthropic_runner_no_tools(db_session, anthropic_config, simple_task):
    mock_response = _anthropic_text_response("42")

    # Patch anthropic.Anthropic on the cached module so the lazy import inside
    # the runner picks up the mock.
    with patch("anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.return_value = mock_response

        runner = AgentRunner(anthropic_config, db_session)
        run = runner.run(simple_task)

    assert run.status == "done"
    assert run.output == "42"

    spans = db_session.exec(Span.__table__.select().where(Span.run_id == run.id)).all()
    assert len(spans) == 1
    assert spans[0].kind == "llm"


def test_openai_runner_no_tools(db_session, openai_config, simple_task):
    mock_response = _openai_text_response("42")

    with patch("openai.OpenAI") as MockClient:
        mock_client = MockClient.return_value
        mock_client.chat.completions.create.return_value = mock_response

        runner = AgentRunner(openai_config, db_session)
        run = runner.run(simple_task)

    assert run.status == "done"
    assert run.output == "42"

    spans = db_session.exec(Span.__table__.select().where(Span.run_id == run.id)).all()
    assert len(spans) == 1
    assert spans[0].kind == "llm"


def test_anthropic_runner_with_tool_call(db_session, simple_task):
    """Two LLM turns: first returns tool_use, second returns final text."""
    config = AgentConfig(
        name="test-tool",
        provider="anthropic",
        model="claude-3-haiku-20240307",
        system_prompt="Use tools when needed.",
        tools=["calculator"],
        params={"max_tokens": 256},
    )

    first_response = _anthropic_tool_use_response("calculator", {"expression": "6*7"})
    second_response = _anthropic_text_response("42")

    with patch("anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.side_effect = [first_response, second_response]

        runner = AgentRunner(config, db_session)
        run = runner.run(simple_task)

    assert run.status == "done"
    assert run.output == "42"

    spans = db_session.exec(Span.__table__.select().where(Span.run_id == run.id)).all()
    llm_spans = [s for s in spans if s.kind == "llm"]
    tool_spans = [s for s in spans if s.kind == "tool"]
    assert len(llm_spans) == 2
    assert len(tool_spans) == 1
    assert tool_spans[0].name == "calculator"


def test_run_persisted_to_db(db_session, anthropic_config, simple_task):
    mock_response = _anthropic_text_response("42")

    with patch("anthropic.Anthropic") as MockClient:
        mock_client = MockClient.return_value
        mock_client.messages.create.return_value = mock_response

        runner = AgentRunner(anthropic_config, db_session)
        run = runner.run(simple_task)

    persisted = db_session.get(Run, run.id)
    assert persisted is not None
    assert persisted.status == "done"
