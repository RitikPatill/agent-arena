"""Arena page — run evaluations and view results."""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from agent_arena.dashboard import api_client

st.title("Run Arena")

# ── Sidebar controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")

    try:
        configs = api_client.list_configs()
    except RuntimeError as e:
        st.error(str(e))
        configs = []

    config_options = {c["name"]: c["id"] for c in configs}
    selected_names = st.multiselect("Agent Configs", list(config_options.keys()))
    selected_config_ids = [config_options[n] for n in selected_names]

    try:
        suites = api_client.list_task_suites()
    except RuntimeError:
        suites = []
    suite_options = {s["name"]: s["path"] for s in suites}
    suite_name = st.selectbox("Task Suite", list(suite_options.keys()) or ["(none)"])
    task_suite_path = suite_options.get(suite_name, "")

    try:
        rubrics = api_client.list_rubrics()
    except RuntimeError:
        rubrics = []
    rubric_options = {r["name"]: r["path"] for r in rubrics}
    rubric_name = st.selectbox("Rubric", list(rubric_options.keys()) or ["(none)"])
    rubric_path = rubric_options.get(rubric_name, "")

    judge_model = st.text_input("Judge model", "claude-haiku-4-5-20251001")
    max_turns = st.number_input("Max turns", min_value=1, max_value=20, value=10)

    # Previous runs
    st.divider()
    st.subheader("Previous runs")
    try:
        past_runs = api_client.list_arena_runs()
    except RuntimeError:
        past_runs = []
    run_ids = [r["id"] for r in past_runs if r.get("status") == "done"]
    if run_ids:
        load_id = st.selectbox("Load past run", [""] + run_ids)
        if load_id:
            st.session_state["last_arena_id"] = load_id

# ── Run buttons ───────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)
run_btn = col1.button("Run Arena", disabled=not selected_config_ids)
demo_btn = col2.button("Run Demo")

if run_btn or demo_btn:
    with st.spinner("Running arena — this may take a minute…"):
        try:
            if demo_btn:
                result = api_client.run_demo()
            else:
                result = api_client.start_arena_run(
                    {
                        "config_ids": selected_config_ids,
                        "task_suite_path": task_suite_path,
                        "rubric_path": rubric_path,
                        "judge_model": judge_model,
                        "judge_provider": "anthropic",
                        "max_turns": int(max_turns),
                    }
                )
            st.session_state["last_arena_id"] = result["arena_id"]
            st.success(f"Arena run complete. ID: {result['arena_id']}")
        except RuntimeError as e:
            st.error(str(e))

# ── Results ───────────────────────────────────────────────────────────────────
arena_id = st.session_state.get("last_arena_id") or st.text_input(
    "Or load arena ID", placeholder="paste an arena_id here"
)

if arena_id:
    try:
        results = api_client.get_arena_results(arena_id)
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    _render_configs = configs  # captured above; fallback to fetching fresh
    if not _render_configs:
        try:
            _render_configs = api_client.list_configs()
        except RuntimeError:
            _render_configs = []

    id_to_name = {c["id"]: c["name"] for c in _render_configs}

    config_ids: list[str] = results.get("config_ids", [])
    mean_scores: dict = results.get("mean_scores", {})
    win_rates: dict = results.get("win_rates", {})
    per_task: dict = results.get("per_task", {})

    # Criterion names (from first config that has scores)
    criterion_names: list[str] = []
    for cid in config_ids:
        if cid in mean_scores and mean_scores[cid]:
            criterion_names = list(mean_scores[cid].keys())
            break

    st.divider()

    # 1. Summary table
    st.subheader("Summary")
    summary_rows = []
    for rank, cid in enumerate(
        sorted(
            config_ids,
            key=lambda c: sum(
                mean_scores.get(c, {}).get(k, {}).get("mean", 0)
                for k in criterion_names
            )
            / max(len(criterion_names), 1),
            reverse=True,
        ),
        start=1,
    ):
        scores = mean_scores.get(cid, {})
        overall = (
            sum(scores.get(k, {}).get("mean", 0) for k in criterion_names)
            / len(criterion_names)
            if criterion_names
            else 0.0
        )
        ci_low = (
            sum(scores.get(k, {}).get("ci_low", 0) for k in criterion_names)
            / len(criterion_names)
            if criterion_names
            else 0.0
        )
        ci_high = (
            sum(scores.get(k, {}).get("ci_high", 0) for k in criterion_names)
            / len(criterion_names)
            if criterion_names
            else 0.0
        )
        summary_rows.append(
            {
                "rank": rank,
                "config": id_to_name.get(cid, cid[:8]),
                "overall": round(overall, 3),
                "ci_low": round(ci_low, 3),
                "ci_high": round(ci_high, 3),
            }
        )
    st.dataframe(summary_rows, use_container_width=True)

    # 2. Radar chart
    if criterion_names and len(config_ids) > 0:
        st.subheader("Radar Chart — per-criterion scores")
        fig_radar = go.Figure()
        categories = criterion_names + [criterion_names[0]]  # close the shape
        for cid in config_ids:
            scores = mean_scores.get(cid, {})
            values = [scores.get(k, {}).get("mean", 0) for k in criterion_names]
            values = values + [values[0]]  # close
            fig_radar.add_trace(
                go.Scatterpolar(
                    r=values,
                    theta=categories,
                    fill="toself",
                    name=id_to_name.get(cid, cid[:8]),
                )
            )
        fig_radar.update_layout(
            polar={"radialaxis": {"visible": True, "range": [0, 1]}},
            showlegend=True,
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    # 3. Win-rate heatmap
    if len(config_ids) > 1:
        st.subheader("Head-to-Head Win Rate Heatmap")
        config_names = [id_to_name.get(cid, cid[:8]) for cid in config_ids]
        z_matrix = []
        text_matrix = []
        for a in config_ids:
            row = []
            text_row = []
            for b in config_ids:
                if a == b:
                    row.append(None)
                    text_row.append("—")
                else:
                    val = win_rates.get(a, {}).get(b, 0.5)
                    row.append(val)
                    text_row.append(f"{val:.0%}")
            z_matrix.append(row)
            text_matrix.append(text_row)

        fig_heat = go.Figure(
            go.Heatmap(
                z=z_matrix,
                x=config_names,
                y=config_names,
                text=text_matrix,
                texttemplate="%{text}",
                colorscale="RdYlGn",
                zmin=0,
                zmax=1,
            )
        )
        fig_heat.update_layout(
            xaxis_title="Opponent",
            yaxis_title="Config",
        )
        st.plotly_chart(fig_heat, use_container_width=True)

    # 4. Per-task breakdown with deep-links to trace viewer
    if per_task:
        st.subheader("Per-task Scores")

        # Build run_id lookup: (config_name, task_id) -> run_id
        run_id_lookup: dict[tuple[str, str], str] = {}
        try:
            arena_run_list = api_client.get_arena_run_list(arena_id)
            for r in arena_run_list:
                key = (r.get("config_name", r["config_id"][:8]), r["task_id"])
                run_id_lookup[key] = r["id"]
        except RuntimeError:
            pass  # fall back to plain table if API unavailable

        config_display_names = [id_to_name.get(cid, cid[:8]) for cid in config_ids]
        task_ids = list(per_task.keys())

        if run_id_lookup:
            # Render interactive grid with deep-link buttons
            header_cols = st.columns([2] + [1] * len(config_display_names))
            header_cols[0].markdown("**Task**")
            for ci, cname in enumerate(config_display_names):
                header_cols[ci + 1].markdown(f"**{cname}**")

            for task_id in task_ids:
                scores_by_config = per_task[task_id]
                row_cols = st.columns([2] + [1] * len(config_display_names))
                row_cols[0].write(task_id)
                for ci, (cid, cname) in enumerate(
                    zip(config_ids, config_display_names)
                ):
                    score = round(scores_by_config.get(cid, 0.0), 3)
                    rid = run_id_lookup.get((cname, task_id))
                    if rid:
                        try:
                            row_cols[ci + 1].page_link(
                                "pages/5_Trace_Viewer.py",
                                label=str(score),
                                query_params={"run_id": rid},
                            )
                        except Exception:
                            row_cols[ci + 1].markdown(
                                f"[{score}](/Trace_Viewer?run_id={rid})",
                                unsafe_allow_html=True,
                            )
                    else:
                        row_cols[ci + 1].write(score)
        else:
            # Fallback: plain dataframe
            rows = []
            for task_id, scores_by_config in per_task.items():
                row = {"task_id": task_id}
                for cid in config_ids:
                    row[id_to_name.get(cid, cid[:8])] = round(
                        scores_by_config.get(cid, 0.0), 3
                    )
                rows.append(row)
            st.dataframe(rows, use_container_width=True)
