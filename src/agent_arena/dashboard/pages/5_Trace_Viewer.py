"""Trace Viewer — per-run waterfall of spans + judgements side panel."""

from __future__ import annotations

import json

import plotly.graph_objects as go
import streamlit as st

from agent_arena.dashboard import api_client

st.title("Trace Viewer")

# ── Entry: check for run_id in query params ────────────────────────────────────
run_id: str | None = st.query_params.get("run_id")

# ── Selector (no run_id in URL) ────────────────────────────────────────────────
if not run_id:
    st.subheader("Select a run")

    try:
        arena_runs = api_client.list_arena_runs()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    done_runs = [r for r in arena_runs if r.get("status") == "done"]
    if not done_runs:
        st.info("No completed arena runs found. Run an arena first.")
        st.stop()

    arena_ids = list({r["id"] for r in done_runs})
    selected_arena = st.selectbox("Arena run", arena_ids)

    if selected_arena:
        try:
            run_list = api_client.get_arena_run_list(selected_arena)
        except RuntimeError as e:
            st.error(str(e))
            st.stop()

        if not run_list:
            st.info("No individual runs found for this arena.")
            st.stop()

        st.markdown("Click **View** to open the trace for a run.")
        header_cols = st.columns([3, 2, 1, 1, 1])
        header_cols[0].markdown("**Config**")
        header_cols[1].markdown("**Task**")
        header_cols[2].markdown("**Status**")
        header_cols[3].markdown("**Score**")
        header_cols[4].markdown("")

        for run in run_list:
            cols = st.columns([3, 2, 1, 1, 1])
            cols[0].write(run.get("config_name", run["config_id"][:8]))
            cols[1].write(run.get("task_id", ""))
            cols[2].write(run.get("status", ""))
            cols[3].write("")
            if cols[4].button("View", key=f"view_{run['id']}"):
                st.query_params["run_id"] = run["id"]
                st.rerun()

    st.stop()

# ── Trace view (run_id is known) ───────────────────────────────────────────────
try:
    run = api_client.get_run(run_id)
except RuntimeError as e:
    st.error(str(e))
    st.stop()

try:
    spans = api_client.get_run_spans(run_id)
except RuntimeError as e:
    spans = []
    st.warning(f"Could not load spans: {e}")

try:
    judgements = api_client.get_run_judgements(run_id)
except RuntimeError as e:
    judgements = []
    st.warning(f"Could not load judgements: {e}")

# Back button
if st.button("← Back to selector"):
    if "run_id" in st.query_params:
        del st.query_params["run_id"]
    st.rerun()

st.divider()

col_left, col_main = st.columns([3, 7])

# ── Left panel: metadata + judgements ─────────────────────────────────────────
with col_left:
    st.subheader("Run info")
    st.markdown(f"**Config:** {run.get('config_name', run.get('config_id', '')[:8])}")
    st.markdown(f"**Task:** {run.get('task_id', '')}")
    st.markdown(f"**Status:** {run.get('status', '')}")

    started = run.get("started_at", "")
    finished = run.get("finished_at", "")
    if started and finished:
        st.markdown(f"**Started:** {started}")
        st.markdown(f"**Finished:** {finished}")
    elif started:
        st.markdown(f"**Started:** {started}")

    if run.get("error"):
        st.error(f"Error: {run['error']}")

    st.divider()
    st.subheader("Judgements")

    if not judgements:
        st.info("No judgements for this run.")
    else:
        sorted_judgements = sorted(judgements, key=lambda j: j.get("criterion", ""))
        for j in sorted_judgements:
            st.metric(
                label=j.get("criterion", ""),
                value=f"{j.get('score', 0):.2f}",
            )
            st.caption(j.get("justification", ""))

# ── Main panel: waterfall chart + span expanders ──────────────────────────────
with col_main:
    st.subheader("Span Waterfall")

    if not spans:
        st.info("No spans recorded for this run.")
    else:
        # Build cumulative start times
        latencies = [s.get("latency_ms", 0) for s in spans]
        starts = [sum(latencies[:i]) for i in range(len(spans))]

        colors = [
            "#4C78A8" if s.get("kind") == "llm" else "#F58518" for s in spans
        ]
        labels = [
            f"#{i} [{s.get('kind', '')}] {s.get('name', '')}"
            for i, s in enumerate(spans)
        ]
        hover_texts = [
            (
                f"latency: {s.get('latency_ms', 0)} ms"
                + (f"<br>tokens: {s['tokens']}" if s.get("tokens") else "")
                + f"<br>kind: {s.get('kind', '')}"
            )
            for s in spans
        ]

        fig = go.Figure()
        for i, s in enumerate(spans):
            fig.add_trace(
                go.Bar(
                    orientation="h",
                    x=[latencies[i]],
                    y=[labels[i]],
                    base=[starts[i]],
                    marker_color=colors[i],
                    hovertext=hover_texts[i],
                    hoverinfo="text",
                    showlegend=False,
                )
            )

        # Legend entries
        fig.add_trace(
            go.Bar(
                orientation="h",
                x=[None],
                y=[None],
                marker_color="#4C78A8",
                name="LLM call",
            )
        )
        fig.add_trace(
            go.Bar(
                orientation="h",
                x=[None],
                y=[None],
                marker_color="#F58518",
                name="Tool call",
            )
        )

        chart_height = max(200, 60 * len(spans))
        fig.update_layout(
            height=chart_height,
            xaxis_title="Cumulative latency (ms)",
            yaxis_autorange="reversed",
            barmode="overlay",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
            margin={"l": 10, "r": 10, "t": 30, "b": 40},
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── Span detail expanders ──────────────────────────────────────────────
        st.subheader("Span Details")
        for i, s in enumerate(spans):
            label = (
                f"#{i} [{s.get('kind', '')}] {s.get('name', '')} "
                f"— {s.get('latency_ms', 0)} ms"
            )
            with st.expander(label):
                left, right = st.columns(2)
                with left:
                    st.markdown("**Input**")
                    try:
                        st.json(json.loads(s.get("input", "null")))
                    except (json.JSONDecodeError, TypeError):
                        st.text(s.get("input", ""))
                with right:
                    st.markdown("**Output**")
                    try:
                        st.json(json.loads(s.get("output", "null")))
                    except (json.JSONDecodeError, TypeError):
                        st.text(s.get("output", ""))
