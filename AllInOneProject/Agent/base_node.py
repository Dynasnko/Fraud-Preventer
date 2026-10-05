import traceback
import json
import re
from typing import Any, Dict, List, Optional
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.errors import GraphInterrupt
from AllInOneProject.Model.state import MultiState

class BaseNode:
    def __init__(self, node_id: str):
        self.id = node_id
    def execute(self, state: MultiState) -> Dict[str, Any]:
        raise NotImplementedError

class AgentNode(BaseNode):
    BASE_SYSTEM_PROMPT = (
        "【系統核心指令】\n"
        "1. 你是專業的 AI 協作系統的一部分。\n"
        "2. 請一律使用繁體中文回答。\n"
        "3. 思考時請一步一步來 (Think step by step)。\n"
        "------"
    )

    def __init__(self, node_id: str, llm: Any, prompt: Optional[str] = None):
        super().__init__(node_id)
        self.llm = llm
        self.node_prompt = prompt or ""
        self.runner = self.build_runner()

    def build_runner(self):
        return self.llm

    def _get_global_instructions(self) -> str:
        return self.BASE_SYSTEM_PROMPT

    def _get_local_instructions(self) -> str:
        return self.node_prompt

    def _get_context_instructions(self, state: MultiState) -> str:
        return ""

    def _build_system_prompt(self, state: MultiState = None) -> str:
        parts = []
        if self._get_global_instructions():
            parts.append(self._get_global_instructions())
        if state:
            ctx = self._get_context_instructions(state)
            if ctx: parts.append(f"【當前上下文資訊】\n{ctx}")
        if self._get_local_instructions():
            parts.append(f"【當前任務指令】\n{self._get_local_instructions()}")
        return "\n\n".join(parts)

    def _safe_invoke(self, payload: Any) -> Any:
        try:
            return self.runner.invoke(payload)
        except GraphInterrupt:
            raise
        except Exception as e:
            traceback.print_exc()
            return AIMessage(content=f"LLMError: {type(e).__name__}: {e}")

    def _invoke_and_parse_json(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        payload = messages
        result = self._safe_invoke(payload)
        content = result.content if isinstance(result, AIMessage) else str(result)
        try:
            m = re.search(r"\{.*\}", content, flags=re.S)
            return json.loads(m.group(0) if m else content)
        except Exception as e:
            print(f"⚠️ [Node:{self.id}] JSON 解析失敗: {e} | 原始回應: {content[:120]}")
            return {}
