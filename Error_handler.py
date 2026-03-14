import os
from dotenv import load_dotenv
from serpapi import GoogleSearch 
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.messages import AnyMessage , SystemMessage , HumanMessage, ToolMessage
from typing_extensions import TypedDict, Annotated
import operator
from typing import Literal
from langgraph.graph import StateGraph, START, END
from IPython.display import Image, display

load_dotenv()

os.environ["LANGSMITH_API_KEY"] = os.getenv("LANGSMITH_API_KEY")
os.environ['LANGCHAIN_TRACING_V2'] = 'true'
os.environ['LANGCHAIN_ENDPOINT'] = 'https://api.smith.langchain.com'
os.environ['LANGCHAIN_PROJECT'] = 'learning-langchain'

@tool
def web_search(query: str) -> str:
    """Search the web for information using Google Search."""
    params = {
        "engine": "google",
        "q": query,
        "api_key": os.getenv("SERPAPI_API_KEY"),
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    organic_results = results.get("organic_results", [])

    output = ""
    for r in organic_results[:3]:
        output += f"Title: {r.get('title','')}\nSnippet: {r.get('snippet','')}\n\n"
    return output

llm = ChatGroq(
    model_name="llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
)

tools = [web_search]
tools_by_name = {tool.name: tool for tool in tools}
model_with_tools = llm.bind_tools(tools)

class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int

def llm_call(state: dict):
    """LLM decides whether to call a tool or not"""

    return {
        "messages": [
            model_with_tools.invoke(
                [
                    SystemMessage(
                        content="""You are a senior software debugging agent.
                                    Goal: Identify root cause of errors and provide precise fixes.

                                    Process:
                                    1. Analyze the error message carefully.
                                    2. Identify language, library, and likely cause.
                                    3. If uncertain or version-dependent → use web search tool.
                                    4. Provide structured output:
                                    - Root Cause
                                    - Exact Fix
                                    - Corrected Code (if needed)
                                    - Why it happened (brief)

                                    Rules:
                                    - Do not guess.
                                    - Use search tool for library/framework/version issues.
                                    - Be concise and technical.
                                    - No unnecessary explanations.
                                    - If solution fails, reanalyze and try a different fix."""
                    )
                ]
                + state["messages"]
            )
        ],
        "llm_calls": state.get('llm_calls', 0) + 1
    }

def tool_node(state: dict):
    """Performs the tool call"""

    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
    return {"messages": result}


def should_continue(state: MessagesState) -> Literal["tool_node", END]:
    """Decide if we should continue the loop or stop based upon whether the LLM made a tool call"""

    messages = state["messages"]
    last_message = messages[-1]

    if last_message.tool_calls:
        return "tool_node"

    return END

# Build workflow
agent_builder = StateGraph(MessagesState)

agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("tool_node", tool_node)

agent_builder.add_edge(START, "llm_call")
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
    ["tool_node", END]
)
agent_builder.add_edge("tool_node", "llm_call")

agent = agent_builder.compile()

display(Image(agent.get_graph(xray=True).draw_mermaid_png()))

# Invoke
messages = [HumanMessage(content="""
Python circular import.
a.py:
from b import func_b
def func_a():
    return "A"

b.py:
from a import func_a
def func_b():
    return func_a()

Error:
ImportError: cannot import name 'func_a' from partially initialized module 'a'
""")]
messages = agent.invoke({"messages": messages})
final_output = messages["messages"][-1]
print(final_output.content)