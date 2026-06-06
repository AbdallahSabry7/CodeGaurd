import os
import sys
import argparse

from helpers.config import get_settings

settings = get_settings()

# Wire up LangSmith tracing from settings before importing the graph
os.environ["OPENROUTER_API_KEY"] = settings.OPENROUTER_API_KEY
os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT

from graph import build_graph


def _read_source(args) -> str:
    if args.stdin:
        return sys.stdin.read()
    with open(args.file, "r", encoding="utf-8") as f:
        return f.read()


def print_final_ai_message(stream):
    final_message = None
    for state in stream:
        messages = state.get("messages", [])
        if messages:
            final_message = messages[-1]
    if final_message:
        final_message.pretty_print()


def main():
    parser = argparse.ArgumentParser(
        prog="codeguard",
        description="Analyze and automatically refactor Python (or Java/C++) code.",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", "-f", help="Path to a source file to analyze.")
    src.add_argument("--stdin", action="store_true", help="Read source code from stdin.")
    args = parser.parse_args()

    code = _read_source(args)
    if not code.strip():
        raise SystemExit("No code provided.")

    app = build_graph()
    inputs = {
        "messages": [("user", code)],
        "original_code": code,
        "refactor_iterations": 0,
    }
    outputs = app.stream(inputs, stream_mode="values")
    print_final_ai_message(outputs)


if __name__ == "__main__":
    main()