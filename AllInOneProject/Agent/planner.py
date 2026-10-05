import json
from typing import Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from AllInOneProject.Agent.base_node import AgentNode
from AllInOneProject.Model.state import MultiState, ExecutionPlan
from AllInOneProject.Model.worker_config import get_disabled_workers

class PlannerNode(AgentNode):
    def __init__(self, node_id: str, llm: ChatGoogleGenerativeAI, worker_map: Dict[str, str]):
        self.worker_map = worker_map
        self.worker_map_str = json.dumps(worker_map, indent=2, ensure_ascii=False)
        super().__init__(node_id, llm=llm)

    def build_runner(self):
        return self.llm.with_structured_output(ExecutionPlan)

    def _get_local_instructions(self) -> str:
        disabled = get_disabled_workers()
        active_map = {k: v for k, v in self.worker_map.items() if k not in disabled}
        active_map_str = json.dumps(active_map, indent=2, ensure_ascii=False)
        valid_ids = list(active_map.keys())
        return f'''
        你是任務規劃者，負責將問題分派給最適合的專家。

        ### 可用本地專家（優先使用）
        {active_map_str}

        ### 合法 Worker ID（含 internet_search）
        {json.dumps(valid_ids + ["internet_search"], ensure_ascii=False)}

        ### 選擇規則（依序優先）
        1. **優先選本地專家**：若問題與任一專家的描述相關，必須選該專家。
        2. **internet_search 是最後手段**：只有以下情況才使用：
           - 問題明確需要即時資訊（今日新聞、當前股價、最新事件）
           - 所有本地專家的描述都與問題完全無關
        3. worker_id 必須完全匹配上述合法 ID 之一。
        4. query 須為完整句子，清楚描述要查詢的內容。
        '''

    def _get_context_instructions(self, state: MultiState) -> str:
        last_question = (state.get("variables", {}) or {}).get("last_question", "")
        if not last_question:
            return ""
        return (
            f"使用者本輪的完整需求（已由需求澄清節點彙整）：\n{last_question}\n\n"
            "請以此為本輪唯一的分派依據；下方訊息歷史僅供背景參考，"
            "不要把歷史中已處理過的舊問題誤判為本輪需求。"
        )

    def execute(self, state: MultiState) -> Dict[str, Any]:
        print(f"\n--- [Planner] 開始規劃 ---")
        variables = state.get("variables", {})
        history_msgs = state.get("messages", [])

        system_text = self._build_system_prompt(state)
        msgs = [SystemMessage(content=system_text)] + history_msgs

        plan = self._safe_invoke(msgs)

        if isinstance(plan, AIMessage) and "LLMError" in plan.content:
            return {"variables": {"tasks_to_execute": []}}

        try:
            tasks_data = []
            disabled = get_disabled_workers()
            valid_worker_ids = {k for k in self.worker_map.keys() if k not in disabled}
            valid_worker_ids.add("internet_search")

            for task in plan.tasks:
                original_id = task.worker_id.strip()
                final_id = original_id

                if original_id not in valid_worker_ids:
                    potential_id = f"worker_{original_id}"
                    if potential_id in valid_worker_ids:
                        print(f"⚠️ [Planner] 自動修正 ID: {original_id} -> {potential_id}")
                        final_id = potential_id
                    else:
                        print(f"❌ [Planner] 無效 ID: {original_id} -> internet_search")
                        final_id = "internet_search"

                task_dict = task.model_dump()
                task_dict["worker_id"] = final_id
                tasks_data.append(task_dict)

            print(f"📋 [Planner] 任務: {[t['worker_id'] for t in tasks_data]}")
            return {
                "variables": {
                    "tasks_to_execute": tasks_data,
                    "plan_summary": plan.summary
                }
            }
        except Exception as e:
            print(f"❌ Planner Error: {e}")
            return {"variables": {"tasks_to_execute": []}}
