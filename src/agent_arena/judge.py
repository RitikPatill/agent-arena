"""LLM-as-judge: scores agent run outputs against rubric criteria."""

from __future__ import annotations

import json

from sqlmodel import Session

from .models import Judgement, Run
from .schemas import CriterionConfig, RubricConfig

_JUDGE_PROMPT = """\
You are an impartial evaluator. Score the agent response on the criterion below.

CRITERION: {criterion_name}
DESCRIPTION: {criterion_description}
SCALE: 0 to {criterion_scale} (higher is better)

TASK INPUT:
{task_input}
{reference_block}
AGENT RESPONSE:
{output}

Reply ONLY with a JSON object: {{"score": <int>, "justification": "<one sentence>"}}"""


class Judge:
    """Scores Run outputs against every criterion in a Rubric."""

    def __init__(self, judge_model: str, provider: str, db_session: Session) -> None:
        self.judge_model = judge_model
        self.provider = provider
        self.session = db_session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def judge_run(
        self,
        run: Run,
        task_input: str,
        reference: str | None,
        rubric: RubricConfig,
    ) -> list[Judgement]:
        """Score run.output against every criterion. Persists and returns Judgements."""
        results: list[Judgement] = []
        for criterion in rubric.criteria:
            score, justification = self._score_criterion(
                task_input=task_input,
                output=run.output or "",
                reference=reference,
                criterion=criterion,
            )
            j = Judgement(
                run_id=run.id,
                rubric_id=rubric.content_hash,
                criterion=criterion.name,
                score=score,
                justification=justification,
                judge_model=self.judge_model,
            )
            self.session.add(j)
            results.append(j)
        self.session.commit()
        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _score_criterion(
        self,
        task_input: str,
        output: str,
        reference: str | None,
        criterion: CriterionConfig,
    ) -> tuple[float, str]:
        """Single LLM call → parse JSON {score, justification}. Retries once."""
        reference_block = f"REFERENCE ANSWER:\n{reference}\n" if reference else ""
        prompt = _JUDGE_PROMPT.format(
            criterion_name=criterion.name,
            criterion_description=criterion.description,
            criterion_scale=criterion.scale,
            task_input=task_input,
            reference_block=reference_block,
            output=output,
        )

        raw = self._call_llm(prompt)
        try:
            return self._parse_response(raw)
        except ValueError:
            # Retry with correction message
            correction = (
                f"Your previous response was not valid JSON. "
                f"You responded with:\n{raw}\n\n"
                f"Reply ONLY with a JSON object: "
                f'{"{"}"score": <int>, "justification": "<one sentence>"{"}"}'
            )
            raw2 = self._call_llm(prompt, correction_message=correction)
            try:
                return self._parse_response(raw2)
            except ValueError:
                raise ValueError("Judge returned unparseable JSON after retry")

    def _parse_response(self, raw: str) -> tuple[float, str]:
        """Parse {score, justification} from raw LLM text."""
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        data = json.loads(text)
        score = float(data["score"])
        justification = str(data["justification"])
        return score, justification

    def _call_llm(self, prompt: str, correction_message: str | None = None) -> str:
        """Call the configured LLM provider and return raw text response."""
        messages: list[dict] = [{"role": "user", "content": prompt}]
        if correction_message:
            # Add a dummy assistant turn so the correction reads naturally
            messages.append({"role": "assistant", "content": "```\nnot valid json\n```"})
            messages.append({"role": "user", "content": correction_message})

        if self.provider == "anthropic":
            return self._call_anthropic(messages)
        elif self.provider == "openai":
            return self._call_openai(messages)
        else:
            raise ValueError(f"Unknown judge provider: {self.provider}")

    def _call_anthropic(self, messages: list[dict]) -> str:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=self.judge_model,
            max_tokens=256,
            messages=messages,
        )
        text_blocks = [b for b in response.content if b.type == "text"]
        return text_blocks[0].text if text_blocks else ""

    def _call_openai(self, messages: list[dict]) -> str:
        import openai

        client = openai.OpenAI()
        response = client.chat.completions.create(
            model=self.judge_model,
            messages=messages,
            max_tokens=256,
        )
        return response.choices[0].message.content or ""
