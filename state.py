from typing_extensions import TypedDict, Annotated, List, Optional
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages:                 Annotated[List[AnyMessage], add_messages]
    analyzer_messages:        List[AnyMessage]  
    executer_messages:        List[AnyMessage]
    analyzer_report:          str
    original_analyzer_report: str
    original_code:            str
    refactored_code:          str
    comparator_report:        str
    refactor_iterations:      int
    execution_result:         str
    refactor_syntax_error:    Optional[str]