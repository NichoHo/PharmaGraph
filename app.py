"""PharmaGraph Streamlit demo. Same agent as cli.py, a UI on top of it."""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

GRAPH_PATH = Path(__file__).parent / "data" / "seed" / "graph.json"
if not GRAPH_PATH.exists():
    st.error("No seed data found. Run `python scripts/build_seed_data.py` first, then restart this app.")
    st.stop()

from agent.orchestrator import ask  # noqa: E402
from agent.tools import example_question  # noqa: E402

st.set_page_config(page_title="PharmaGraph", page_icon="🧬")
st.title("PharmaGraph")
st.caption(
    "GraphRAG demo over a small FDA-label-derived drug graph. "
    "Not medical advice, portfolio project only."
)

placeholder_q = example_question() or "Ask about a drug in the graph"
with st.form("ask_form"):
    question = st.text_input(
        "Ask a question (Leave empty and press Enter to run the example)",
        max_chars=500,
        placeholder=placeholder_q,
    )
    submitted = st.form_submit_button("Ask")

if submitted:
    active_question = question.strip() if question.strip() else placeholder_q
    with st.spinner("Walking the graph..."):
        result = ask(active_question)

    st.subheader("Graph lookups")
    for step in result["trace"]:
        st.code(f"{step['tool']}({step['input']})", language="text")

    st.subheader("Answer")
    st.write(result["answer"])
    st.write(f"**Confidence:** {result['confidence']}, {result['confidence_reason']}")

    if result["citations"]:
        st.subheader("Citations")
        for c in result["citations"]:
            st.markdown(f"- [{c['title']}]({c['url']})")
