# Contributing to AgentArena

Thanks for your interest in contributing! This guide covers the dev setup, conventions, and PR checklist.

---

## Dev setup

```bash
git clone https://github.com/agent-arena/agent-arena.git
cd agent-arena
pip install -e ".[dev]"
pre-commit install
```

The `[dev]` extra installs `pytest`, `ruff`, `pre-commit`, and `httpx` (for the test client). No API key is needed to run the test suite — all LLM calls are mocked.

---

## Running tests

```bash
pytest
```

All tests use in-memory SQLite and mocked LLM clients. Tests must pass without any environment variables set.

---

## Lint and format

```bash
ruff check src tests
ruff format src tests
```

Pre-commit runs both automatically on each commit. Fix any issues before opening a PR.

---

## PR checklist

- [ ] `pytest` passes locally
- [ ] `ruff check` and `ruff format` report no issues
- [ ] New behaviour is covered by at least one test
- [ ] An entry is added under `## [Unreleased]` in `CHANGELOG.md`
- [ ] Commit subject is imperative, ≤ 72 chars, references issue/PR if applicable (e.g. `feat(runner): add retry on rate-limit (#42)`)

---

## Commit style

Use imperative present tense in the subject line:

```
feat(runner): add retry on rate-limit errors
fix(judge): handle empty response from OpenAI
docs: add ARCHITECTURE.md
chore: pin ruff to 0.4
```

Reference the relevant issue or PR number when applicable. Keep the subject ≤ 72 characters. Add a blank line and a longer body if the change warrants explanation.

---

## Adding a built-in tool

Tools live in `src/agent_arena/tools.py`. Use the `@tool` decorator:

```python
from agent_arena.tools import tool

@tool
def my_tool(arg: str) -> str:
    """One-sentence description shown to the LLM."""
    return do_something(arg)
```

Rules:
- The function name becomes the tool name — it must be unique across the registry.
- The docstring is passed verbatim to the LLM as the tool description; keep it concise.
- The tool must be a pure function or have no side effects that could break parallel test runs.
- Add at least one test in `tests/` that exercises the tool with a mocked runner.

---

## Adding a provider

Provider-specific LLM call logic lives in `src/agent_arena/runner.py`. Follow the `_call_anthropic` / `_call_openai` pattern:

1. Add a `_call_<provider>` method on `AgentRunner` that accepts a list of messages and returns the raw response object.
2. Dispatch from `_call_llm` by matching on `self.config.provider`.
3. Map the provider's tool-call format to the internal `Span` schema.
4. Mirror the same `_call_<provider>` pattern in `src/agent_arena/judge.py`.
5. Add mocked tests for the new provider path.
