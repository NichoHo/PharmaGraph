# PharmaGraph, Project Blueprint

A GraphRAG portfolio project: a small life-sciences knowledge graph (drugs, conditions, interactions, evidence sources), a retrieval layer that walks that graph instead of doing flat vector search, and a Claude-powered agent that decomposes a question, traverses the graph, and returns a cited, confidence-scored answer.

This document is the full build plan. It is written so that an AI coding assistant with no other context can implement the project by following it phase by phase, using the exact file paths and code given. Follow the phases in order. Each phase ends with something you can run and check before moving to the next one.

**This is a demo project. It is not a medical device, and its answers are not medical advice.** Say this in the CLI output too (Phase 4 covers that).

---

## 1. What you are building

Five pieces, matching the original brief:

1. **A small graph dataset**: drugs, conditions, drug-drug interactions, and evidence sources, built from real (but lightly processed) FDA drug label data. A few hundred entities is the target, not thousands.
2. **A graph store**: an in-memory graph (Python's `networkx` library) holding those entities and relationships. A Neo4j-backed version is an optional later swap, not required for the base build.
3. **A retrieval layer**: functions that answer questions by walking the graph (find a node, follow an edge, check for a direct relationship) instead of embedding text and doing nearest-neighbor search. This is the "Graph" in GraphRAG.
4. **An agent flow**: takes a question like "can warfarin and aspirin be co-prescribed?", calls graph-query tools to gather facts, then writes a final answer with a confidence level and citations back to the specific evidence records used.
5. **A CLI demo**: a small command-line program that runs the whole pipeline and prints the question, the graph lookups the agent made, and the final cited answer. A basic web UI is an optional stretch phase.

### Non-goals (read this before adding anything not listed below)

- Not a clinical decision support tool. No real-world medical validation of any kind.
- No user accounts, no login, no multi-user database.
- No production database engine required. `networkx` plus a JSON file is the whole graph store for the base build.
- No LangChain or LlamaIndex in the base build. See section 2 for why.
- Dataset target is roughly 150 to 400 entities. Do not try to ingest the full FDA label corpus; that is out of scope and will not make the demo better.
- No deployment/hosting setup is required for the base build. The CLI running locally satisfies the brief. A public web demo is covered as an explicit opt-in in the last phase, because it changes the security posture.

If a phase below tempts you to add something not on this list (an ORM, a task queue, a config framework, extra abstraction layers), do not. Every phase says exactly what files to create.

---

## 2. Tech stack and key decisions

| Choice | Decision | Why |
|---|---|---|
| Language | Python 3.11+ | Matches the brief, best library support for both `networkx` and the Anthropic SDK. |
| Graph store | `networkx` (in-memory, persisted as JSON) | No infrastructure to install or run. A Neo4j swap-in is Phase 6 (optional) if you want the "real graph database" line on your resume too. |
| LLM | Anthropic Claude, via the official `anthropic` Python SDK | Required by the brief. |
| Agent orchestration framework | None. Direct SDK tool use (the `anthropic` package's built-in Tool Runner). | LangChain and LlamaIndex add a dependency and an abstraction layer for something this project can do in about 150 lines of direct SDK calls. Writing it directly is less code, has fewer moving parts to break for someone unfamiliar with a framework's API, and is arguably more credible in an interview since you can explain every line. If you want LangChain/LlamaIndex on your resume as well, it is a Phase 3 alternate implementation, not a rewrite of anything else. |
| UI | CLI (required), Streamlit (optional stretch, Phase 5) | The brief says the UI does not need to be polished. |
| Data source | openFDA Drug Label API (`https://api.fda.gov/drug/label.json`), no API key required for this project's request volume | Real, free, public, structured-enough regulatory data. DrugBank's full dataset needs a paid license; its open data extract is smaller and less consistently structured than openFDA's label API for this purpose. |

### Model to use

Default to `claude-opus-5` everywhere in the code below. If you want cheaper, faster iteration while developing, swap the `MODEL` constant in `agent/orchestrator.py` to `claude-sonnet-5`. That is a cost/quality tradeoff for you to make, not something to change silently.

---

## 3. Project layout

Create exactly these files. Nothing else, unless a later phase says to add it.

```
pharmagraph/
├── BLUEPRINT.md
├── requirements.txt
├── .env.example
├── .gitignore
├── data/
│   └── seed/
│       └── graph.json          (generated by Phase 1, do not hand-write)
├── scripts/
│   └── build_seed_data.py      (Phase 1)
├── graph/
│   ├── __init__.py
│   └── store.py                (Phase 2)
├── agent/
│   ├── __init__.py
│   ├── prompts.py               (Phase 3)
│   ├── tools.py                 (Phase 3)
│   └── orchestrator.py          (Phase 3)
├── cli.py                       (Phase 4)
├── app.py                       (Phase 5, optional stretch)
└── tests/
    └── test_graph_smoke.py      (Phase 2)
```

---

## Phase 0: Project setup

**Goal:** a working Python environment with the two dependencies you need to start.

1. Create the project folder and a virtual environment:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
```

2. Create `requirements.txt`:

```
anthropic>=0.68.0
networkx>=3.2,<4
requests>=2.31
python-dotenv>=1.0
```

(Streamlit is added in Phase 5 only if you build the optional UI.)

3. Install: `pip install -r requirements.txt`

4. Create `.env.example`:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Copy it to a real `.env` file and put your actual key there. `.env` must never be committed.

5. Create `.gitignore`:

```
.env
__pycache__/
*.pyc
.venv/
venv/
data/seed/graph.json
```

(`data/seed/graph.json` is generated in Phase 1. Committing a generated file is fine too if you want the repo to work without running the build script; either choice is reasonable. If you do want it committed for reproducibility, remove that line.)

6. If you have not already, get an Anthropic API key from the Anthropic Console and put it in `.env`. Do not hardcode it anywhere in the code.

**Check before moving on:** `pip list` shows `anthropic`, `networkx`, `requests`, and `python-dotenv` installed.

---

## Phase 1: Seed dataset

**Goal:** a JSON file at `data/seed/graph.json` holding a `networkx` graph with roughly 150 to 400 real drugs, their drug classes, the conditions they treat, drug-drug interactions, and one evidence-source node per drug pointing back to the FDA label record it came from.

### 1.1 Graph schema

Four node types, four edge types. Every edge that states a medical fact carries an `evidence_id` pointing at the `EvidenceSource` node it came from, so the retrieval layer can always answer "what is this based on."

**Nodes**

| Type | Key attributes |
|---|---|
| `Drug` | `generic_name`, `brand_names` (list), `substance_name` (list), `route` (list) |
| `Condition` | `name` |
| `DrugClass` | `name` |
| `EvidenceSource` | `source_type`, `title`, `url`, `effective_time` |

**Edges** (all directed; `INTERACTS_WITH` is added in both directions so you can traverse from either drug)

| Edge | From, To | Meaning |
|---|---|---|
| `TREATS` | Drug, Condition | Drug is indicated to treat this condition (`evidence_id` set) |
| `IN_CLASS` | Drug, DrugClass | Drug belongs to this pharmacologic class |
| `INTERACTS_WITH` | Drug, Drug | A known interaction is documented between these two drugs (`evidence_id` set) |
| `HAS_EVIDENCE` | Drug, EvidenceSource | This drug's facts come from this FDA label record |

### 1.2 Build script

Create `scripts/build_seed_data.py`:

```python
"""
Fetches drug label records from openFDA, extracts a small structured
graph (Drug, Condition, DrugClass, EvidenceSource nodes plus TREATS,
INTERACTS_WITH, IN_CLASS, HAS_EVIDENCE edges), and writes it to
data/seed/graph.json in networkx node-link format.

Run once: python scripts/build_seed_data.py

If openFDA is unreachable, this falls back to a small hardcoded dataset
(FALLBACK_RECORDS below) so the project still works offline. Extend that
list with more entries in the same shape if you want a bigger offline
fallback.
"""
import json
import re
import time
from pathlib import Path

import networkx as nx
import requests

OPENFDA_URL = "https://api.fda.gov/drug/label.json"
PAGE_SIZE = 100
TARGET_RECORDS = 300
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "seed" / "graph.json"

# Controlled vocabulary for condition extraction: keyword found in the
# label's "indications_and_usage" text, mapped to a canonical condition
# name. This is a deliberate simplification. Real condition extraction
# would use a medical NER model or a full ontology such as SNOMED CT.
# A fixed keyword list is enough for a demo graph and adds no extra
# dependency. Extend this list to grow the graph's condition coverage.
CONDITION_KEYWORDS = {
    "hypertension": "Hypertension",
    "high blood pressure": "Hypertension",
    "type 2 diabetes": "Type 2 Diabetes",
    "diabetes mellitus": "Type 2 Diabetes",
    "major depressive disorder": "Major Depressive Disorder",
    "depression": "Major Depressive Disorder",
    "generalized anxiety disorder": "Generalized Anxiety Disorder",
    "anxiety": "Generalized Anxiety Disorder",
    "insomnia": "Insomnia",
    "asthma": "Asthma",
    "seizures": "Epilepsy",
    "epilepsy": "Epilepsy",
    "migraine": "Migraine",
    "gastroesophageal reflux": "GERD",
    "heartburn": "GERD",
    "acid reflux": "GERD",
    "hypercholesterolemia": "High Cholesterol",
    "high cholesterol": "High Cholesterol",
    "bacterial infection": "Bacterial Infection",
    "urinary tract infection": "Urinary Tract Infection",
    "atrial fibrillation": "Atrial Fibrillation",
    "heart failure": "Heart Failure",
    "osteoarthritis": "Osteoarthritis",
    "rheumatoid arthritis": "Rheumatoid Arthritis",
    "allergic rhinitis": "Allergic Rhinitis",
    "hypothyroidism": "Hypothyroidism",
    "nausea": "Nausea",
    "chronic obstructive pulmonary disease": "COPD",
}

# Small offline fallback so the project still runs without network access.
# Shape matches a trimmed openFDA record. Add more entries the same way
# if you want a bigger offline dataset.
FALLBACK_RECORDS = [
    {
        "id": "fallback-warfarin",
        "effective_time": "20250101",
        "openfda": {
            "generic_name": ["warfarin sodium"],
            "brand_name": ["Coumadin"],
            "substance_name": ["WARFARIN SODIUM"],
            "route": ["ORAL"],
            "pharm_class_epc": ["Vitamin K Antagonist"],
        },
        "indications_and_usage": ["Warfarin is indicated for prophylaxis and treatment of atrial fibrillation and venous thrombosis."],
        "drug_interactions": ["Concomitant use with aspirin or ibuprofen increases the risk of bleeding."],
    },
    {
        "id": "fallback-aspirin",
        "effective_time": "20250101",
        "openfda": {
            "generic_name": ["aspirin"],
            "brand_name": ["Bayer Aspirin"],
            "substance_name": ["ASPIRIN"],
            "route": ["ORAL"],
            "pharm_class_epc": ["Nonsteroidal Anti-inflammatory Drug"],
        },
        "indications_and_usage": ["For the treatment of pain and to reduce the risk of heart attack."],
        "drug_interactions": ["Use with warfarin increases bleeding risk. Avoid combination with ibuprofen."],
    },
    {
        "id": "fallback-ibuprofen",
        "effective_time": "20250101",
        "openfda": {
            "generic_name": ["ibuprofen"],
            "brand_name": ["Advil"],
            "substance_name": ["IBUPROFEN"],
            "route": ["ORAL"],
            "pharm_class_epc": ["Nonsteroidal Anti-inflammatory Drug"],
        },
        "indications_and_usage": ["Ibuprofen is indicated for the treatment of pain and osteoarthritis."],
        "drug_interactions": ["Concurrent use with aspirin or warfarin may increase the risk of gastrointestinal bleeding."],
    },
    {
        "id": "fallback-metformin",
        "effective_time": "20250101",
        "openfda": {
            "generic_name": ["metformin hydrochloride"],
            "brand_name": ["Glucophage"],
            "substance_name": ["METFORMIN HYDROCHLORIDE"],
            "route": ["ORAL"],
            "pharm_class_epc": ["Biguanide"],
        },
        "indications_and_usage": ["Metformin is indicated for the treatment of type 2 diabetes mellitus."],
        "drug_interactions": ["No clinically significant interactions with lisinopril have been established."],
    },
    {
        "id": "fallback-lisinopril",
        "effective_time": "20250101",
        "openfda": {
            "generic_name": ["lisinopril"],
            "brand_name": ["Zestril"],
            "substance_name": ["LISINOPRIL"],
            "route": ["ORAL"],
            "pharm_class_epc": ["ACE Inhibitor"],
        },
        "indications_and_usage": ["Lisinopril is indicated for the treatment of hypertension and heart failure."],
        "drug_interactions": ["Use with ibuprofen may reduce the antihypertensive effect and impair kidney function."],
    },
    {
        "id": "fallback-sertraline",
        "effective_time": "20250101",
        "openfda": {
            "generic_name": ["sertraline hydrochloride"],
            "brand_name": ["Zoloft"],
            "substance_name": ["SERTRALINE HYDROCHLORIDE"],
            "route": ["ORAL"],
            "pharm_class_epc": ["Selective Serotonin Reuptake Inhibitor"],
        },
        "indications_and_usage": ["Sertraline is indicated for the treatment of major depressive disorder and generalized anxiety disorder."],
        "drug_interactions": ["Concomitant use with aspirin may increase the risk of bleeding."],
    },
]


def normalize(name: str) -> str:
    return name.strip().lower()


def fetch_records() -> list[dict]:
    records: list[dict] = []
    skip = 0
    while len(records) < TARGET_RECORDS:
        resp = requests.get(OPENFDA_URL, params={"limit": PAGE_SIZE, "skip": skip}, timeout=30)
        resp.raise_for_status()
        batch = resp.json().get("results", [])
        if not batch:
            break
        records.extend(batch)
        skip += PAGE_SIZE
        time.sleep(0.3)  # be polite to the free, unauthenticated tier
    return records[:TARGET_RECORDS]


def build_graph(records: list[dict]) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    drug_id_by_name: dict[str, str] = {}
    text_and_evidence_by_drug: dict[str, tuple[str, str]] = {}

    # Pass 1: nodes plus TREATS and IN_CLASS edges.
    for rec in records:
        openfda = rec.get("openfda", {})
        generic_names = openfda.get("generic_name", [])
        if not generic_names:
            continue
        generic_name = generic_names[0].title()
        drug_id = f"drug:{normalize(generic_name)}"
        if drug_id in g:
            continue  # skip duplicate labels for the same drug

        brand_names = [b.title() for b in openfda.get("brand_name", [])]
        record_id = rec.get("id", drug_id)
        evidence_id = f"evidence:{record_id}"

        g.add_node(
            evidence_id,
            type="EvidenceSource",
            source_type="openFDA_drug_label",
            title=f"{generic_name}, FDA drug label",
            url=f'https://api.fda.gov/drug/label.json?search=id:"{record_id}"',
            effective_time=rec.get("effective_time", ""),
        )
        g.add_node(
            drug_id,
            type="Drug",
            generic_name=generic_name,
            brand_names=brand_names,
            substance_name=openfda.get("substance_name", []),
            route=openfda.get("route", []),
        )
        g.add_edge(drug_id, evidence_id, type="HAS_EVIDENCE")

        for cls in openfda.get("pharm_class_epc", []):
            class_id = f"class:{normalize(cls)}"
            if class_id not in g:
                g.add_node(class_id, type="DrugClass", name=cls)
            g.add_edge(drug_id, class_id, type="IN_CLASS")

        indications = " ".join(rec.get("indications_and_usage", [])).lower()
        for keyword, condition_name in CONDITION_KEYWORDS.items():
            if keyword in indications:
                condition_id = f"condition:{normalize(condition_name)}"
                if condition_id not in g:
                    g.add_node(condition_id, type="Condition", name=condition_name)
                g.add_edge(drug_id, condition_id, type="TREATS", evidence_id=evidence_id)

        drug_id_by_name[normalize(generic_name)] = drug_id
        for b in brand_names:
            drug_id_by_name[normalize(b)] = drug_id

        interaction_text = " ".join(rec.get("drug_interactions", [])).lower()
        text_and_evidence_by_drug[drug_id] = (interaction_text, evidence_id)

    # Pass 2: INTERACTS_WITH edges. Regex-match every other known drug name
    # against this drug's free-text interactions section. This is a
    # heuristic, not a clinically validated extraction: it will miss real
    # interactions and can produce false positives on short name overlaps.
    # Good enough for a demo graph, not for anything else.
    all_names_longest_first = sorted(drug_id_by_name.keys(), key=len, reverse=True)
    for drug_id, (text, evidence_id) in text_and_evidence_by_drug.items():
        for name in all_names_longest_first:
            other_id = drug_id_by_name[name]
            if other_id == drug_id:
                continue
            if re.search(rf"\b{re.escape(name)}\b", text):
                if not g.has_edge(drug_id, other_id, key="INTERACTS_WITH"):
                    g.add_edge(drug_id, other_id, key="INTERACTS_WITH", type="INTERACTS_WITH", evidence_id=evidence_id)
                    g.add_edge(other_id, drug_id, key="INTERACTS_WITH", type="INTERACTS_WITH", evidence_id=evidence_id)

    return g


def main() -> None:
    try:
        records = fetch_records()
        print(f"Fetched {len(records)} records from openFDA")
    except requests.RequestException as e:
        print(f"openFDA fetch failed ({e}); using the small offline fallback dataset")
        records = FALLBACK_RECORDS

    g = build_graph(records)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # networkx renamed the link/edges parameter across 3.x versions.
    # Passing edges="edges" explicitly here avoids version-dependent
    # default key names; graph/store.py reads it back with the same
    # explicit argument.
    data = nx.node_link_data(g, edges="edges")
    OUTPUT_PATH.write_text(json.dumps(data, indent=2))
    print(f"Wrote {g.number_of_nodes()} nodes and {g.number_of_edges()} edges to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
```

Run it:

```bash
python scripts/build_seed_data.py
```

**Check before moving on:** `data/seed/graph.json` exists and the script printed a node and edge count in the hundreds (or, if you ran offline, the small fallback graph built without error).

---

## Phase 2: Graph store (retrieval layer)

**Goal:** a `GraphStore` class that loads `data/seed/graph.json` and answers graph-walk queries. This class is both "the graph store" and "the retrieval layer" from the brief; splitting those into two files would be one class too many for what it does.

Create `graph/__init__.py` (empty file) and `graph/store.py`:

```python
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

    def get_evidence(self, node_id: str) -> list[dict]:
        results = []
        for nbr, edges in self.g[node_id].items():
            if any(e.get("type") == "HAS_EVIDENCE" for e in edges.values()):
                results.append({"id": nbr, **self.g.nodes[nbr]})
        return results

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
```

### Smoke test

Non-trivial logic here (multi-edge lookups, direction handling) needs one runnable check. Create `tests/test_graph_smoke.py`:

```python
"""Minimal smoke test. Builds a tiny in-memory graph by hand (no network
call, no dependency on data/seed/graph.json existing) and checks that
GraphStore's query methods return what the graph actually contains.

Run directly: python tests/test_graph_smoke.py
Or with pytest, if you have it installed: pytest tests/
"""
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
```

**Check before moving on:** `python tests/test_graph_smoke.py` prints "all checks passed" with no assertion errors. Then, separately, confirm the store loads your real generated data: `python -c "from graph.store import GraphStore; s = GraphStore(); print(len(s.g.nodes), 'nodes')"` should print a number in the hundreds.

---

## Phase 3: Agent orchestration

**Goal:** given a natural-language question, an agent that (a) decides which drugs and conditions to look up, (b) calls graph-query tools to gather facts, (c) writes a final answer with a confidence level and citations pointing only at evidence sources that were actually found.

This is a two-phase design, and both phases matter:

- **Phase A, decompose and traverse:** Claude is given the graph-query tools and the question, and calls tools until it has enough facts. Each tool call is one sub-query against the graph. This is done with the Anthropic SDK's built-in Tool Runner, so you do not hand-write the call-execute-loop cycle.
- **Phase B, synthesize:** a second Claude call, with no tools, given the full record of what Phase A looked up and what it found, asked to produce a structured JSON answer (`answer`, `confidence`, `confidence_reason`, `citations`) using the API's structured outputs feature, so the shape is guaranteed rather than hoped for.

Splitting it this way keeps each call doing one job, keeps the final answer's shape reliable, and makes the citations trustworthy: Phase B is told explicitly to cite only sources that appeared in Phase A's tool results, never to invent one.

### 3.1 Prompts

Create `agent/__init__.py` (empty file) and `agent/prompts.py`:

```python
AGENT_SYSTEM_PROMPT = """You are a pharmacology research assistant with access to a \
knowledge graph of drugs, conditions, drug classes, and interactions built \
from FDA drug label data. You do not know anything about drugs beyond what \
the tools return. Always look facts up with tools instead of answering from \
your own training knowledge.

For every question:
1. Identify the drugs and/or conditions the question is about.
2. Call tools to find each one in the graph and gather relevant facts \
   (interactions, treated conditions, drug class).
3. For any co-prescription safety question, always call check_co_prescription.
4. Base your answer only on what the tools returned. If the graph has no \
   data on something, say so explicitly instead of guessing.

This is a portfolio and demo project, not a medical device. Never state or \
imply a clinical recommendation. Describe only what the graph data shows."""

SYNTHESIS_SYSTEM_PROMPT = """You write the final answer for a pharmacology \
graph-RAG demo, given a record of graph tool calls and their results.

Rules:
- Base the answer only on the tool results provided. Do not add outside \
  medical knowledge.
- Set confidence to "high" only if a direct, relevant graph edge \
  (interaction or treats) with evidence was found. Use "medium" if only \
  indirect or related evidence was found, for example the same drug \
  class but no direct interaction edge. Use "low" if no relevant data was \
  found in the graph.
- List a citation only if its evidence source actually appeared in the \
  tool results. Never invent a source.
- If the graph found no direct interaction edge between two drugs, say so \
  plainly. An absent edge means "not found in this graph," not "no \
  interaction exists." Do not imply the drugs are safe to combine just \
  because no edge was found."""
```

### 3.2 Tools

Create `agent/tools.py`:

```python
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
```

### 3.3 Orchestrator

Create `agent/orchestrator.py`:

```python
"""The two-phase agent flow described at the top of Phase 3."""
import json

from anthropic import Anthropic

from .prompts import AGENT_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT
from .tools import build_tools

MODEL = "claude-opus-5"  # swap to "claude-sonnet-5" for cheaper, faster iteration if you want; your call

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
```

**Check before moving on:** with a valid `ANTHROPIC_API_KEY` in `.env`, run:

```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from agent.orchestrator import ask
r = ask('Can warfarin and aspirin be co-prescribed?')
print(r['answer'])
print(r['confidence'], '-', r['confidence_reason'])
print(r['trace'])
"
```

You should see a natural-language answer, a confidence level, and at least one `check_co_prescription` call in the trace. If the fallback dataset from Phase 1 is what you built (it has a warfarin-aspirin interaction), confidence should come back "high."

---

## Phase 4: CLI demo

**Goal:** a REPL that takes a question, prints the graph lookups the agent made (this is the visible "decomposition" the brief asks for), and prints the final cited answer.

Create `cli.py`:

```python
"""
PharmaGraph CLI demo. Type a question, see the graph lookups the agent
made, and get a cited, confidence-scored answer.

Not medical advice. Portfolio and demo project only.
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from agent.orchestrator import ask  # noqa: E402 (import after load_dotenv on purpose)

DISCLAIMER = (
    "PharmaGraph is a portfolio demo built on a small, heuristically extracted\n"
    "sample of FDA drug label data. It is not medical advice and must never be\n"
    "used for real prescribing decisions."
)


def print_result(result: dict) -> None:
    print("\nGraph lookups:")
    for step in result["trace"]:
        print(f"  {step['tool']}({step['input']})")

    print("\nAnswer:")
    print(f"  {result['answer']}")
    print(f"\nConfidence: {result['confidence']} ({result['confidence_reason']})")

    if result["citations"]:
        print("\nCitations:")
        for c in result["citations"]:
            print(f"  - {c['title']}: {c['url']}")

    print(f"\n{DISCLAIMER}")


def main() -> None:
    print("PharmaGraph, a GraphRAG demo. Type a question, or 'quit' to exit.")
    print(DISCLAIMER)
    print(
        "\nTry: \"Can warfarin and aspirin be co-prescribed?\", "
        "\"What does metformin treat?\", "
        "\"Is there an interaction between ibuprofen and warfarin?\""
    )
    while True:
        question = input("\n> ").strip()
        if question.lower() in {"quit", "exit"}:
            break
        if not question:
            continue
        if len(question) > 500:
            print("Question is too long; keep it under 500 characters.")
            continue
        try:
            result = ask(question)
        except Exception as e:  # surface a clean message, never a raw traceback, to the CLI user
            print(f"Something went wrong answering that question: {e}")
            continue
        print_result(result)


if __name__ == "__main__":
    sys.exit(main())
```

Run it: `python cli.py`

**Check before moving on:** ask each of the three suggested questions and confirm you get a graph lookup trace, an answer, a confidence level, and (when relevant) citations for each one. This is the finished base project. Phases 5 and 6 below are optional.

---

## Phase 5 (optional stretch): Basic web UI

If you want a UI instead of, or alongside, the CLI, add Streamlit. This does not replace anything above; it is a second front end on the same `agent.orchestrator.ask()` function.

1. Add `streamlit>=1.35` to `requirements.txt` and `pip install streamlit`.
2. Create `app.py`:

```python
"""PharmaGraph Streamlit demo. Same agent as cli.py, a UI on top of it."""
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agent.orchestrator import ask  # noqa: E402

st.set_page_config(page_title="PharmaGraph", page_icon="🧬")
st.title("PharmaGraph")
st.caption(
    "GraphRAG demo over a small FDA-label-derived drug graph. "
    "Not medical advice, portfolio project only."
)

question = st.text_input("Ask a question", max_chars=500, placeholder="Can warfarin and aspirin be co-prescribed?")

if st.button("Ask") and question:
    with st.spinner("Walking the graph..."):
        result = ask(question)

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
```

3. Run it: `streamlit run app.py`

If you deploy this publicly (Streamlit Community Cloud, Hugging Face Spaces, etc.), read the deployment note in the Security phase below first; a public link that anyone can hit changes what you need to guard against.

---

## Phase 6 (optional stretch): Neo4j swap-in

If you want a real graph database on your resume in addition to the `networkx` version, you can swap the store without touching the agent, the tools, or the CLI, because they only depend on `GraphStore`'s method signatures, not on `networkx` itself.

1. Run Neo4j locally (Docker is the fastest path: `docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/yourpassword neo4j:5`), and `pip install neo4j`.
2. Write a one-off loader script that reads `data/seed/graph.json` and issues `MERGE` statements to create the same nodes and edges in Neo4j (one `MERGE` per node type, one `MERGE` per edge type, matching section 1.1's schema).
3. Create `graph/neo4j_store.py` with a `Neo4jGraphStore` class implementing the exact same public methods as `GraphStore` (`find_drug`, `get_interactions`, `get_conditions_treated`, `check_interaction`), each running a Cypher query instead of a networkx graph walk. For example, `check_interaction`:

```cypher
MATCH (a:Drug)-[r:INTERACTS_WITH]->(b:Drug)
WHERE toLower(a.generic_name) = toLower($drug_a) AND toLower(b.generic_name) = toLower($drug_b)
RETURN r.evidence_id AS evidence_id
LIMIT 1
```

4. In `agent/tools.py`, change the one line `from graph.store import GraphStore` to `from graph.neo4j_store import Neo4jGraphStore as GraphStore`. Nothing else changes.

This is optional and not required to satisfy the brief; the `networkx` version already demonstrates the graph-traversal retrieval pattern the brief asks for.

---

## Phase 7: Security and hardening

**Tier: T1, Personal.** This is a portfolio project built on public FDA data, with no user accounts, no real patient data, and a single developer holding the API key. Re-check this tier if the project's shape changes later, for example if you add real user accounts, connect it to actual patient or clinical data, or if a public demo link starts getting meaningful uninvited traffic; any of those would move it to T2 (Internal/Team) or higher, and pull the additional rows from `~/.claude/security-phase-checklist.md`.

What applies at T1, adapted to what this project actually has (a local CLI and, optionally, a local or lightly-deployed web demo; no database server, no user accounts):

- **Keep the API key server-side, out of git, from the first commit.** `ANTHROPIC_API_KEY` lives only in `.env`. `.env` is in `.gitignore` before you run `git add` for the first time, not after. If a key is ever committed by accident, treat it as burned: revoke it in the Anthropic Console and issue a new one, do not just delete the file from a later commit.
- **No public data leak beyond what is already public.** The graph is built from public FDA label data, so there is nothing confidential in `data/seed/graph.json`; it is fine to commit if you want the repo to run without a build step.
- **Validate and cap user input server-side**, even for a CLI. `cli.py` already caps the question at 500 characters before sending it to the API; keep that check if you build the Streamlit version too (the `max_chars` argument on `st.text_input` above does this).
- **Never show a raw traceback to the end user.** `cli.py`'s `except Exception as e: print(...)` catches errors and prints a short message instead of letting a stack trace (which can include file paths or other environment details) reach the terminal output someone might screenshot.
- **Run a dependency vulnerability scan before you publish the repo.** `pip install pip-audit && pip-audit` once, fix anything with a non-breaking patch available.
- **If you deploy the Streamlit UI publicly** (Phase 5, on Streamlit Community Cloud, Hugging Face Spaces, or similar), this is the one part of the project that meaningfully changes risk, since strangers can then trigger paid API calls:
  - Add a hard per-session or per-day question cap in `app.py` (for example, track a count in `st.session_state` and stop responding past 20 questions per session) so a stranger cannot run up your Anthropic bill.
  - Set a billing alert or spend cap on your Anthropic Console so a bug or an abuse spike is a notification, not a surprise invoice.
  - Put the API key in the platform's secret manager (Streamlit Cloud's `st.secrets`, or the hosting platform's equivalent), never in a file committed to the repo, and never printed to the page or included in any error message shown to the visitor.
  - Rely on the hosting platform's default HTTPS; do not build custom TLS handling for a project at this scale.

That is the whole security phase for a project this size. Do not add authentication, rate-limiting middleware, or a secrets vault for a local CLI with no accounts; that would be solving a problem this project does not have.
