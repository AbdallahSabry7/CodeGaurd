from typing_extensions import TypedDict, Annotated, List, Optional
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages:                 Annotated[List[AnyMessage], add_messages]
    analyzer_report:          str
    original_analyzer_report: str
    original_code:            str
    original_code_converted:   str
    translator_code:          Optional[str]
    refactored_code:          str
    refactor_iterations:      int
    execution_result:         str
    refactor_syntax_error:    Optional[str]
    translator_syntax_error:  Optional[str]
    source_language:          str
    destination_language:     str
    language:                 Optional[str]
    architect_report:         Optional[dict]
    refactor_directives:      Optional[list[dict]]
    architect_verdict:        Optional[str]
    architect_baseline_report: Optional[dict]
    architect_rejected:        Optional[list[dict]]
    syntax_iterations:         int
    quality_scores:             list[float]
    golden_master: Optional[str]        
    behavior_diff: Optional[str]        
    equivalence_report: Optional[str]