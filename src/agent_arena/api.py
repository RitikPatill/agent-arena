"""FastAPI application exposing Arena endpoints."""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .arena import Arena
from .db import get_session, init_db
from .loaders import load_rubric, load_task_suite
from .models import AgentConfig, ArenaRun


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
