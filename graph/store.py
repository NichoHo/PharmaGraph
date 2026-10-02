"""
GraphStore is the retrieval layer: every public method here does a graph
walk over the in-memory networkx graph, never an LLM call and never a
vector search. That graph walk is the "Graph" part of GraphRAG. The
agent (see agent/tools.py) calls these methods; it never touches the
networkx graph directly.
"""
import json
from pathlib import Path

import networkx as nx

DEFAULT_GRAPH_PATH = Path(__file__).parent.parent / "data" / "seed" / "graph.json"


class GraphStore:
    def __init__(self, path: Path = DEFAULT_GRAPH_PATH):
        data = json.loads(Path(path).read_text())
        self.g = nx.node_link_graph(data, edges="edges")  # see the matching note in build_seed_data.py
        self._name_index = self._build_name_index()

    def _build_name_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for node_id, attrs in self.g.nodes(data=True):
            if attrs.get("type") != "Drug":
                continue
            index[attrs["generic_name"].lower()] = node_id
            for brand in attrs.get("brand_names", []):
                index[brand.lower()] = node_id
        return index

    def find_drug(self, name: str) -> dict | None:
        node_id = self._name_index.get(name.strip().lower())
        if node_id is None:
            return None
        return {"id": node_id, **self.g.nodes[node_id]}


    def get_interactions(self, drug_name: str) -> list[dict]:
        drug = self.find_drug(drug_name)
        if drug is None:
            return []
        results = []
        for nbr, edges in self.g[drug["id"]].items():
            for edge in edges.values():
                if edge.get("type") == "INTERACTS_WITH":
                    results.append({
                        "drug": self.g.nodes[nbr]["generic_name"],
                        "evidence": self._evidence_summary(edge.get("evidence_id")),
                    })
        return results

    def get_conditions_treated(self, drug_name: str) -> list[dict]:
        drug = self.find_drug(drug_name)
        if drug is None:
            return []
        results = []
        for nbr, edges in self.g[drug["id"]].items():
            for edge in edges.values():
                if edge.get("type") == "TREATS":
                    results.append({
                        "condition": self.g.nodes[nbr]["name"],
                        "evidence": self._evidence_summary(edge.get("evidence_id")),
                    })
        return results

    def check_interaction(self, drug_a: str, drug_b: str) -> dict:
        a, b = self.find_drug(drug_a), self.find_drug(drug_b)
        if a is None or b is None:
            missing = drug_a if a is None else drug_b
            return {"found": False, "reason": f"'{missing}' not found in graph"}
        for nbr, edges in self.g[a["id"]].items():
            if nbr != b["id"]:
                continue
            for edge in edges.values():
                if edge.get("type") == "INTERACTS_WITH":
                    return {"found": True, "evidence": self._evidence_summary(edge.get("evidence_id"))}
        return {"found": False, "reason": "no direct interaction edge in the graph"}

    def _evidence_summary(self, evidence_id: str | None) -> dict | None:
        if evidence_id is None or evidence_id not in self.g:
            return None
        return {"id": evidence_id, **self.g.nodes[evidence_id]}
