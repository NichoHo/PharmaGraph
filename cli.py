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
    suggestion = example_question()
    if suggestion:
        print(f'\nTry: "{suggestion}"')
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
