"""Tests for YAML task suite and rubric loaders."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_arena.loaders import load_rubric, load_task_suite

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_SUITE = """\
name: test_suite
tasks:
  - id: t-001
    input: "What is 2+2?"
    reference: "4"
"""

MINIMAL_RUBRIC = """\
name: test_rubric
criteria:
  - name: accuracy
    description: "Is the answer correct?"
    weight: 0.5
    scale: 5
"""


def write(tmp_path: Path, filename: str, content: str) -> Path:
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# TaskSuite tests
# ---------------------------------------------------------------------------


def test_load_task_suite_valid(tmp_path):
    p = write(tmp_path, "suite.yaml", MINIMAL_SUITE)
    suite = load_task_suite(p)
    assert suite.name == "test_suite"
    assert len(suite.tasks) == 1
    assert suite.tasks[0].id == "t-001"
    # content_hash must be a 64-char hex string
    assert len(suite.content_hash) == 64
    assert all(c in "0123456789abcdef" for c in suite.content_hash)


def test_load_task_suite_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_task_suite(tmp_path / "nonexistent.yaml")


def test_load_task_suite_invalid_yaml(tmp_path):
    p = write(tmp_path, "bad.yaml", "name: test\ntasks: [bad: yaml: here")
    with pytest.raises(yaml.YAMLError):
        load_task_suite(p)


def test_load_task_suite_missing_required_field(tmp_path):
    # Missing 'name'
    content = "tasks:\n  - id: t-001\n    input: hello\n"
    p = write(tmp_path, "suite.yaml", content)
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        load_task_suite(p)


def test_load_task_suite_extra_field_forbidden(tmp_path):
    content = MINIMAL_SUITE + "unknown_field: surprise\n"
    p = write(tmp_path, "suite.yaml", content)
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        load_task_suite(p)


def test_content_hash_stability(tmp_path):
    p = write(tmp_path, "suite.yaml", MINIMAL_SUITE)
    h1 = load_task_suite(p).content_hash
    h2 = load_task_suite(p).content_hash
    assert h1 == h2


def test_content_hash_changes_on_edit(tmp_path):
    p = write(tmp_path, "suite.yaml", MINIMAL_SUITE)
    h1 = load_task_suite(p).content_hash
    p.write_text(MINIMAL_SUITE + "description: edited\n", encoding="utf-8")
    h2 = load_task_suite(p).content_hash
    assert h1 != h2


def test_content_hash_in_yaml_is_stripped(tmp_path):
    content = MINIMAL_SUITE + "content_hash: aaabbb\n"
    p = write(tmp_path, "suite.yaml", content)
    suite = load_task_suite(p)
    # The loader's hash overwrites whatever was in the YAML
    assert len(suite.content_hash) == 64


# ---------------------------------------------------------------------------
# Rubric tests
# ---------------------------------------------------------------------------


def test_load_rubric_valid(tmp_path):
    p = write(tmp_path, "rubric.yaml", MINIMAL_RUBRIC)
    rubric = load_rubric(p)
    assert rubric.name == "test_rubric"
    assert len(rubric.criteria) == 1
    assert rubric.criteria[0].weight == 0.5
    assert len(rubric.content_hash) == 64


def test_rubric_weight_negative_rejected(tmp_path):
    content = """\
name: bad_rubric
criteria:
  - name: accuracy
    description: "test"
    weight: -1
    scale: 5
"""
    p = write(tmp_path, "rubric.yaml", content)
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        load_rubric(p)


def test_rubric_scale_out_of_range(tmp_path):
    content = """\
name: bad_rubric
criteria:
  - name: accuracy
    description: "test"
    weight: 0.5
    scale: 0
"""
    p = write(tmp_path, "rubric.yaml", content)
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        load_rubric(p)


# ---------------------------------------------------------------------------
# Integration: example files
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize(
    "yaml_path",
    list((EXAMPLES_DIR / "task_suites").glob("*.yaml")),
    ids=lambda p: p.stem,
)
def test_load_example_suites(yaml_path):
    suite = load_task_suite(yaml_path)
    assert len(suite.tasks) > 0
    assert suite.name


@pytest.mark.parametrize(
    "yaml_path",
    list((EXAMPLES_DIR / "rubrics").glob("*.yaml")),
    ids=lambda p: p.stem,
)
def test_load_example_rubrics(yaml_path):
    rubric = load_rubric(yaml_path)
    assert len(rubric.criteria) > 0
    assert rubric.name
