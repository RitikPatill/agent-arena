"""Configs CRUD page."""

from __future__ import annotations

import json

import streamlit as st

from agent_arena.dashboard import api_client

st.title("Agent Configs")

# ── List ──────────────────────────────────────────────────────────────────────
try:
    configs = api_client.list_configs()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

if configs:
    display = [
        {
            "id": c["id"],
            "name": c["name"],
            "provider": c["provider"],
            "model": c["model"],
            "tools": ", ".join(c.get("tools") or []),
        }
        for c in configs
    ]
    st.dataframe(display, use_container_width=True)

    st.subheader("Delete a config")
    for c in configs:
        if st.button(f"Delete {c['name']}", key=f"del_{c['id']}"):
            try:
                api_client.delete_config(c["id"])
                st.success(f"Deleted {c['name']}")
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
else:
    st.info("No configs yet. Add one below.")

# ── Add ───────────────────────────────────────────────────────────────────────
with st.expander("Add Config"):
    with st.form("add_config_form"):
        name = st.text_input("Name", placeholder="my-agent")
        provider = st.selectbox("Provider", ["anthropic", "openai"])
        model = st.text_input("Model", placeholder="claude-haiku-4-5-20251001")
        system_prompt = st.text_area(
            "System Prompt", value="You are a helpful assistant."
        )
        tools_raw = st.text_input(
            "Tools (comma-separated)", placeholder="calculator, web_search_stub"
        )
        params_raw = st.text_area("Extra params (JSON)", value="{}")
        submitted = st.form_submit_button("Create Config")

    if submitted:
        tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
        try:
            params = json.loads(params_raw) if params_raw.strip() else {}
        except json.JSONDecodeError:
            st.error("Extra params must be valid JSON.")
            st.stop()

        payload = {
            "name": name,
            "provider": provider,
            "model": model,
            "system_prompt": system_prompt,
            "tools": tools,
            "params": params,
        }
        try:
            created = api_client.create_config(payload)
            st.success(f"Created config: {created['id']} ({created['name']})")
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))
