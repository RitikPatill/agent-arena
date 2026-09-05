"""Core data models for AgentArena."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field as PydanticField
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class AgentConfig(SQLModel, table=True):
    """Persisted agent configuration."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    provider: str  # "anthropic" | "openai"
    model: str
    system_prompt: str
    tools: list = Field(default_factory=list, sa_column=Column(JSON))
    params: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Task(BaseModel):
    """In-memory task definition (not persisted independently)."""

    id: str = PydanticField(default_factory=lambda: str(uuid.uuid4()))
    input: str
    reference: str | None = None
    meta: dict = PydanticField(default_factory=dict)


class Run(SQLModel, table=True):
    """Persisted record of one agent execution on one task."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    config_id: str
    task_id: str
    output: str | None = None
    status: str = "pending"  # pending | running | done | error
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    error: str | None = None


class Span(SQLModel, table=True):
    """Persisted record of a single LLM call or tool call within a Run."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    run_id: str
    kind: str  # "llm" | "tool"
    name: str
    input: str   # JSON string
    output: str  # JSON string
    latency_ms: int
    tokens: int | None = None  # LLM spans only
