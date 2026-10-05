import textwrap
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt
from AllInOneProject.Agent.base_node import AgentNode
from AllInOneProject.Model.state import MultiState

class HumanRequirementNode(AgentNode):
    def __init__(self, node_id: str, llm: ChatGoogleGenerativeAI):
        super().__init__(node_id, llm=llm)

    def _get_global_instructions(self) -> str:
        return ""

    def _decision(self, state: MultiState, current_input: str) -> dict:
        history_msgs = [m for m in state.get("messages", []) if not isinstance(m, SystemMessage)]
        history_text = "\n".join([f"{m.type}: {m.content}" for m in history_msgs])

        prompt = textwrap.dedent(
            f'''
            你是需求澄清與彙整專家。
            任務：閱讀歷史與最新輸入，判斷需求是否完整。

            【對話歷史】
            {history_text}

            【最新輸入】
            human: {current_input}

            【判斷規則】
            1. 若需求模糊，route="clarify"。
            2. 若需求明確，route="ok"。
            3. 🔥 若 route="ok"，請在 "summary" 填入合併後的「完整單一指令」。

            【輸出 JSON】
            {{ "route": "ok" | "clarify", "question": "...", "summary": "..." }}
            '''
        ).strip()
        return self._invoke_and_parse_json([HumanMessage(content=prompt)])

    def execute(self, state: MultiState) -> dict:
        variables = dict(state.get("variables", {}) or {})

        msgs = state.get("messages", [])
        last_human = next((m for m in reversed(msgs) if isinstance(m, HumanMessage)), None)
        user_text = last_human.content if last_human else ""

        variables["tasks_to_execute"] = []
        variables["plan_summary"] = ""

        decision = self._decision(state, user_text)
        route = decision.get("route", "ok")

        if route == "clarify":
            question = decision.get("question") or "請補充資訊"
            clarification = interrupt({"question": question})

            # 執行到這裡代表 LangGraph 已 resume，clarification 是使用者的補充回覆
            combined_input = f"{user_text} (補充: {clarification})"
            variables["last_question"] = combined_input
            print(f"✅ [Requirement] 需求澄清後確認: {combined_input}")
            sys_msg = SystemMessage(content=f"【已確認的使用者需求】\n{combined_input}")
            return {
                "messages": [sys_msg],
                "variables": variables,
                "worker_results": "RESET"
            }
        else:
            final_goal = decision.get("summary") or user_text
            variables["last_question"] = final_goal
            print(f"✅ [Requirement] 需求確認: {final_goal}")
            sys_msg = SystemMessage(content=f"【已確認的使用者需求】\n{final_goal}")
            return {
                "messages": [sys_msg],
                "variables": variables,
                "worker_results": "RESET"
            }
