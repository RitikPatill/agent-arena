"""Task Suites browser page."""

from __future__ import annotations

import streamlit as st

from agent_arena.dashboard import api_client

st.title("Task Suites")

try:
    suites = api_client.list_task_suites()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

if not suites:
    st.info("No task suite YAML files found in the examples/task_suites/ directory.")
    st.stop()

st.dataframe(
    [{"name": s["name"], "path": s["path"], "tasks": s["task_count"]} for s in suites],
    use_container_width=True,
)

selected = st.selectbox("Inspect suite", [s["name"] for s in suites])
suite_info = next(s for s in suites if s["name"] == selected)

st.subheader(f"Tasks in `{selected}`")

try:
    # Load task details via a dedicated endpoint if available, else show path info
    import yaml
    from pathlib import Path

    path = Path(suite_info["path"])
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks = data.get("tasks", [])
        rows = [
            {
                "id": t.get("id", ""),
                "input": (t.get("input", ""))[:120],
                "reference": (t.get("reference") or "")[:80],
                "meta": str(t.get("meta", {})),
            }
            for t in tasks
        ]
        st.dataframe(rows, use_container_width=True)
    else:
        st.warning(f"File not accessible from dashboard: {path}")
except Exception as e:
    st.error(f"Could not load suite details: {e}")
