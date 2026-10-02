"""The two-phase agent flow described at the top of Phase 3."""
import json

from anthropic import Anthropic

from .prompts import AGENT_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT
from .tools import build_tools

MODEL = "claude-sonnet-5"

FINAL_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "The final answer, in plain English."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "confidence_reason": {"type": "string", "description": "One sentence on why this confidence level."},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["id", "title", "url"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "confidence", "confidence_reason", "citations"],
    "additionalProperties": False,
}


def ask(question: str, client: Anthropic | None = None) -> dict:
    """Runs the full agent flow and returns a dict with answer, confidence,
    confidence_reason, citations, and trace (the list of graph lookups made)."""
    client = client or Anthropic()
    trace: list[dict] = []
    tools = build_tools(trace)

    # Phase A: decompose and traverse. Claude calls graph tools until it has
    # enough facts to answer, or gives up. We only need the trace this
    # produces as a side effect; the free-text answer from this phase is
    # discarded in favor of Phase B's structured one.
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=2048,
        system=AGENT_SYSTEM_PROMPT,
        tools=tools,
        messages=[{"role": "user", "content": question}],
        max_iterations=6,
    )
    for _ in runner:
        pass  # draining the iterator is what runs the tool calls

    # Phase B: synthesize a cited, confidence-scored answer from the trace.
    synthesis_input = {"question": question, "graph_lookups": trace}
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYNTHESIS_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": FINAL_ANSWER_SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(synthesis_input)}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    result = json.loads(text)
    result["trace"] = trace
    return result
