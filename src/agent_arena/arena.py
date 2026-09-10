"""Arena orchestrator: runs N configs × all tasks and aggregates results."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, select

from .judge import Judge
from .models import AgentConfig, ArenaRun, Judgement, Run
from .runner import AgentRunner
from .schemas import RubricConfig, TaskItem, TaskSuiteConfig


@dataclass
class CriterionStats:
    mean: float
    ci_low: float
    ci_high: float


@dataclass
class ArenaResults:
    arena_id: str
    config_ids: list[str]
    # win_rates[config_a][config_b] = fraction of tasks where a beats b
    win_rates: dict[str, dict[str, float]] = field(default_factory=dict)
    # mean_scores[config_id][criterion_name] = CriterionStats
    mean_scores: dict[str, dict[str, CriterionStats]] = field(default_factory=dict)
    # per_task[task_id][config_id] = weighted_score (0–1 normalised)
    per_task: dict[str, dict[str, float]] = field(default_factory=dict)


class Arena:
    """Orchestrates multi-config, multi-task evaluation runs."""

    def __init__(self, db_session: Session) -> None:
        self.session = db_session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        configs: list[AgentConfig],
        task_suite: TaskSuiteConfig,
        rubric: RubricConfig,
        judge_model: str = "claude-haiku-4-5-20251001",
        judge_provider: str = "anthropic",
        max_turns: int = 10,
    ) -> str:
        """Run each config against every task, judge outputs, persist everything.

        Returns arena_id.
        """
        arena_run = ArenaRun(
            config_ids=[c.id for c in configs],
            task_suite_hash=task_suite.content_hash,
            rubric_hash=rubric.content_hash,
            status="running",
        )
        self.session.add(arena_run)
        self.session.commit()

        judge = Judge(
            judge_model=judge_model,
            provider=judge_provider,
            db_session=self.session,
        )

        try:
            for config in configs:
                runner = AgentRunner(config, self.session, max_turns=max_turns, arena_run_id=arena_run.id)
                for task_item in task_suite.tasks:
                    from .models import Task
                    task = Task(
                        id=task_item.id,
                        input=task_item.input,
                        reference=task_item.reference,
                        meta=task_item.meta,
                    )
                    completed_run = runner.run(task)
                    if completed_run.status == "done":
                        judge.judge_run(
                            run=completed_run,
                            task_input=task_item.input,
                            reference=task_item.reference,
                            rubric=rubric,
                        )

            arena_run.status = "done"
        except Exception as exc:  # noqa: BLE001
            arena_run.status = "error"
            arena_run.error = str(exc)
            raise
        finally:
            arena_run.finished_at = datetime.utcnow()
            self.session.add(arena_run)
            self.session.commit()

        return arena_run.id

    def get_results(self, arena_id: str) -> ArenaResults:
        """Load and aggregate results for a completed ArenaRun."""
        arena_run = self.session.get(ArenaRun, arena_id)
        if arena_run is None:
            raise ValueError(f"ArenaRun '{arena_id}' not found")
        if arena_run.status != "done":
            raise ValueError(
                f"ArenaRun '{arena_id}' is not complete (status={arena_run.status})"
            )

        config_ids: list[str] = arena_run.config_ids
        configs = [self.session.get(AgentConfig, cid) for cid in config_ids]
        configs = [c for c in configs if c is not None]

        # Load rubric from DB via judgements to reconstruct criteria info
        # Scope runs strictly to this arena run to avoid mixing results across executions.
        runs: list[Run] = list(
            self.session.exec(
                select(Run).where(Run.arena_run_id == arena_id)
            ).all()
        )
        run_ids = [r.id for r in runs]

        judgements: list[Judgement] = []
        if run_ids:
            judgements = list(
                self.session.exec(
                    select(Judgement).where(Judgement.run_id.in_(run_ids))
                ).all()
            )

        # Reconstruct rubric info from judgements (criteria names + scales)
        # We need the rubric but don't store it — reconstruct from judgements
        # Build a lightweight rubric proxy from persisted judgements
        from .schemas import CriterionConfig, RubricConfig as _RubricConfig

        criterion_names = list({j.criterion for j in judgements})
        # Build per-criterion scale from max score seen (best-effort reconstruction)
        criterion_scale: dict[str, int] = {}
        for j in judgements:
            if j.criterion not in criterion_scale:
                criterion_scale[j.criterion] = 5  # default
        # Uniform weight=1 for aggregation when rubric not available
        fake_criteria = [
            CriterionConfig(name=n, description="", weight=1.0, scale=criterion_scale[n])
            for n in criterion_names
        ]

        return self._aggregate(arena_run, runs, judgements, configs, fake_criteria)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _weighted_score(
        self, judgements: list[Judgement], criteria: list[CriterionConfig]
    ) -> float:
        """Compute normalised weighted score in [0, 1]."""
        if not judgements or not criteria:
            return 0.0
        scale_map = {c.name: c.scale for c in criteria}
        weight_map = {c.name: c.weight for c in criteria}
        total_weight = sum(weight_map.get(j.criterion, 1.0) for j in judgements)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(
            (j.score / scale_map.get(j.criterion, 5)) * weight_map.get(j.criterion, 1.0)
            for j in judgements
        )
        return weighted_sum / total_weight

    def _bootstrap_ci(
        self,
        values: list[float],
        n_iter: int = 1000,
        alpha: float = 0.05,
        seed: int = 42,
    ) -> tuple[float, float]:
        """Pure-stdlib bootstrap confidence interval."""
        if not values:
            return (0.0, 0.0)
        rng = random.Random(seed)
        n = len(values)
        means = []
        for _ in range(n_iter):
            sample = rng.choices(values, k=n)
            means.append(sum(sample) / n)
        means.sort()
        lo_idx = int(alpha / 2 * n_iter)
        hi_idx = int((1 - alpha / 2) * n_iter) - 1
        return (means[lo_idx], means[hi_idx])

    def _aggregate(
        self,
        arena_run: ArenaRun,
        runs: list[Run],
        judgements: list[Judgement],
        configs: list[AgentConfig],
        criteria: list[CriterionConfig],
    ) -> ArenaResults:
        config_ids = [c.id for c in configs]

        # Index: run_id -> list[Judgement]
        j_by_run: dict[str, list[Judgement]] = {}
        for j in judgements:
            j_by_run.setdefault(j.run_id, []).append(j)

        # Index: (config_id, task_id) -> Run
        run_by_ct: dict[tuple[str, str], Run] = {}
        for r in runs:
            run_by_ct[(r.config_id, r.task_id)] = r

        # Collect all task_ids seen
        task_ids = list({r.task_id for r in runs})

        # per_task[task_id][config_id] = weighted_score
        per_task: dict[str, dict[str, float]] = {}
        for task_id in task_ids:
            per_task[task_id] = {}
            for config in configs:
                run = run_by_ct.get((config.id, task_id))
                if run and run.status == "done":
                    score = self._weighted_score(j_by_run.get(run.id, []), criteria)
                else:
                    score = 0.0
                per_task[task_id][config.id] = score

        # win_rates[a][b] = fraction of tasks where a > b (tie → 0.5 each)
        win_rates: dict[str, dict[str, float]] = {cid: {} for cid in config_ids}
        for a in config_ids:
            for b in config_ids:
                if a == b:
                    win_rates[a][b] = 0.5
                    continue
                wins = 0.0
                count = 0
                for task_id in task_ids:
                    sa = per_task[task_id].get(a, 0.0)
                    sb = per_task[task_id].get(b, 0.0)
                    if abs(sa - sb) < 1e-9:
                        wins += 0.5
                    elif sa > sb:
                        wins += 1.0
                    count += 1
                win_rates[a][b] = wins / count if count > 0 else 0.5

        # mean_scores[config_id][criterion_name] = CriterionStats
        mean_scores: dict[str, dict[str, CriterionStats]] = {}
        for config in configs:
            mean_scores[config.id] = {}
            config_runs = [r for r in runs if r.config_id == config.id]
            for criterion in criteria:
                scores = []
                for r in config_runs:
                    for j in j_by_run.get(r.id, []):
                        if j.criterion == criterion.name:
                            scores.append(j.score / criterion.scale)
                if scores:
                    mean = sum(scores) / len(scores)
                    ci_low, ci_high = self._bootstrap_ci(scores)
                else:
                    mean, ci_low, ci_high = 0.0, 0.0, 0.0
                mean_scores[config.id][criterion.name] = CriterionStats(
                    mean=mean, ci_low=ci_low, ci_high=ci_high
                )

        return ArenaResults(
            arena_id=arena_run.id,
            config_ids=config_ids,
            win_rates=win_rates,
            mean_scores=mean_scores,
            per_task=per_task,
        )
