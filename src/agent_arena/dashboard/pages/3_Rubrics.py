"""Rubrics browser page."""

from __future__ import annotations

import streamlit as st

from agent_arena.dashboard import api_client

st.title("Rubrics")

try:
    rubrics = api_client.list_rubrics()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

if not rubrics:
    st.info("No rubric YAML files found in the examples/rubrics/ directory.")
    st.stop()

st.dataframe(
    [
        {"name": r["name"], "path": r["path"], "criteria": r["criterion_count"]}
        for r in rubrics
    ],
    use_container_width=True,
)

selected = st.selectbox("Inspect rubric", [r["name"] for r in rubrics])
rubric_info = next(r for r in rubrics if r["name"] == selected)

st.subheader(f"Criteria in `{selected}`")

try:
    import yaml
    from pathlib import Path

    path = Path(rubric_info["path"])
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        criteria = data.get("criteria", [])
        rows = [
            {
                "name": c.get("name", ""),
                "description": c.get("description", ""),
                "weight": c.get("weight", 1.0),
                "scale": c.get("scale", 5),
            }
            for c in criteria
        ]
        st.dataframe(rows, use_container_width=True)
    else:
        st.warning(f"File not accessible from dashboard: {path}")
except Exception as e:
    st.error(f"Could not load rubric details: {e}")
