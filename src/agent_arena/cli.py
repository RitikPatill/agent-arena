import typer

app = typer.Typer(no_args_is_help=True)


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
