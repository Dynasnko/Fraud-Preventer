from typing import Any, Dict, List, Union, Annotated, TypedDict
import operator
from pydantic import BaseModel, Field
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage

def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    return {**left, **right}

def reduce_results(existing: List, new: Union[List, str]) -> List:
    if new == "RESET":
        return []
    if isinstance(new, list):
        return existing + new
    return existing

class MultiState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    variables: Annotated[Dict[str, Any], merge_dicts]
    worker_results: Annotated[List[Dict[str, Any]], reduce_results]

class SubTask(BaseModel):
    worker_id: str = Field(..., description="負責此任務的 Worker ID")
    query: str = Field(..., description="具體查詢指令")
    reasoning: str = Field(..., description="分派理由")

class ExecutionPlan(BaseModel):
    tasks: List[SubTask]
    summary: str
