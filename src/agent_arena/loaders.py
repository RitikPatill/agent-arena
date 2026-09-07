"""Loaders for YAML-based task suites and rubrics."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from .schemas import RubricConfig, TaskSuiteConfig


def _content_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_task_suite(path: str | Path) -> TaskSuiteConfig:
    """Load and validate a task suite YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        Validated TaskSuiteConfig with content_hash set.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
        pydantic.ValidationError: If the data fails schema validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Task suite file not found: {path}")

    file_hash = _content_hash(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    suite = TaskSuiteConfig.model_validate(data)
    suite.content_hash = file_hash
    return suite


def load_rubric(path: str | Path) -> RubricConfig:
    """Load and validate a rubric YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        Validated RubricConfig with content_hash set.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
        pydantic.ValidationError: If the data fails schema validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Rubric file not found: {path}")

    file_hash = _content_hash(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rubric = RubricConfig.model_validate(data)
    rubric.content_hash = file_hash
    return rubric
