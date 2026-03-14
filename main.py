import os
from dotenv import load_dotenv
from langchain.messages import AIMessage

load_dotenv()

os.environ["OPENROUTER_API_KEY"] = os.getenv("OPENROUTER_API_KEY")
os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY")
os.environ['LANGCHAIN_TRACING_V2'] = 'true'
os.environ['LANGCHAIN_ENDPOINT'] = 'https://api.smith.langchain.com'
os.environ['LANGCHAIN_PROJECT'] = 'learning-langchain'

from graph import build_graph


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
