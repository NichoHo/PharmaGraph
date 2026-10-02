# PharmaGraph, Review Notes

I read every file against BLUEPRINT.md, then actually ran the project (installed venv, rebuilt the seed data, ran the smoke test, called the graph store directly, and inspected the real generated `data/seed/graph.json`) rather than just reading the code. Every finding below is something I reproduced, not a guess. Each one names the exact file, the exact problem, how I confirmed it, and a concrete fix.

Work through "Fix these" first; they affect whether the demo actually works. "Should fix" is real but the project still runs without them. "Not a bug" is a note for you, not something to hand to another model.

---

## Fix these

### 1. `python tests/test_graph_smoke.py` fails exactly as the blueprint tells you to run it

**File:** `tests/test_graph_smoke.py`

Running the command the file's own docstring tells you to run:

```
python tests/test_graph_smoke.py
```

fails with:

```
ModuleNotFoundError: No module named 'graph'
```

Reason: when Python runs a script directly, it only puts that script's own folder (`tests/`) on `sys.path`, not the project root, so `from graph.store import GraphStore` cannot find the `graph` package one level up. Running it as `python -m tests.test_graph_smoke` from the project root works, because `-m` puts the current directory on the path instead. That's a real fix, but it's not what the docstring tells someone to type, and it's the first thing anyone will try.

**Fix:** add these two lines to the top of `tests/test_graph_smoke.py`, before the `graph.store` import, so the file works no matter how it's invoked:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import networkx as nx

from graph.store import GraphStore
```

Then both `python tests/test_graph_smoke.py` and `python -m tests.test_graph_smoke` work.

---

### 2. The seed dataset is full of things that are not really "drugs" for this demo

**File:** `scripts/build_seed_data.py`, function `fetch_records()`

I rebuilt the seed data and looked at the actual drug names that ended up in the graph. A sample:

```
Advanced Coconut Water And Lime Dry Spray 72H Antiperspirant Deodorant
Aluminium Fluoratum
Aluminium Nitricum
Aluminium Phosphoricum
Benzalkonium Chloride
Avobenzone, Homosalate, Octisalate, And Octocrylene
```

That's an antiperspirant, three homeopathic single remedies, an antiseptic ingredient, and a sunscreen. `fetch_records()` currently queries `https://api.fda.gov/drug/label.json` with no `search` filter, so openFDA returns whatever labels it has on file in that endpoint, which includes cosmetics, sunscreens, and homeopathic products alongside real prescription drugs. Recognizable drugs (metformin, warfarin, ibuprofen, aspirin) are diluted among a lot of noise, which will look wrong to anyone trying the demo.

**Fix:** filter to prescription drugs only. openFDA supports this via the `openfda.product_type` field (confirmed against openFDA's own docs). Change the request in `fetch_records()`:

```python
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
```

After this change, rerun `python scripts/build_seed_data.py` and spot-check `data/seed/graph.json` again; the drug list should look like actual medications.

---

### 3. Only 92 unique drugs came out of a 300-record fetch

**File:** `scripts/build_seed_data.py`, constant `TARGET_RECORDS`

The real build I ran fetched 300 raw label records but only produced 92 unique `Drug` nodes (222 nodes total once you add evidence, class, and condition nodes). That is because openFDA has many separate label records for the same generic drug (different manufacturers, different package sizes), and `build_graph()` correctly skips duplicates by generic name, so most of the 300 records collapse into far fewer unique drugs. 92 is below the "roughly 150 to 400" target the blueprint set, and it directly causes finding 4 below.

**Fix:** raise `TARGET_RECORDS` so enough raw records survive deduplication. Combined with the product_type filter in finding 2, try:

```python
TARGET_RECORDS = 1500
```

Rerun the build script and check the printed node and edge counts. If the unique `Drug` count (you can check with the one-liner in the "How to check your fixes" section below) is still well under 150, raise `TARGET_RECORDS` further; there is no need to guess at the exact right number, the script tells you the result every time it runs.

---

### 4. The CLI's own example questions do not work

**File:** `cli.py` (and `app.py`), the hardcoded suggested questions

`cli.py` prints these suggestions on startup:

```
Try: "Can warfarin and aspirin be co-prescribed?", "What does metformin treat?", "Is there an interaction between ibuprofen and warfarin?"
```

I checked the real generated graph: none of warfarin, aspirin, metformin, or ibuprofen are in it. Those four names only exist in `FALLBACK_RECORDS`, the offline backup dataset, not in what actually gets pulled from openFDA. Anyone who copies the app's own suggested question gets a "not found" or low-confidence answer on their very first try, which will read as broken even though the rest of the pipeline is fine.

This will keep happening any time the seed data is rebuilt, since which specific drugs openFDA returns is not something you control. The fix should not be "hardcode a different specific drug name"; it should generate the example from whatever data is actually loaded.

**Fix:** add a small helper to `agent/tools.py` that builds a real example question from an interaction edge that actually exists in the currently loaded graph, and use it in both front ends instead of a hardcoded string.

In `agent/tools.py`, add this function (after `build_tools`, still in the same file, so it can reuse the module-level `_store` that is already loaded):

```python
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
```

In `cli.py`, replace the hardcoded suggestion block:

```python
from agent.tools import example_question  # add this import near the top, with the other agent imports
```

```python
def main() -> None:
    print("PharmaGraph, a GraphRAG demo. Type a question, or 'quit' to exit.")
    print(DISCLAIMER)
    suggestion = example_question()
    if suggestion:
        print(f'\nTry: "{suggestion}"')
    # ... rest of main() unchanged
```

In `app.py`, use the same helper for the `placeholder` argument instead of the hardcoded warfarin and aspirin string:

```python
from agent.tools import example_question  # add near the top

question = st.text_input(
    "Ask a question",
    max_chars=500,
    placeholder=example_question() or "Ask about a drug in the graph",
)
```

---

## Should fix

### 5. Drug class names carry a leftover `[EPC]` tag

**File:** `scripts/build_seed_data.py`, the `pharm_class_epc` loop in `build_graph()`

openFDA's `pharm_class_epc` field returns values like `"Nonsteroidal Anti-inflammatory Drug [EPC]"`, not the clean name. I confirmed this in the real generated data; every `DrugClass` node name in `data/seed/graph.json` ends in the literal text `[EPC]`. It is not wrong, but it looks like a data bug when it shows up in an answer or a citation, and it is cheap to clean up.

**Fix:** strip the tag when building the node:

```python
import re  # add to the existing imports at the top of build_seed_data.py

def clean_class_name(cls: str) -> str:
    return re.sub(r"\s*\[EPC\]\s*$", "", cls).strip()
```

Then in `build_graph()`, change:

```python
for cls in openfda.get("pharm_class_epc", []):
    class_id = f"class:{normalize(cls)}"
    if class_id not in g:
        g.add_node(class_id, type="DrugClass", name=cls)
    g.add_edge(drug_id, class_id, type="IN_CLASS")
```

to:

```python
for cls in openfda.get("pharm_class_epc", []):
    cls = clean_class_name(cls)
    class_id = f"class:{normalize(cls)}"
    if class_id not in g:
        g.add_node(class_id, type="DrugClass", name=cls)
    g.add_edge(drug_id, class_id, type="IN_CLASS")
```

Rerun `python scripts/build_seed_data.py` after this change.

---

### 6. `cli.py` and `app.py` crash with a raw traceback if you forget to build the seed data first

**File:** `cli.py`, `app.py`

I reproduced this by temporarily removing `data/seed/graph.json` and running `python cli.py`. It fails at import time, before `main()`'s try/except block ever runs, with a full Python traceback ending in `FileNotFoundError`. Reason: `agent/tools.py` builds its `GraphStore` at module import time (`_store = GraphStore()`), and `cli.py` imports `agent.orchestrator` (which imports `agent.tools`) at the top of the file, so the crash happens before any of `cli.py`'s own error handling exists. This is exactly the kind of raw traceback the blueprint's own security section says a user should never see, and it is a likely first-run mistake for anyone who clones the repo and runs `python cli.py` before reading the setup steps.

**Fix, in `cli.py`:** check for the file before importing the agent, and print a clear instruction instead of importing something that will fail.

```python
"""
PharmaGraph CLI demo. Type a question, see the graph lookups the agent
made, and get a cited, confidence-scored answer.

Not medical advice. Portfolio and demo project only.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GRAPH_PATH = Path(__file__).parent / "data" / "seed" / "graph.json"
if not GRAPH_PATH.exists():
    print("No seed data found. Run this first, then try again:\n\n  python scripts/build_seed_data.py\n")
    sys.exit(1)

from agent.orchestrator import ask  # noqa: E402
from agent.tools import example_question  # noqa: E402
```

**Fix, in `app.py`:** Streamlit reruns the whole script on every interaction, so `sys.exit` is the wrong tool there; use `st.error` and `st.stop` instead, before the `agent.orchestrator` import:

```python
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
```

---

### 7. The agent's tool-calling loop has no iteration cap

**File:** `agent/orchestrator.py`, the `client.beta.messages.tool_runner(...)` call in `ask()`

There is no `max_iterations` set on the tool runner. This project's tools are simple lookups that should resolve in a handful of calls; without a cap, a confused or unusually thorough model response could keep calling tools longer, and more expensively, than this task needs.

**Fix:** add an explicit cap:

```python
runner = client.beta.messages.tool_runner(
    model=MODEL,
    max_tokens=2048,
    system=AGENT_SYSTEM_PROMPT,
    tools=tools,
    messages=[{"role": "user", "content": question}],
    max_iterations=6,
)
```

---

### 8. `GraphStore.get_evidence()` is never called

**File:** `graph/store.py`

`get_evidence(self, node_id)` is a working method, but nothing in `agent/tools.py` calls it, so it is dead code right now. Either wire it up as a fifth tool (for a "show me the exact source for this drug" style question) or delete it so the file only has what is actually used. Not urgent, just pick one; leaving unused public methods around is the kind of thing that looks like an unfinished feature in a portfolio review.

---

## Not a bug, action needed from you

### 9. I could not verify the live agent call end to end

Your local `.env` has `ANTHROPIC_API_KEY=` present but empty (I checked the length programmatically without printing the value; it is 0 characters). Because of that, I could not exercise the actual Phase A tool-calling round trip or the Phase B structured-output call against the real Anthropic API.

What I did verify directly, without needing a key:
- The graph builds correctly from real openFDA data (once findings 2 and 3 above are applied, it will be cleaner).
- `GraphStore`'s query methods (`find_drug`, `get_interactions`, `get_conditions_treated`, `check_interaction`) all run correctly against the real generated graph and return correct, well-formed results, including a real, working citation URL (I confirmed one by fetching it directly).
- The `@beta_tool`-wrapped functions in `agent/tools.py` build correct, valid JSON schemas from their type hints and docstrings.

What is still unverified: whether Claude's actual tool-use loop and the structured-output synthesis call behave the way `agent/orchestrator.py` expects (right tool choices, valid JSON matching `FINAL_ANSWER_SCHEMA`, sensible confidence levels). Put a real key in `.env`, then run:

```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from agent.orchestrator import ask
r = ask('Can <two real drug names from your rebuilt graph> be co-prescribed?')
print(r['answer'])
print(r['confidence'], '-', r['confidence_reason'])
print(r['trace'])
"
```

and confirm you get a sensible answer, a plausible confidence level, and at least one tool call in the trace, before considering the agent phase done.

---

## How to check your fixes

After applying the fixes above, in order:

1. Rerun the seed data build: `python scripts/build_seed_data.py`. Check the printed unique drug count is comfortably above 150.
2. Check the drug list looks like real medications, not cosmetics or homeopathic remedies:
   ```bash
   python -c "
   import json
   d = json.load(open('data/seed/graph.json'))
   names = sorted(n['generic_name'] for n in d['nodes'] if n['type'] == 'Drug')
   print(len(names), 'unique drugs')
   print(names[:20])
   "
   ```
3. Check class names no longer end in `[EPC]`:
   ```bash
   python -c "
   import json
   d = json.load(open('data/seed/graph.json'))
   print([n['name'] for n in d['nodes'] if n['type'] == 'DrugClass'][:10])
   "
   ```
4. Run `python tests/test_graph_smoke.py` directly (not with `-m`) and confirm it prints "all checks passed."
5. Temporarily rename `data/seed/graph.json`, run `python cli.py`, confirm you see the friendly "run the build script first" message and not a traceback, then rename the file back.
6. With a real API key in `.env`, run `python cli.py`, confirm the printed example question actually works, then try one or two of your own questions.
