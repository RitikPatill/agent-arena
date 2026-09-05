"""Unit tests for built-in tools."""

import pytest

from agent_arena.tools import calculator, web_search_stub


def test_calculator_addition():
    assert calculator("2 + 3") == "5"


def test_calculator_multiply():
    assert calculator("6 * 7") == "42"


def test_calculator_division():
    assert calculator("10 / 4") == "2.5"


def test_calculator_rejects_exec():
    with pytest.raises(ValueError):
        calculator("__import__('os').system('ls')")


def test_calculator_rejects_call():
    with pytest.raises(ValueError):
        calculator("abs(-1)")  # function call nodes are not whitelisted


def test_web_search_stub_returns_string():
    result = web_search_stub("python async io")
    assert isinstance(result, str)
    assert len(result) > 0
    assert "python async io" in result
