"""FastAPI application exposing Arena endpoints."""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, select

from .arena import Arena
from .db import get_session, init_db
from .loaders import load_rubric, load_task_suite
from .models import AgentConfig, ArenaRun, Judgement, Run, Span

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AgentArena", version="0.1.0", lifespan=lifespan)


class ArenaRunRequest(BaseModel):
    config_ids: list[str]
    task_suite_path: str
    rubric_path: str
    judge_model: str = "claude-haiku-4-5-20251001"
    judge_provider: str = "anthropic"
    max_turns: int = 10


class ArenaRunResponse(BaseModel):
    arena_id: str
    status: str


@app.post("/arena/run", response_model=ArenaRunResponse)
def start_arena_run(
    body: ArenaRunRequest, session: Session = Depends(get_session)
) -> ArenaRunResponse:
    """Synchronous — runs to completion before returning."""
    configs = [session.get(AgentConfig, cid) for cid in body.config_ids]
    if any(c is None for c in configs):
        raise HTTPException(status_code=404, detail="One or more config_ids not found")
    suite = load_task_suite(body.task_suite_path)
    rubric = load_rubric(body.rubric_path)
    arena = Arena(session)
    arena_id = arena.run(
        configs,  # type: ignore[arg-type]
        suite,
        rubric,
        body.judge_model,
        body.judge_provider,
        body.max_turns,
    )
    return ArenaRunResponse(arena_id=arena_id, status="done")


@app.get("/arena/results/{arena_id}")
def get_arena_results(
    arena_id: str, session: Session = Depends(get_session)
) -> dict:
    arena = Arena(session)
    try:
        results = arena.get_results(arena_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return dataclasses.asdict(results)


@app.get("/configs", response_model=list[AgentConfig])
def list_configs(session: Session = Depends(get_session)):
    return session.exec(select(AgentConfig)).all()


@app.post("/configs", response_model=AgentConfig)
def create_config(
    config: AgentConfig, session: Session = Depends(get_session)
) -> AgentConfig:
    session.add(config)
    session.commit()
    session.refresh(config)
    return config


@app.get("/arena/runs", response_model=list[ArenaRun])
def list_arena_runs(session: Session = Depends(get_session)):
    return session.exec(select(ArenaRun)).all()


@app.get("/task-suites")
def list_task_suites() -> list[dict]:
    """Scan EXAMPLES_DIR/task_suites/*.yaml, return [{name, path, task_count}]."""
    suite_dir = EXAMPLES_DIR / "task_suites"
    if not suite_dir.exists():
        return []
    result = []
    for p in sorted(suite_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            result.append(
                {
                    "name": data.get("name", p.stem),
                    "path": str(p),
                    "task_count": len(data.get("tasks", [])),
                }
            )
        except Exception:  # noqa: BLE001
            pass
    return result


@app.get("/rubrics")
def list_rubrics() -> list[dict]:
    """Scan EXAMPLES_DIR/rubrics/*.yaml, return [{name, path, criterion_count}]."""
    rubric_dir = EXAMPLES_DIR / "rubrics"
    if not rubric_dir.exists():
        return []
    result = []
    for p in sorted(rubric_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            result.append(
                {
                    "name": data.get("name", p.stem),
                    "path": str(p),
                    "criterion_count": len(data.get("criteria", [])),
                }
            )
        except Exception:  # noqa: BLE001
            pass
    return result


@app.delete("/configs/{config_id}", status_code=204, response_model=None)
def delete_config(config_id: str, session: Session = Depends(get_session)) -> None:
    """Delete an AgentConfig by id. 404 if not found."""
    config = session.get(AgentConfig, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Config '{config_id}' not found")
    session.delete(config)
    session.commit()


@app.get("/arena/runs/{arena_id}")
def get_arena_run(arena_id: str, session: Session = Depends(get_session)) -> dict:
    """Return ArenaRun record fields as dict. 404 if not found."""
    arena_run = session.get(ArenaRun, arena_id)
    if arena_run is None:
        raise HTTPException(status_code=404, detail=f"ArenaRun '{arena_id}' not found")
    return {
        "id": arena_run.id,
        "config_ids": arena_run.config_ids,
        "task_suite_hash": arena_run.task_suite_hash,
        "rubric_hash": arena_run.rubric_hash,
        "status": arena_run.status,
        "created_at": arena_run.created_at.isoformat() if arena_run.created_at else None,
        "finished_at": arena_run.finished_at.isoformat() if arena_run.finished_at else None,
        "error": arena_run.error,
    }


@app.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    """Return Run metadata with config_name resolved. 404 if not found."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    config = session.get(AgentConfig, run.config_id)
    config_name = config.name if config else run.config_id[:8]
    return {
        "id": run.id,
        "arena_run_id": run.arena_run_id,
        "config_id": run.config_id,
        "config_name": config_name,
        "task_id": run.task_id,
        "output": run.output,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": run.error,
    }


@app.get("/runs/{run_id}/spans")
def get_run_spans(run_id: str, session: Session = Depends(get_session)) -> list[dict]:
    """Return spans for a run ordered by rowid (insertion order)."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    spans = session.exec(
        select(Span).where(Span.run_id == run_id).order_by(text("rowid"))
    ).all()
    return [
        {
            "id": s.id,
            "run_id": s.run_id,
            "kind": s.kind,
            "name": s.name,
            "input": s.input,
            "output": s.output,
            "latency_ms": s.latency_ms,
            "tokens": s.tokens,
        }
        for s in spans
    ]


@app.get("/runs/{run_id}/judgements")
def get_run_judgements(
    run_id: str, session: Session = Depends(get_session)
) -> list[dict]:
    """Return all judgements for a run."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    judgements = session.exec(
        select(Judgement).where(Judgement.run_id == run_id)
    ).all()
    return [
        {
            "id": j.id,
            "run_id": j.run_id,
            "rubric_id": j.rubric_id,
            "criterion": j.criterion,
            "score": j.score,
            "justification": j.justification,
            "judge_model": j.judge_model,
        }
        for j in judgements
    ]


@app.get("/arena/{arena_id}/runs")
def get_arena_run_list(
    arena_id: str, session: Session = Depends(get_session)
) -> list[dict]:
    """Return all runs for an arena_id with config_name resolved. 404 if none."""
    runs = session.exec(select(Run).where(Run.arena_run_id == arena_id)).all()
    if not runs:
        raise HTTPException(
            status_code=404, detail=f"No runs found for arena '{arena_id}'"
        )
    result = []
    for run in runs:
        config = session.get(AgentConfig, run.config_id)
        config_name = config.name if config else run.config_id[:8]
        result.append(
            {
                "id": run.id,
                "arena_run_id": run.arena_run_id,
                "config_id": run.config_id,
                "config_name": config_name,
                "task_id": run.task_id,
                "output": run.output,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": (
                    run.finished_at.isoformat() if run.finished_at else None
                ),
                "error": run.error,
            }
        )
    return result


@app.post("/arena/demo", response_model=dict)
def run_demo(session: Session = Depends(get_session)) -> dict:
    """Seed two built-in configs (if not present), run demo, return {arena_id}."""
    demo_configs = [
        {
            "name": "claude-baseline",
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "system_prompt": "You are a helpful assistant.",
            "tools": [],
            "params": {},
        },
        {
            "name": "claude-cot",
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "system_prompt": (
                "You are a helpful assistant. Think step by step before answering."
            ),
            "tools": [],
            "params": {},
        },
    ]

    configs = []
    for demo in demo_configs:
        existing = session.exec(
            select(AgentConfig).where(AgentConfig.name == demo["name"])
        ).first()
        if existing:
            configs.append(existing)
        else:
            new_config = AgentConfig(**demo)
            session.add(new_config)
            session.commit()
            session.refresh(new_config)
            configs.append(new_config)

    suite_path = EXAMPLES_DIR / "task_suites" / "customer_support.yaml"
    rubric_path = EXAMPLES_DIR / "rubrics" / "helpfulness.yaml"

    if not suite_path.exists():
        raise HTTPException(
            status_code=500, detail=f"Demo task suite not found: {suite_path}"
        )
    if not rubric_path.exists():
        raise HTTPException(
            status_code=500, detail=f"Demo rubric not found: {rubric_path}"
        )

    suite = load_task_suite(suite_path)
    rubric = load_rubric(rubric_path)
    arena = Arena(session)
    arena_id = arena.run(
        configs,
        suite,
        rubric,
        judge_model="claude-haiku-4-5-20251001",
        judge_provider="anthropic",
        max_turns=5,
    )
    return {"arena_id": arena_id}
