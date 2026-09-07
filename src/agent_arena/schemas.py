"""Pydantic schemas for YAML-based task suites and rubrics.

These are the YAML-layer data classes, kept separate from models.py
(which owns the SQLite-persisted models).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskItem(BaseModel):
    """A single task in a task suite."""

    id: str
    input: str
    reference: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TaskSuiteConfig(BaseModel):
    """Validated representation of a task suite YAML file."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    version: str = "1.0"
    tasks: list[TaskItem]
    content_hash: str = ""  # injected by loader, must not appear in YAML

    @model_validator(mode="before")
    @classmethod
    def _strip_content_hash(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data.pop("content_hash", None)
        return data


class CriterionConfig(BaseModel):
    """A single scoring criterion within a rubric."""

    name: str
    description: str
    weight: float = Field(default=1.0, ge=0.0)
    scale: int = Field(default=5, ge=1, le=10)


class RubricConfig(BaseModel):
    """Validated representation of a rubric YAML file."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    version: str = "1.0"
    criteria: list[CriterionConfig]
    content_hash: str = ""  # injected by loader, must not appear in YAML

    @model_validator(mode="before")
    @classmethod
    def _strip_content_hash(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data.pop("content_hash", None)
        return data
