import os
from helpers.config import get_settings, Settings
from langchain.messages import AIMessage

settings = get_settings()

os.environ["OPENROUTER_API_KEY"] = settings.OPENROUTER_API_KEY
os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
os.environ['LANGCHAIN_TRACING_V2'] = settings.LANGCHAIN_TRACING_V2
os.environ['LANGCHAIN_ENDPOINT'] = settings.LANGCHAIN_ENDPOINT
os.environ['LANGCHAIN_PROJECT'] = settings.LANGCHAIN_PROJECT

from app.graph import build_graph


def print_final_ai_message(stream):
    final_message = None
    for state in stream:
        messages = state.get("messages", [])
        if messages:
            final_message = messages[-1]
    if final_message:
        final_message.pretty_print()


def main():
    app = build_graph()

    with open("code_to_analyze.py", "r", encoding="utf-8") as f:
        code = f.read()

    inputs = {
        "messages": [("user", code)],
        "original_code": code,
        "refactor_iterations": 0,
        "analyzer_report": "",
        "refactored_code": "",
        "validator_report": ""
    }

    outputs = app.stream(inputs, stream_mode="values")
    print_final_ai_message(outputs)


if __name__ == "__main__":
    main()
