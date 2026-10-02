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
TARGET_RECORDS = 1500
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
        resp = requests.get(
            OPENFDA_URL,
            params={
                "search": 'openfda.product_type:"HUMAN PRESCRIPTION DRUG"',
                "limit": PAGE_SIZE,
                "skip": skip,
            },
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json().get("results", [])
        if not batch:
            break
        records.extend(batch)
        skip += PAGE_SIZE
        time.sleep(0.3)
    return records[:TARGET_RECORDS]


def clean_class_name(cls: str) -> str:
    return re.sub(r"\s*\[EPC\]\s*$", "", cls).strip()


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
            cls = clean_class_name(cls)
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
