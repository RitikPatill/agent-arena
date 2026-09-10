"""Provider-agnostic AgentRunner with tool-calling loop."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from sqlmodel import Session

from .models import AgentConfig, Run, Span, Task
from .tools import TOOL_REGISTRY, get_tool_schemas

DEFAULT_MAX_TURNS = 10


class AgentRunner:
    """Runs an agent config against a task, persisting spans to the DB."""

    def __init__(
        self,
        config: AgentConfig,
        db_session: Session,
        max_turns: int = DEFAULT_MAX_TURNS,
        arena_run_id: str | None = None,
    ) -> None:
        self.config = config
        self.session = db_session
        self.max_turns = max_turns
        self.arena_run_id = arena_run_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, task: Task) -> Run:
        """Execute the agent loop for one task. Returns completed Run."""
        run = Run(
            id=str(uuid.uuid4()),
            arena_run_id=self.arena_run_id,
            config_id=self.config.id,
            task_id=task.id,
            status="running",
            started_at=datetime.utcnow(),
        )
        self.session.add(run)
        self.session.commit()

        messages: list[dict] = [{"role": "user", "content": task.input}]

        try:
            if self.config.provider == "anthropic":
                output = self._run_anthropic(run, messages)
            elif self.config.provider == "openai":
                output = self._run_openai(run, messages)
            else:
                raise ValueError(f"Unknown provider: {self.config.provider}")

            run.output = output
            run.status = "done"
        except Exception as exc:  # noqa: BLE001
            run.status = "error"
            run.error = str(exc)
        finally:
            run.finished_at = datetime.utcnow()
            self.session.add(run)
            self.session.commit()

        return run

    # ------------------------------------------------------------------
    # Anthropic loop
    # ------------------------------------------------------------------

    def _run_anthropic(self, run: Run, messages: list[dict]) -> str:
        import anthropic

        client = anthropic.Anthropic()
        tool_names: list[str] = list(self.config.tools or [])
        tools = get_tool_schemas(tool_names, provider="anthropic")

        for _ in range(self.max_turns):
            kwargs: dict = {
                "model": self.config.model,
                "max_tokens": self.config.params.get("max_tokens", 1024),
                "system": self.config.system_prompt,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools

            t0 = time.monotonic()
            response = client.messages.create(**kwargs)
            latency_ms = int((time.monotonic() - t0) * 1000)

            tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
            self._record_llm_span(run, messages, response, latency_ms, tokens)

            # Check for tool-use blocks
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_use_blocks:
                # Final text answer
                text_blocks = [b for b in response.content if b.type == "text"]
                return text_blocks[0].text if text_blocks else ""

            # Append assistant message with tool_use blocks
            messages.append({"role": "assistant", "content": response.content})

            # Dispatch all tool calls and collect results
            tool_results = []
            for block in tool_use_blocks:
                result = self._dispatch_tool(run, block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})

        run.status = "error"
        run.error = "max_turns exceeded"
        raise RuntimeError("max_turns exceeded")

    # ------------------------------------------------------------------
    # OpenAI loop
    # ------------------------------------------------------------------

    def _run_openai(self, run: Run, messages: list[dict]) -> str:
        import openai

        client = openai.OpenAI()
        tool_names: list[str] = list(self.config.tools or [])
        tools = get_tool_schemas(tool_names, provider="openai")

        # Prepend system message
        full_messages = [{"role": "system", "content": self.config.system_prompt}] + messages

        for _ in range(self.max_turns):
            kwargs: dict = {
                "model": self.config.model,
                "messages": full_messages,
                **{k: v for k, v in self.config.params.items() if k != "max_tokens"},
            }
            if "max_tokens" in self.config.params:
                kwargs["max_tokens"] = self.config.params["max_tokens"]
            if tools:
                kwargs["tools"] = tools

            t0 = time.monotonic()
            response = client.chat.completions.create(**kwargs)
            latency_ms = int((time.monotonic() - t0) * 1000)

            tokens = response.usage.total_tokens if response.usage else None
            self._record_llm_span(run, full_messages, response, latency_ms, tokens)

            choice = response.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                full_messages.append(msg.model_dump())

                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    result = self._dispatch_tool(run, tc.function.name, args)
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
            else:
                return msg.content or ""

        run.status = "error"
        run.error = "max_turns exceeded"
        raise RuntimeError("max_turns exceeded")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dispatch_tool(self, run: Run, name: str, args: dict) -> str:
        """Call the named tool, record a Span, return string output."""
        fn = TOOL_REGISTRY.get(name)
        if fn is None:
            return f"[error] Unknown tool: {name}"

        t0 = time.monotonic()
        try:
            result = fn(**args)
        except Exception as exc:  # noqa: BLE001
            result = f"[error] {exc}"
        latency_ms = int((time.monotonic() - t0) * 1000)

        span = Span(
            id=str(uuid.uuid4()),
            run_id=run.id,
            kind="tool",
            name=name,
            input=json.dumps(args),
            output=json.dumps(result),
            latency_ms=latency_ms,
        )
        self.session.add(span)
        self.session.commit()
        return str(result)

    def _record_llm_span(
        self,
        run: Run,
        input_msgs: list[dict],
        output_obj: object,
        latency_ms: int,
        tokens: int | None,
    ) -> Span:
        span = Span(
            id=str(uuid.uuid4()),
            run_id=run.id,
            kind="llm",
            name=self.config.model,
            input=json.dumps(input_msgs, default=str),
            output=json.dumps(str(output_obj)),
            latency_ms=latency_ms,
            tokens=tokens,
        )
        self.session.add(span)
        self.session.commit()
        return span
