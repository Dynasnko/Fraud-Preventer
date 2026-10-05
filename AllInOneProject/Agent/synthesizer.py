import json
from typing import Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from AllInOneProject.Agent.base_node import AgentNode
from AllInOneProject.Model.state import MultiState

class SynthesizerNode(AgentNode):
    def __init__(self, node_id: str, llm: ChatGoogleGenerativeAI):
        super().__init__(node_id, llm=llm)

    def _get_local_instructions(self) -> str:
        return """
        你是智慧整合助手。
        任務：根據多位專家的報告，回答使用者的原始問題。

        【注意事項】
        1. 專家的報告包含「信心分數」，請優先採納高分專家的資訊。
        2. 若專家表示查無資料 (信心分數低)，請誠實告知使用者。
        3. 回答時請標註資訊來源 (例如：「根據防詐騙專家的資料...」或「根據OO網頁搜尋的資料...」或「根據{Worker_id}提供的資料...」)若Worker_id為internet_search請標記為根據網頁搜尋資料，同時須標註源自www.example.com或Google等。
        4. 請保持語氣專業、客觀。
        """

    def _get_context_instructions(self, state: MultiState) -> str:
        results = state.get("worker_results", [])
        variables = state.get("variables", {})
        plan_summary = variables.get("plan_summary", "")
        original_query = variables.get("last_question", "")

        context = f"【使用者原始問題】：{original_query}\n"
        context += f"【規劃策略】：{plan_summary}\n\n"

        context += "【各專家回報】：\n"

        if not results:
            context += "(無任何專家報告)"
        else:
            for i, res in enumerate(results, 1):
                wid = res.get("worker_id", "Unknown")
                query = res.get("query", "Unknown Query")
                content = res.get("content") or res.get("result") or "(無內容)"
                confidence = res.get("confidence_score", 0.0)
                sources = res.get("sources", [])
                thought = res.get("thought_process", "")

                source_str = ""
                if sources:
                    if isinstance(sources, list):
                        source_list = []
                        for s in sources:
                            if isinstance(s, dict):
                                title = s.get('title', 'Doc')
                                url = s.get('url', '')
                                source_list.append(f"- {title} ({url})")
                            else:
                                source_list.append(f"- {str(s)}")
                        source_str = "\n".join(source_list[:3])
                    else:
                        source_str = str(sources)

                context += f"--- 報告 #{i} (專家: {wid}) ---\n"
                context += f"針對問題: {query}\n"
                context += f"信心分數: {confidence:.2f}\n"
                context += f"思考過程: {thought}\n"
                context += f"回答內容: {content}\n"
                if source_str:
                    context += f"主要來源:\n{source_str}\n"
                context += "\n"

        return context

    def execute(self, state: MultiState) -> Dict[str, Any]:
        print(f"\n--- [Synthesizer] 整合報告中 ---")

        sys_prompt = self._build_system_prompt(state)
        original_query = state.get("variables", {}).get("last_question", "請整合上述資訊並回答。")

        msgs = [
            SystemMessage(content=sys_prompt),
            HumanMessage(content=f"請根據上述專家報告，回答我的問題：{original_query}")
        ]

        response = self._safe_invoke(msgs)
        return {"messages": [response]}
