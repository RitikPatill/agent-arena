"""AgentArena Streamlit dashboard — home / landing page."""

from __future__ import annotations

import streamlit as st

from . import api_client

st.set_page_config(page_title="AgentArena", layout="wide")

st.title("AgentArena")
st.markdown(
    """
**AgentArena** is an open-source evaluation harness for LLM agents.

Define agent configs, run them against task suites, judge outputs with an LLM,
and compare head-to-head in seconds.

---

### Quick start

```bash
# Terminal 1 — start the API server
uvicorn agent_arena.api:app --reload

# Terminal 2 — start this dashboard
arena dashboard
```

Then navigate to the **Arena** page and click **Run Demo** to see a live evaluation.
"""
)

st.divider()
st.subheader("API Status")

try:
    configs = api_client.list_configs()
    st.success(
        f"API reachable at `{api_client.ARENA_API_URL}` — "
        f"{len(configs)} config(s) stored."
    )
except RuntimeError as e:
    st.error(str(e))
