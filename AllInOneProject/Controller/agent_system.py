# agent_system.py
import inspect
import json
import uuid
import traceback
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

# 引用核心邏輯
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.types import Command
from AllInOneProject.Agent.graph import build_chat_flow
from AllInOneProject.Agent.tools.tools import build_date_hint

# --- 1. 定義標準化的「輸出格式」 (The Protocol) ---
# 無論是網頁、APP、還是 API，拿到的永遠是這個結構
class AgentResponse(BaseModel):
    response_text: str = Field(..., description="AI 的最終回答或追問問題")
    thread_id: str = Field(..., description="對話 Session ID")
    status: str = Field(..., description="狀態: 'completed' (完成) | 'interrupted' (等待使用者輸入) | 'error' (錯誤)")
    planner_thought: Optional[str] = Field(None, description="Planner 的規劃摘要 (可選)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="其他資訊 (如來源)")
    chart_images: List[str] = Field(default_factory=list, description="Worker 工具產生的圖表圖片（base64 data URI），不經過 LLM Synthesizer 改寫")

# --- 2. 定義「Agent 系統」 (The System) ---
_GROUNDING_TEXT = {"grounded": "有依據", "partial": "部分依據", "ungrounded": "無依據"}


class HolisticAgentSystem:
    _instance = None

    # 單例模式：確保系統啟動後，RAG 資料庫只會載入一次
    def __new__(cls):
        if cls._instance is None:
            print("⚙️ [System] 正在初始化整合型 Agent 核心...")
            cls._instance = super(HolisticAgentSystem, cls).__new__(cls)
            cls._instance.app = build_chat_flow()
            print("✅ [System] 核心就緒。")
        return cls._instance

    @classmethod
    def rebuild(cls) -> None:
        """重建 LangGraph（新增 Worker 後呼叫）。原子性替換 app，不中斷進行中的對話。"""
        print("🔄 [System] 重建 Agent 核心...")
        new_app = build_chat_flow()
        if cls._instance is None:
            cls._instance = super(HolisticAgentSystem, cls).__new__(cls)
        cls._instance.app = new_app
        print("✅ [System] 重建完成。")

    def process_request(
        self,
        user_input: str,
        thread_id: str = None,
        is_resume: bool = False,
        on_step=None,
        analysis_request: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """
        🔥 這是唯一的對外窗口。
        它封裝了所有 LangGraph 的複雜操作（Command, Snapshot, Interrupt）。
        on_step: 可選的 callback(step_type: str, detail: str)，用於即時回報中間狀態。
        """

        # on_step 可為 (step_type, detail) 或 (step_type, detail, data)；後者另外收到結構化資料
        try:
            _accepts_data = on_step is not None and len(inspect.signature(on_step).parameters) >= 3
        except (TypeError, ValueError):
            _accepts_data = False

        def _emit(step_type: str, detail: str, data: Optional[Dict[str, Any]] = None):
            """安全地呼叫 on_step callback。

            detail 慣例：第一行為標題，其餘各行為可展開的詳細內容（純文字接收端可直接顯示）。
            data：同一事件的結構化內容，供 Thinking Log 排版（僅傳給接受三個參數的 callback）。
            """
            if on_step:
                try:
                    if _accepts_data:
                        on_step(step_type, detail, data)
                    else:
                        on_step(step_type, detail)
                except Exception:
                    pass

        # A. 管理 Session ID
        if not thread_id:
            thread_id = str(uuid.uuid4())

        config = {"configurable": {"thread_id": thread_id}}

        # B. 智慧判斷 Payload (決定是「新對話」還是「回答追問」)
        # 如果外部標記 is_resume=True，代表這是在回答系統上一輪的問題
        if is_resume:
            print(f"🔄 [System] Resuming thread {thread_id}...")
            _emit("system", "繼續上一輪對話...")
            # 把使用者的補充加入 checkpoint messages，確保 requirement 重跑時
            # _decision() 能看到完整對話（原始問題 + 補充），產出正確 summary
            self.app.update_state(config, {"messages": [HumanMessage(content=user_input)]})
            payload = Command(resume=user_input)
        else:
            print(f"🚀 [System] New input for thread {thread_id}...")
            _emit("system", "收到新問題，開始分析...")
            date_hint = build_date_hint(user_input)
            payload = {
                "messages": [
                    SystemMessage(content=date_hint),
                    HumanMessage(content=user_input)
                ],
                # variables 在同一 thread 會跨輪保留，每個新問題都要明確覆寫（沒有就設 None）
                "variables": {"analysis_request": analysis_request},
            }

        # C. 執行與狀態捕捉
        response_data = {
            "response_text": "",
            "thread_id": thread_id,
            "status": "processing",
            "planner_thought": "",
            "chart_images": []
        }

        try:
            # 使用 stream 來即時捕捉中間產物 (Planner 的思考)
            events = self.app.stream(payload, config=config, stream_mode="updates")

            for event in events:
                # 1. 偵測中斷 (需要使用者補充資訊)
                if "__interrupt__" in event:
                    interrupt_value = event["__interrupt__"][0].value
                    response_data["response_text"] = interrupt_value.get("question", "請提供更多資訊")
                    response_data["status"] = "interrupted"
                    _emit("interrupt", f"系統需要更多資訊：{response_data['response_text']}")
                    return AgentResponse(**response_data)

                # 2. 捕捉各節點的產出，並即時回呼
                for node_name, updates in event.items():

                    # ── requirement 節點 ──
                    if node_name == "requirement":
                        _emit("requirement", "需求分析完成，準備規劃任務...")

                    # ── planner 節點：抓規劃摘要 + 分派的專家清單 ──
                    if node_name == "planner":
                        variables = updates.get("variables", {})
                        plan = variables.get("plan_summary", "")
                        tasks = variables.get("tasks_to_execute", [])
                        if plan:
                            response_data["planner_thought"] = plan
                            _emit("planner", f"規劃完成\n{plan}")
                        if tasks:
                            expert_list = "、".join(
                                t["worker_id"].replace("worker_", "") for t in tasks
                            )
                            _emit("planner_dispatch", f"分派 {len(tasks)} 位專家：{expert_list}")
                            for t in tasks:
                                wid = t["worker_id"].replace("worker_", "")
                                _emit("planner_task", f"{wid} 的任務\n{t.get('query', '')}")

                    # ── worker 節點：捕捉每個專家的執行結果 ──
                    # stream_mode="updates" 在節點「完成後」才送出，因此這裡只回報完成與執行紀錄
                    if node_name.startswith("worker_") or node_name == "internet_search":
                        display_name = node_name.replace("worker_", "")
                        results = updates.get("worker_results", [])
                        for r in results:
                            score = r.get("confidence_score", 0)
                            elapsed = r.get("elapsed_sec")
                            thought = r.get("thought_process", "")
                            sources = r.get("sources", [])
                            charts = r.get("chart_images", [])
                            trace = r.get("trace") or {}
                            took = f"・{elapsed:.1f} 秒" if elapsed is not None else ""
                            g = r.get("grounding") or {}
                            level_text = _GROUNDING_TEXT.get(g.get("level"), "依據未知")
                            claim_lines = [
                                f"・{c.get('text', '')} [{', '.join(c.get('source_ids', [])) or '無引用'}]"
                                for c in g.get("claims", [])
                            ]
                            _emit("worker_done",
                                  f"{display_name} 完成・{level_text}{took}\n"
                                  f"{g.get('reason', '')}（模型自評 {score:.0%}）"
                                  + ("\n" + "\n".join(claim_lines) if claim_lines else ""),
                                  {"name": display_name, "elapsed": elapsed, "llm_score": score,
                                   "grounding": g})

                            # 系統實際執行紀錄（非 LLM 自述）：工具 → 知識庫 → 網路
                            for tc in trace.get("tools", []):
                                status = "" if tc.get("ok") else "・失敗"
                                args = json.dumps(tc.get("args", {}), ensure_ascii=False)
                                _emit("worker_tool",
                                      f"{tc.get('id', '')} 工具 {tc.get('name')}・{tc.get('sec', 0):.1f} 秒{status}\n"
                                      f"參數：{args}\n結果：{tc.get('result', '')}",
                                      tc)
                            rag = trace.get("rag")
                            if rag:
                                used = rag.get("used", [])
                                lines = [f"{d.get('id', '')} [{d['relevance']:.2f}] {d['source']}" for d in used]
                                _emit("worker_rag",
                                      f"知識庫檢索：採用 {len(used)}/{rag.get('candidates', 0)} 筆"
                                      f"・最佳關聯度 {rag.get('best', 0):.2f}"
                                      + ("\n" + "\n".join(lines) if lines else ""),
                                      rag)
                            for w in trace.get("web", []):
                                kind = "法條驗證搜尋" if w.get("kind") == "verify" else "網路搜尋"
                                lines = [f"{it.get('id', '')} {it.get('title', '')}\n  {it.get('url', '')}"
                                         for it in w.get("results", [])]
                                _emit("worker_web",
                                      f"{kind}：{len(w.get('results', []))} 筆・{w.get('sec', 0):.1f} 秒\n"
                                      f"查詢：{w.get('query', '')}"
                                      + ("\n" + "\n".join(lines) if lines else ""),
                                      w)

                            if thought:
                                _emit("worker_thought", f"推論過程\n{thought}")
                            if sources:
                                # LLM 在回答中自述引用的來源（完整保留，不截斷）
                                lines = [
                                    f"{s.get('title', '')}\n  {s.get('url', '')}" for s in sources
                                ]
                                _emit("worker_sources", f"回答引用 {len(sources)} 個來源\n" + "\n".join(lines))
                            if charts:
                                response_data["chart_images"].extend(charts)
                                _emit("worker_chart", f"產生了 {len(charts)} 張圖表")

                    # ── composer 節點：品質評估 ──
                    if node_name == "composer":
                        variables = updates.get("variables", {})
                        decision = variables.get("composer_decision", "")
                        reasoning = variables.get("composer_reasoning", "")
                        if decision == "retry":
                            # 比照 LangGraph 端 worker_results 的 "RESET" 語意：重試會讓被精煉的
                            # Worker 重新執行並可能重新產圖，先清空已收集的圖表避免重複顯示舊圖。
                            response_data["chart_images"] = []
                            retry_tasks = variables.get("tasks_to_execute", [])
                            retry_names = ", ".join(
                                t["worker_id"].replace("worker_", "") for t in retry_tasks
                            )
                            _emit("composer", f"品質不足，重新執行：{retry_names}"
                                  + (f"\n{reasoning}" if reasoning else ""))
                        elif decision == "pass":
                            _emit("composer", f"品質評估通過")

                    # ── synthesizer 節點：最終回答 ──
                    if node_name == "synthesizer":
                        _emit("synthesizer", "正在整合所有專家意見，撰寫最終回答...")

                    # 抓 Synthesizer 的最終回答
                    if "messages" in updates:
                        msgs = updates["messages"]
                        if msgs and isinstance(msgs[-1], AIMessage):
                            response_data["response_text"] = msgs[-1].content

            # 迴圈正常結束，代表任務完成
            response_data["status"] = "completed"
            _emit("done", "回答完成 ✓")

        except Exception as e:
            traceback.print_exc()
            response_data["status"] = "error"
            response_data["response_text"] = f"系統內部發生錯誤: {str(e)}"
            _emit("error", f"發生錯誤：{str(e)}")

        return AgentResponse(**response_data)
