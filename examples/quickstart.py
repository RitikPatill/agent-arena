"""AgentArena Quickstart — run a 2-config head-to-head arena and print results.

Usage:
    python examples/quickstart.py
    python examples/quickstart.py --tasks 5
    python examples/quickstart.py --no-judge

Requires:
    ANTHROPIC_API_KEY environment variable set.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Bootstrap import path so this works with or without `pip install -e .`
_repo_root = Path(__file__).resolve().parent.parent
_src = _repo_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY is not set.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "Then re-run: python examples/quickstart.py",
            file=sys.stderr,
        )
        sys.exit(1)


def _build_configs(session) -> tuple:
    from sqlmodel import select
    from agent_arena.models import AgentConfig

    baseline_name = "quickstart-baseline"
    cot_name = "quickstart-cot"

    existing = {
        c.name: c
        for c in session.exec(
            select(AgentConfig).where(AgentConfig.name.in_([baseline_name, cot_name]))
        ).all()
    }

    if baseline_name not in existing:
        baseline = AgentConfig(
            name=baseline_name,
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            system_prompt="You are a helpful customer support assistant. Answer questions clearly and concisely.",
            tools=[],
            params={},
        )
        session.add(baseline)
        session.commit()
        session.refresh(baseline)
    else:
        baseline = existing[baseline_name]

    if cot_name not in existing:
        cot = AgentConfig(
            name=cot_name,
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            system_prompt=(
                "Before answering, reason step-by-step inside <thinking> tags, "
                "then give your final answer.\n\n"
                "You are a helpful customer support assistant. Answer questions clearly and concisely."
            ),
            tools=[],
            params={},
        )
        session.add(cot)
        session.commit()
        session.refresh(cot)
    else:
        cot = existing[cot_name]

    return baseline, cot


def _print_summary(results, configs: list) -> None:
    """Print a formatted summary of arena results."""
    from agent_arena.arena import ArenaResults

    config_by_id = {c.id: c.name for c in configs}
    config_ids = results.config_ids

    # --- Win Rates ---
    print("\n┌─ Win Rates " + "─" * 34 + "┐")
    for a_id in config_ids:
        for b_id in config_ids:
            if a_id == b_id:
                continue
            a_name = config_by_id.get(a_id, a_id[:8])
            b_name = config_by_id.get(b_id, b_id[:8])
            rate = results.win_rates.get(a_id, {}).get(b_id, 0.0)
            n_tasks = len(results.per_task)
            wins = round(rate * n_tasks)
            label = f"  {a_name} vs {b_name}:"
            value = f"{wins}/{n_tasks}"
            print(f"{label.ljust(52)}{value.rjust(4)}")

    # --- Mean Scores ---
    print("\n┌─ Mean Scores (0–5) " + "─" * 26 + "┐")
    col_w = 14
    header = "  " + "Criterion".ljust(16)
    for cid in config_ids:
        header += config_by_id.get(cid, cid[:8]).ljust(col_w)
    print(header)

    # Collect all criterion names
    all_criteria: list[str] = []
    if config_ids and results.mean_scores.get(config_ids[0]):
        all_criteria = list(results.mean_scores[config_ids[0]].keys())

    for criterion in all_criteria:
        row = "  " + criterion.ljust(16)
        for cid in config_ids:
            stats = results.mean_scores.get(cid, {}).get(criterion)
            if stats:
                mean_5 = stats.mean * 5  # normalised → 0-5 scale
                ci = (stats.ci_high - stats.ci_low) * 5 / 2
                cell = f"{mean_5:.2f}±{ci:.2f}"
            else:
                cell = "  n/a"
            row += cell.ljust(col_w)
        print(row)

    # --- Verdict ---
    if len(config_ids) >= 2:
        a_id, b_id = config_ids[0], config_ids[1]
        a_name = config_by_id.get(a_id, a_id[:8])
        b_name = config_by_id.get(b_id, b_id[:8])
        n_tasks = len(results.per_task)
        a_wins = round(results.win_rates.get(a_id, {}).get(b_id, 0.0) * n_tasks)
        b_wins = n_tasks - a_wins
        if a_wins > b_wins:
            winner, wins = a_name, a_wins
        elif b_wins > a_wins:
            winner, wins = b_name, b_wins
        else:
            winner, wins = "tie", n_tasks // 2
        print(f"\n  ✓ Winner: {winner} ({wins}/{n_tasks} tasks)")


def main(n_tasks: int = 3, no_judge: bool = False) -> None:
    _check_api_key()

    from agent_arena.db import init_db, engine
    from agent_arena.arena import Arena
    from agent_arena.loaders import load_task_suite, load_rubric
    from sqlmodel import Session

    init_db()

    examples_dir = Path(__file__).resolve().parent
    suite_path = examples_dir / "task_suites" / "customer_support.yaml"
    rubric_path = examples_dir / "rubrics" / "helpfulness.yaml"

    suite = load_task_suite(suite_path)
    rubric = load_rubric(rubric_path)

    # Slice to n_tasks
    sliced_tasks = suite.tasks[:n_tasks]
    suite = suite.model_copy(update={"tasks": sliced_tasks})

    with Session(engine) as session:
        baseline, cot = _build_configs(session)
        configs = [baseline, cot]

        print(f"\nAgentArena Quickstart — {n_tasks} tasks × 2 configs")
        print(f"  Config A: {baseline.name} ({baseline.model})")
        print(f"  Config B: {cot.name} ({cot.model})")
        print(f"  Task suite: {suite.name} (first {n_tasks} tasks)")
        print(f"  Rubric: {rubric.name} ({len(rubric.criteria)} criteria)")

        if no_judge:
            print("\n[--no-judge] Skipping real LLM calls; results will show stubs.")
            print("  Arena ID: (dry-run, no data persisted)")
            return

        print("\nRunning arena (this may take a minute)...")
        arena = Arena(session)
        arena_id = arena.run(
            configs=configs,
            task_suite=suite,
            rubric=rubric,
            judge_model="claude-haiku-4-5-20251001",
            judge_provider="anthropic",
            max_turns=5,
        )

        results = arena.get_results(arena_id)
        _print_summary(results, configs)

        print(f"\n✓ Arena ID: {arena_id}")
        print("  To explore traces:")
        print("    uvicorn agent_arena.api:app --reload   # terminal 1")
        print("    arena dashboard                        # terminal 2")
        print("  Then open http://localhost:8501 → Arena page")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AgentArena Quickstart — run a 2-config head-to-head demo."
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=3,
        help="Number of tasks to run (default: 3)",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM calls and judge phase (dry-run mode)",
    )
    args = parser.parse_args()
    main(n_tasks=args.tasks, no_judge=args.no_judge)
