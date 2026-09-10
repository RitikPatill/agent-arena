"""Arena CLI — entry point for all arena commands."""

from __future__ import annotations

from pathlib import Path

import typer
from sqlmodel import Session, select

from .db import engine, init_db
from .loaders import load_rubric, load_task_suite
from .models import AgentConfig

app = typer.Typer(no_args_is_help=True)

# ---------------------------------------------------------------------------
# tasks subgroup
# ---------------------------------------------------------------------------

tasks_app = typer.Typer(help="Inspect task suites.")
app.add_typer(tasks_app, name="tasks")


@tasks_app.command("list")
def tasks_list(path: Path = typer.Argument(..., help="Path to task suite YAML")):
    """Print task IDs and truncated input for every task in the suite."""
    suite = load_task_suite(path)
    typer.echo(f"Suite: {suite.name}  (v{suite.version}, {len(suite.tasks)} tasks)")
    typer.echo(f"Hash:  {suite.content_hash}")
    typer.echo("")
    for task in suite.tasks:
        truncated = task.input[:72] + "..." if len(task.input) > 72 else task.input
        typer.echo(f"{task.id:<20} {truncated}")


@tasks_app.command("show")
def tasks_show(
    path: Path = typer.Argument(..., help="Path to task suite YAML"),
    task_id: str = typer.Argument(..., help="Task ID to display"),
):
    """Print full detail (input, reference, meta) for one task."""
    suite = load_task_suite(path)
    task = next((t for t in suite.tasks if t.id == task_id), None)
    if task is None:
        typer.echo(f"Error: task '{task_id}' not found in {path}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"ID:        {task.id}")
    typer.echo(f"Input:     {task.input}")
    typer.echo(f"Reference: {task.reference or '(none)'}")
    if task.meta:
        typer.echo(f"Meta:      {task.meta}")


# ---------------------------------------------------------------------------
# configs subgroup
# ---------------------------------------------------------------------------

configs_app = typer.Typer(help="Manage agent configs.")
app.add_typer(configs_app, name="configs")


@configs_app.command("create")
def configs_create(
    name: str = typer.Argument(..., help="Config name"),
    provider: str = typer.Argument(..., help="Provider: anthropic | openai"),
    model: str = typer.Argument(..., help="Model ID"),
    system_prompt: str = typer.Option(
        "You are a helpful assistant.", "--system-prompt", "-s"
    ),
    tools: list[str] = typer.Option([], "--tool", "-t", help="Tool name (repeatable)"),
):
    """Persist a new AgentConfig and print its ID."""
    init_db()
    config = AgentConfig(
        name=name,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
    )
    with Session(engine) as session:
        session.add(config)
        session.commit()
        session.refresh(config)
        typer.echo(f"Created config: {config.id}  ({config.name})")


@configs_app.command("list")
def configs_list():
    """List all stored AgentConfigs."""
    init_db()
    with Session(engine) as session:
        configs = session.exec(select(AgentConfig)).all()
    if not configs:
        typer.echo("No configs found. Use `arena configs create` to add one.")
        return
    header = f"{'ID':<36}  {'NAME':<20}  {'PROVIDER':<10}  MODEL"
    typer.echo(header)
    typer.echo("-" * len(header))
    for c in configs:
        typer.echo(f"{c.id:<36}  {c.name:<20}  {c.provider:<10}  {c.model}")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
def run(
    suite: Path = typer.Argument(..., help="Path to task suite YAML"),
    rubric: Path = typer.Argument(..., help="Path to rubric YAML"),
    config_id: list[str] = typer.Option(
        ..., "--config", "-c", help="AgentConfig ID (repeatable)"
    ),
    judge_model: str = typer.Option("claude-haiku-4-5-20251001", "--judge-model"),
    judge_provider: str = typer.Option("anthropic", "--judge-provider"),
    max_turns: int = typer.Option(10, "--max-turns"),
):
    """Run agent configs against a task suite and judge outputs."""
    from .arena import Arena

    init_db()
    with Session(engine) as session:
        configs = [session.get(AgentConfig, cid) for cid in config_id]
        missing = [cid for cid, c in zip(config_id, configs) if c is None]
        if missing:
            typer.echo(f"Error: config IDs not found: {missing}", err=True)
            raise typer.Exit(code=1)

        task_suite = load_task_suite(suite)
        rubric_cfg = load_rubric(rubric)

        total = len(configs) * len(task_suite.tasks)
        typer.echo(
            f"Running {len(configs)} config(s) × {len(task_suite.tasks)} tasks "
            f"= {total} runs …"
        )

        arena = Arena(session)

        # Patch Arena.run to emit progress; wrap runner
        from .runner import AgentRunner as _Runner
        from .judge import Judge as _Judge

        original_runner_run = _Runner.run
        counter = [0]

        def _patched_run(self_r, task):
            result = original_runner_run(self_r, task)
            counter[0] += 1
            typer.echo(
                f"  [{counter[0]}/{total}] {self_r.config.name} / {task.id} … {result.status}"
            )
            return result

        _Runner.run = _patched_run  # type: ignore[method-assign]
        try:
            arena_id = arena.run(
                configs,  # type: ignore[arg-type]
                task_suite,
                rubric_cfg,
                judge_model,
                judge_provider,
                max_turns,
            )
        finally:
            _Runner.run = original_runner_run  # type: ignore[method-assign]

        typer.echo(f"\nArena run complete. ID: {arena_id}")
        typer.echo(f"Use `arena compare {arena_id}` to view results.")


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


@app.command()
def compare(arena_id: str = typer.Argument(..., help="Arena run ID")):
    """Print head-to-head results for a completed arena run."""
    from .arena import Arena
    from .models import ArenaRun

    init_db()
    with Session(engine) as session:
        arena_run = session.get(ArenaRun, arena_id)
        if arena_run is None:
            typer.echo(f"Error: ArenaRun '{arena_id}' not found.", err=True)
            raise typer.Exit(code=1)
        if arena_run.status != "done":
            typer.echo(
                f"Error: ArenaRun status is '{arena_run.status}', not 'done'.", err=True
            )
            raise typer.Exit(code=1)

        arena = Arena(session)
        try:
            results = arena.get_results(arena_id)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1)

        configs = [session.get(AgentConfig, cid) for cid in results.config_ids]
        name_map = {c.id: c.name for c in configs if c}

    # Build table
    criterion_names = []
    for scores in results.mean_scores.values():
        criterion_names = list(scores.keys())
        break

    # Header
    col_w = 20
    crit_w = 12
    header_parts = [f"{'CONFIG':<{col_w}}"]
    for cname in criterion_names:
        header_parts.append(f"{cname[:crit_w]:<{crit_w}}")
    header_parts.append(f"{'OVERALL':>{crit_w}}")
    for other_id in results.config_ids:
        other_name = name_map.get(other_id, other_id[:8])
        header_parts.append(f"  vs {other_name[:8]}")
    header = "  ".join(header_parts)
    typer.echo("")
    typer.echo(header)
    typer.echo("-" * len(header))

    for config_id in results.config_ids:
        cname = name_map.get(config_id, config_id[:col_w])
        row_parts = [f"{cname[:col_w]:<{col_w}}"]

        # Per-criterion means
        per_crit = results.mean_scores.get(config_id, {})
        overall_scores = []
        for crit in criterion_names:
            stat = per_crit.get(crit)
            val = stat.mean if stat else 0.0
            overall_scores.append(val)
            row_parts.append(f"{val:.3f}{'':<{crit_w - 5}}")

        overall = sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
        row_parts.append(f"{overall:.3f}{'':<{crit_w - 5}}")

        # Win rates vs others
        wr_map = results.win_rates.get(config_id, {})
        for other_id in results.config_ids:
            if other_id == config_id:
                row_parts.append(f"  {'—':^10}")
            else:
                wr = wr_map.get(other_id, 0.5)
                row_parts.append(f"  {wr:.1%}{'':<6}")

        typer.echo("  ".join(row_parts))

    typer.echo("")


# ---------------------------------------------------------------------------
# demo / judge (stubs kept for discoverability)
# ---------------------------------------------------------------------------


@app.command()
def judge():
    """Score run outputs with an LLM judge (use `arena run` for full pipeline)."""
    typer.echo("Use `arena run` to run + judge in one step.")


@app.command()
def dashboard(
    port: int = typer.Option(8501, help="Streamlit port"),
    api_url: str = typer.Option("http://localhost:8000", help="FastAPI base URL"),
):
    """Launch the Streamlit dashboard."""
    import subprocess
    import sys
    import os

    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
    env = {**os.environ, "ARENA_API_URL": api_url}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard_path),
            "--server.port",
            str(port),
        ],
        env=env,
    )


@app.command()
def demo():
    """Seed demo data and open the dashboard."""
    typer.echo("Run in two terminals:")
    typer.echo("  1) uvicorn agent_arena.api:app --reload")
    typer.echo("  2) arena dashboard")
    typer.echo("")
    typer.echo(
        "Then click 'Run Demo' on the Arena page, or call POST /arena/demo directly."
    )


if __name__ == "__main__":
    app()
