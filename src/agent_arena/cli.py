import typer
from pathlib import Path

from .loaders import load_task_suite

app = typer.Typer(no_args_is_help=True)

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


@app.command()
def run():
    """Run agent configs against a task suite."""


@app.command()
def judge():
    """Score run outputs with an LLM judge."""


@app.command()
def compare():
    """Compare two or more runs head-to-head."""


@app.command()
def demo():
    """Launch the demo with pre-built configs and tasks."""


if __name__ == "__main__":
    app()
