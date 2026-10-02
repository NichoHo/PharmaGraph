"""Minimal smoke test. Builds a tiny in-memory graph by hand (no network
call, no dependency on data/seed/graph.json existing) and checks that
GraphStore's query methods return what the graph actually contains.

Run directly: python tests/test_graph_smoke.py
Or with pytest, if you have it installed: pytest tests/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import networkx as nx

from graph.store import GraphStore


def _tiny_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_node("drug:warfarin", type="Drug", generic_name="Warfarin", brand_names=["Coumadin"], substance_name=["WARFARIN"], route=["ORAL"])
    g.add_node("drug:aspirin", type="Drug", generic_name="Aspirin", brand_names=[], substance_name=["ASPIRIN"], route=["ORAL"])
    g.add_node("drug:metformin", type="Drug", generic_name="Metformin", brand_names=[], substance_name=["METFORMIN"], route=["ORAL"])
    g.add_node("condition:atrial fibrillation", type="Condition", name="Atrial Fibrillation")
    g.add_node("evidence:test1", type="EvidenceSource", title="Warfarin label", url="https://example.test/1", effective_time="20250101")
    g.add_edge("drug:warfarin", "evidence:test1", type="HAS_EVIDENCE")
    g.add_edge("drug:warfarin", "condition:atrial fibrillation", type="TREATS", evidence_id="evidence:test1")
    g.add_edge("drug:warfarin", "drug:aspirin", key="INTERACTS_WITH", type="INTERACTS_WITH", evidence_id="evidence:test1")
    g.add_edge("drug:aspirin", "drug:warfarin", key="INTERACTS_WITH", type="INTERACTS_WITH", evidence_id="evidence:test1")
    return g


def _store_from(g: nx.MultiDiGraph) -> GraphStore:
    store = GraphStore.__new__(GraphStore)  # bypass file loading
    store.g = g
    store._name_index = store._build_name_index()
    return store


def test_find_drug_by_generic_and_brand_name():
    store = _store_from(_tiny_graph())
    assert store.find_drug("warfarin")["generic_name"] == "Warfarin"
    assert store.find_drug("Coumadin")["generic_name"] == "Warfarin"
    assert store.find_drug("nonexistent drug") is None


def test_get_interactions_returns_neighbor_and_evidence():
    store = _store_from(_tiny_graph())
    interactions = store.get_interactions("warfarin")
    assert any(i["drug"] == "Aspirin" for i in interactions), interactions
    assert all(i["evidence"] is not None for i in interactions)


def test_get_conditions_treated():
    store = _store_from(_tiny_graph())
    conditions = store.get_conditions_treated("warfarin")
    assert any(c["condition"] == "Atrial Fibrillation" for c in conditions), conditions


def test_check_interaction_found_and_not_found():
    store = _store_from(_tiny_graph())
    found = store.check_interaction("warfarin", "aspirin")
    assert found["found"] is True, found
    not_found = store.check_interaction("warfarin", "metformin")
    assert not_found["found"] is False, not_found


if __name__ == "__main__":
    test_find_drug_by_generic_and_brand_name()
    test_get_interactions_returns_neighbor_and_evidence()
    test_get_conditions_treated()
    test_check_interaction_found_and_not_found()
    print("test_graph_smoke: all checks passed")
