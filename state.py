from typing_extensions import TypedDict, Annotated, List
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
class AgentState(TypedDict):
    messages:                 Annotated[List[AnyMessage], add_messages]
    validator_messages:       List[AnyMessage]
    analyzer_messages:        List[AnyMessage]
    analyzer_report:          str
    original_analyzer_report: str
    original_code:            str
    refactored_code:          str
    validator_report:         str
    refactor_iterations:      int
