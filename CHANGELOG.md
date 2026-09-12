# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.1.0] - 2026-09-12

### Added

- Repo scaffold, `pyproject.toml`, CI workflow (GitHub Actions), pre-commit hooks, MIT license (M1)
- Provider-agnostic `AgentRunner` (Anthropic + OpenAI) with tool-calling loop, `max_turns` guard, and SQLite persistence via SQLModel (M2)
- YAML `TaskSuite` and `Rubric` loaders with SHA-256 content hashing for reproducible eval versioning; `arena tasks` CLI commands (M3)
- LLM-as-judge (`Judge` class): one LLM call per criterion, JSON parse with one retry, Anthropic + OpenAI support (M4)
- `Arena` orchestrator: sequential config × task loop, head-to-head win-rate aggregation, per-criterion `CriterionStats` with bootstrap 95% CI, FastAPI backend, `arena run` / `arena compare` CLI (M5)
- Streamlit dashboard: config CRUD, task-suite and rubric browsers, live run progress, leaderboard, Plotly radar chart, head-to-head win-rate heatmap (M6)
- Trace viewer: per-run Plotly waterfall timeline of LLM + tool spans, collapsible JSON inputs/outputs, judgements side panel, deep-links from the Arena page (M7)
- Runnable demo: `examples/quickstart.py` seeds two configs, runs 3 tasks × 2 configs end-to-end, prints formatted win-rate matrix; `scripts/record_demo.sh` for asciinema capture; placeholder `docs/` images (M8)
- Polished README, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md` (M9)
