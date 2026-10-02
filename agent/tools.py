"""
Tool functions the agent calls during Phase A. Each function is a thin
wrapper around a GraphStore method, decorated with @beta_tool so the
Anthropic SDK can turn it into a tool schema automatically from its type
hints and docstring.

build_tools() returns the tool set bound to a shared `trace` list. Every
call records its input and result into that list as a side effect, which
is how Phase B (agent/orchestrator.py) gets the full record of what the
agent looked up, since the SDK's tool runner does not expose that history
directly.
"""
import json

from anthropic import beta_tool

from graph.store import GraphStore

_store = GraphStore()


def build_tools(trace: list[dict]) -> list:
    def _record(name: str, tool_input: dict, result: dict) -> str:
        trace.append({"tool": name, "input": tool_input, "result": result})
        return json.dumps(result)

    @beta_tool
    def find_drug(name: str) -> str:
        """Look up a drug in the graph by generic or brand name and return
        its known drug class and route of administration.

        Args:
            name: Generic or brand name, for example "warfarin" or "Coumadin".
        """
        drug = _store.find_drug(name)
        return _record("find_drug", {"name": name}, {"found": drug is not None, "drug": drug})

    @beta_tool
    def get_drug_interactions(drug_name: str) -> str:
        """List all drugs in the graph with a known direct interaction
        against the given drug, each with its supporting evidence source.

        Args:
            drug_name: Generic or brand name of the drug.
        """
        result = {"interactions": _store.get_interactions(drug_name)}
        return _record("get_drug_interactions", {"drug_name": drug_name}, result)

    @beta_tool
    def get_drug_conditions(drug_name: str) -> str:
        """List the conditions the given drug is indicated to treat, each
        with its supporting evidence source.

        Args:
            drug_name: Generic or brand name of the drug.
        """
        result = {"conditions": _store.get_conditions_treated(drug_name)}
        return _record("get_drug_conditions", {"drug_name": drug_name}, result)

    @beta_tool
    def check_co_prescription(drug_a: str, drug_b: str) -> str:
        """Check whether two drugs have a known direct interaction in the
        graph. Use this first for any question about co-prescribing two
        drugs together.

        Args:
            drug_a: Generic or brand name of the first drug.
            drug_b: Generic or brand name of the second drug.
        """
        result = _store.check_interaction(drug_a, drug_b)
        return _record("check_co_prescription", {"drug_a": drug_a, "drug_b": drug_b}, result)

    return [find_drug, get_drug_interactions, get_drug_conditions, check_co_prescription]


def example_question() -> str | None:
    """Returns a ready-to-run demo question built from a real interaction
    edge in the currently loaded graph, so the CLI and UI can suggest a
    question that is guaranteed to work no matter what the seed data
    build script happened to fetch. Returns None if the graph has no
    interaction edges at all (shouldn't happen, but don't crash if it does)."""
    for u, v, data in _store.g.edges(data=True):
        if data.get("type") == "INTERACTS_WITH":
            a = _store.g.nodes[u]["generic_name"]
            b = _store.g.nodes[v]["generic_name"]
            return f"Can {a} and {b} be co-prescribed?"
    return None
