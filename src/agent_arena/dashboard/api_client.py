"""Thin synchronous httpx client for the AgentArena FastAPI backend."""

from __future__ import annotations

import os

import httpx

ARENA_API_URL = os.environ.get("ARENA_API_URL", "http://localhost:8000")


def _get(path: str, **kwargs) -> dict | list:
    try:
        r = httpx.get(f"{ARENA_API_URL}{path}", timeout=120, **kwargs)
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"Cannot reach API at {ARENA_API_URL}. Is the server running?"
        ) from e
    if not r.is_success:
        raise RuntimeError(f"GET {path} failed ({r.status_code}): {r.text}")
    return r.json()


def _post(path: str, json: dict | None = None) -> dict:
    try:
        r = httpx.post(f"{ARENA_API_URL}{path}", json=json, timeout=300)
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"Cannot reach API at {ARENA_API_URL}. Is the server running?"
        ) from e
    if not r.is_success:
        raise RuntimeError(f"POST {path} failed ({r.status_code}): {r.text}")
    return r.json()


def _delete(path: str) -> None:
    try:
        r = httpx.delete(f"{ARENA_API_URL}{path}", timeout=30)
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"Cannot reach API at {ARENA_API_URL}. Is the server running?"
        ) from e
    if not r.is_success:
        raise RuntimeError(f"DELETE {path} failed ({r.status_code}): {r.text}")


def list_configs() -> list[dict]:
    return _get("/configs")  # type: ignore[return-value]


def create_config(payload: dict) -> dict:
    return _post("/configs", json=payload)


def delete_config(config_id: str) -> None:
    _delete(f"/configs/{config_id}")


def list_task_suites() -> list[dict]:
    return _get("/task-suites")  # type: ignore[return-value]


def list_rubrics() -> list[dict]:
    return _get("/rubrics")  # type: ignore[return-value]


def list_arena_runs() -> list[dict]:
    return _get("/arena/runs")  # type: ignore[return-value]


def get_arena_run(arena_id: str) -> dict:
    return _get(f"/arena/runs/{arena_id}")  # type: ignore[return-value]


def get_arena_results(arena_id: str) -> dict:
    return _get(f"/arena/results/{arena_id}")  # type: ignore[return-value]


def start_arena_run(payload: dict) -> dict:
    return _post("/arena/run", json=payload)


def run_demo() -> dict:
    return _post("/arena/demo")
