import json
import re
import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from AllInOneProject.Agent.base_node import AgentNode
from AllInOneProject.Model.config import RAG_THRESHOLD, RAG_STRONG, RAG_WEAK, RAG_MARGIN
from AllInOneProject.Model.state import MultiState
from AllInOneProject.Agent.tools.tools import web_search
from AllInOneProject.Agent.tools.data_analysis_tools import run_analysis_request

def _content_to_text(content: Any) -> str:
    """Gemini（ChatGoogleGenerativeAI）在混合 text + tool_call 回應時，
    content 可能是 list（如 [{"type": "text", "text": "..."}]）而非 str，
    直接 .strip() / 正規表示式比對會噴 'list' object has no attribute 'strip'。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(content) if content is not None else ""


LAW_WORKER_IDS = {
    "worker_刑法專家",
    "worker_民法專家",
    "worker_防詐條例專家",
    "worker_洗錢防制專家",
    "worker_刑事訴訟專家",
}

def _brief_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """印 log / Thinking Log 用：data_text 動輒上萬字，只留開頭。"""
    out = dict(args)
    dt = out.get("data_text")
    if isinstance(dt, str) and len(dt) > 120:
        out["data_text"] = f"{dt[:80]}…（共 {len(dt)} 字）"
    return out


def _tool_result_entry(tid: str, name: str, result: Any, chart_sink: List[str]):
    """把工具結果整理成 context 條目。回傳 (條目, 回給 LLM 的文字, 是否成功)。

    generate_chart 的 base64 絕不塞進 LLM context（太長也無助於推論），
    只留精簡摘要給 LLM，實際圖片走 chart_sink 側路直達前端。
    """
    if name != "generate_chart":
        text = str(result)
        return f"【{tid}｜工具 {name} 查詢結果】\n{text}", text, True
    text, ok = str(result), False
    try:
        parsed = json.loads(result)
        text = parsed.get("summary", "圖表已生成")
        if parsed.get("chart_base64"):
            chart_sink.append(parsed["chart_base64"])
            ok = True
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    return f"【{tid}｜工具 {name} 執行結果】\n{text}", text, ok


# ==========================================
# 1. 定義標準化的輸出格式 (Schema)
# ==========================================

class Reference(BaseModel):
    title: str = Field(..., description="來源標題、檔案名稱或網頁標題")
    url: str = Field(..., description="網址(URL)或本地檔案路徑(Local Path)")
    snippet: Optional[str] = Field(None, description="引用的關鍵原文片段")

class Claim(BaseModel):
    text: str = Field(..., description="回答中的一個重點（一句話）")
    source_ids: List[str] = Field(default_factory=list, description="支持此重點的參考資料編號，例如 S1、W2、T1；沒有任何參考資料支持則留空，不可捏造編號")

class WorkerOutput(BaseModel):
    worker_id: str = Field(..., description="負責此任務的專家 ID")
    content: str = Field(..., description="針對問題的完整回答內容")
    sources: List[Reference] = Field(default_factory=list, description="回答所依據的來源清單")
    confidence_score: float = Field(..., description="信心分數 (0.0 - 1.0)")
    thought_process: str = Field(..., description="簡述搜尋策略與推論過程")
    missing_info: Optional[str] = Field(None, description="查不到的資訊")
    claims: List[Claim] = Field(default_factory=list, description="將回答拆成數個重點，逐條標註支持它的參考資料編號")
    chart_images: List[str] = Field(default_factory=list, description="工具產生的圖表圖片（base64 data URI），不經過 LLM 改寫直接傳給前端")


# ==========================================
# 依據等級（grounding）：由系統檢查引用，而非 LLM 自評
# ==========================================
# 參考資料編號前綴 → 類型。本地知識庫與工具（查詢自有資料庫）視為本地依據；網路為外部依據。
_EVIDENCE_KINDS = {"S": "local", "T": "tool", "W": "web", "V": "verify"}
_LOCAL_KINDS = {"local", "tool"}
_CITATION_RULES = """
【引用規則】
- 參考資料每段開頭都有編號（S=本地知識庫、T=工具查詢結果、W=網路搜尋、V=法條驗證搜尋），例如【S1｜…】。
- 請在 claims 欄位把回答拆成數個重點，每個重點附上「確實支持它」的參考資料編號（可多個）。
- 由參考資料歸納、概括或轉述而來的句子（包含開頭的總結句），也要標註其依據的編號。
- 只有真正超出參考資料範圍的內容（例如常識或自行推論）才將 source_ids 留空；不可捏造或猜測編號。
- 參考資料不足以回答時，請在 missing_info 說明，而不是用未經支持的內容補齊。
"""


def select_rag_docs(docs_with_score: List[Any]) -> tuple:
    """相對門檻篩選 RAG 結果（依距離由小到大排序的 [(doc, dist)]）。

    回傳 (採用的 [(doc, dist)], mode)：
    - mode="local"：最佳距離 < RAG_STRONG，只用本地
    - mode="local+web"：最佳距離介於 STRONG～WEAK，本地片段仍採用，另外搜尋網路補充
      （舊做法在此區間會丟掉全部本地結果，實測正確片段常落在 0.70～0.80）
    - mode="web"：最佳距離 ≥ RAG_WEAK 或無結果，只用網路
    評測：python dev_scripts/rag_eval/eval_rag.py report
    """
    if not docs_with_score:
        return [], "web"
    best = docs_with_score[0][1]
    if best >= RAG_WEAK:
        return [], "web"
    cutoff = min(best + RAG_MARGIN, RAG_WEAK)
    used = [(d, s) for d, s in docs_with_score if s < cutoff]
    return used, ("local" if best < RAG_STRONG else "local+web")


def _normalize_id(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(raw)).upper()


def _present_evidence_ids(ctx: str) -> Dict[str, str]:
    """實際送進 LLM 的 context 中出現的參考資料編號 → 類型（被截斷掉的編號不算）。"""
    return {
        m.group(1) + m.group(2): _EVIDENCE_KINDS[m.group(1)]
        for m in re.finditer(r"【([SWTV])(\d+)｜", ctx)
    }


def assess_grounding(claims: List[Dict[str, Any]], evidence: Dict[str, str]) -> Dict[str, Any]:
    """依引用判定依據等級：grounded（有依據）/ partial（部分依據）/ ungrounded（無依據）。

    - 引用有效 = 編號確實出現在送給 LLM 的參考資料中。
    - grounded：≥80% 重點有有效引用，且 ≥80% 重點有本地（知識庫 / 工具）依據。
    - partial：≥50% 重點有有效引用（含僅網路依據）。
    - ungrounded：其餘，或未列出任何重點。
    """
    items, invalid = [], []
    for c in claims or []:
        ids = [_normalize_id(i) for i in (c.get("source_ids") or []) if _normalize_id(i)]
        valid = [i for i in ids if i in evidence]
        invalid += [i for i in ids if i not in evidence and i not in invalid]
        items.append({
            "text": c.get("text", ""),
            "source_ids": ids,
            "valid_ids": valid,
            "local": any(evidence[i] in _LOCAL_KINDS for i in valid),
        })
    total = len(items)
    cited = sum(1 for it in items if it["valid_ids"])
    local = sum(1 for it in items if it["local"])
    if total == 0:
        level, reason = "ungrounded", "未列出任何可驗證的重點"
    else:
        if cited / total >= 0.8 and local / total >= 0.8:
            level = "grounded"
        elif cited / total >= 0.5:
            level = "partial"
        else:
            level = "ungrounded"
        reason = f"{total} 個重點中 {cited} 個有有效引用（本地／工具 {local}、僅外部 {cited - local}）"
    if invalid:
        reason += f"；引用了不存在的編號：{'、'.join(invalid)}"
    return {"level": level, "reason": reason, "total": total, "cited": cited, "local": local,
            "invalid_ids": invalid, "claims": items}

# ==========================================
# 2. Worker Node 實作
# ==========================================

class WorkerNode(AgentNode):
    def __init__(self, node_id: str, llm: Any, db: Optional[Any] = None,
                 tools: Optional[List] = None, description: str = ""):
        # 先設好 Worker 專屬屬性，再呼叫父類別（父類別 __init__ 會呼叫 build_runner()）
        self.db = db
        self.tools = tools or []
        self.description = description
        self.RAG_THRESHOLD = RAG_THRESHOLD
        super().__init__(node_id, llm=llm)

    def _gather_tool_context(self, query: str, raw_user_text: str = "",
                             tool_trace: Optional[List[Dict[str, Any]]] = None,
                             chart_sink: Optional[List[str]] = None) -> str:
        """
        讓 LLM 自主決定是否呼叫工具（如 SQLite 統計查詢、資料分析與繪圖）。
        最多執行 3 輪工具呼叫，回傳所有結果組成的字串。
        使用父類別的 self.llm（由 graph.py 統一傳入）。
        修正：最後一輪 LLM 的自然語言摘要也納入結果。

        raw_user_text: 使用者最原始的訊息全文（未經 Planner 改寫）。Planner 產生的 query
        是 LLM 改寫過的描述性句子，使用者貼上的原始資料（如表格/CSV/JSON）很可能在改寫過程
        中遺失，因此工具呼叫需要額外參考這份原文才能組出正確的 data_text 參數。

        tool_trace / chart_sink: 若提供，分別附加工具呼叫紀錄（供 Thinking Log）與圖表 base64。
        用參數傳入而非存在 self，避免同一 Worker 被多個請求並行時互相覆蓋。
        """
        if not self.tools:
            return ""
        if chart_sink is None:
            chart_sink = []

        try:
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            current_year = datetime.now().year

            llm_with_tools = self.llm.bind_tools(self.tools)
            human_content = query
            if raw_user_text and raw_user_text.strip() != query.strip():
                human_content = (
                    f"任務指令：{query}\n\n"
                    f"【使用者原始訊息（可能包含完整資料，如表格/CSV/JSON，請以此為準）】\n{raw_user_text}"
                )
            messages: List = [
                SystemMessage(content=(
                    f"今天日期：{today}，當前年份：{current_year}。\n"
                    "當使用者說「今年」請用此年份，「去年」請減一，以此類推。\n"
                    "你是資料分析助手，可使用工具查詢防詐騙資料庫，或對使用者提供的資料做統計分析與繪圖。"
                    "若問題需要精確統計數字（如件數、金額加總、排行）或圖表，請主動呼叫工具。"
                    "若工具回傳格式錯誤訊息，請根據訊息內容重新整理資料格式後再呼叫一次。"
                    "若不需要，直接回覆空字串即可。"
                )),
                HumanMessage(content=human_content),
            ]

            results: List[str] = []
            tool_was_called = False
            last_response = None

            for _ in range(3):
                response = llm_with_tools.invoke(messages)
                messages.append(response)
                last_response = response

                if not response.tool_calls:
                    break

                tool_was_called = True
                for tc in response.tool_calls:
                    matched = next((t for t in self.tools if t.name == tc["name"]), None)
                    if not matched:
                        continue
                    t_call = time.perf_counter()
                    try:
                        print(f"   🔧 [Tool Call] {tc['name']} → args: {_brief_args(tc['args'])}")
                        result = matched.invoke(tc["args"])
                        tid = f"T{len(results) + 1}"
                        entry, text, ok = _tool_result_entry(tid, tc["name"], result, chart_sink)
                        results.append(entry)
                        messages.append(ToolMessage(content=text, tool_call_id=tc["id"]))
                        if tool_trace is not None:
                            tool_trace.append({
                                "id": tid, "name": tc["name"], "args": _brief_args(tc["args"]), "ok": ok,
                                "result": text[:500],
                                "sec": round(time.perf_counter() - t_call, 1),
                            })
                    except Exception as e:
                        messages.append(ToolMessage(content=f"工具呼叫失敗: {e}", tool_call_id=tc["id"]))
                        if tool_trace is not None:
                            tool_trace.append({
                                "name": tc["name"], "args": _brief_args(tc["args"]), "ok": False,
                                "result": str(e)[:500],
                                "sec": round(time.perf_counter() - t_call, 1),
                            })

            # 修正問題 4：最後一輪 LLM 的自然語言摘要優先放在結果最前面
            if tool_was_called and last_response and getattr(last_response, "content", ""):
                summary = _content_to_text(last_response.content).strip()
                if summary:
                    # 模型對工具結果的整理，不是原始資料，不給編號（引用請指向 T 編號）
                    results.insert(0, f"[工具結果摘要，僅供參考，引用請使用 T 編號]\n{summary}")

            return "\n\n".join(results)

        except Exception as e:
            print(f"⚠️ [Worker:{self.id}] 工具查詢階段失敗: {e}")
            return ""

    def _run_analysis_request(self, req: Dict[str, Any],
                              tool_trace: List[Dict[str, Any]], chart_sink: List[str]) -> str:
        """「數據分析請求」表單：統計項目與圖表是使用者明確指定的參數，直接照參數執行，
        不交給 LLM 決定要不要呼叫工具；LLM 只負責解讀結果、撰寫報告。"""
        results: List[str] = []
        for tool, args, result in run_analysis_request(req):
            t_call = time.perf_counter()
            tid = f"T{len(results) + 1}"
            print(f"   🔧 [Analysis] {tool.name} → args: {_brief_args(args)}")
            entry, text, ok = _tool_result_entry(tid, tool.name, result, chart_sink)
            results.append(entry)
            tool_trace.append({"id": tid, "name": tool.name, "args": _brief_args(args), "ok": ok,
                               "result": text[:500], "sec": round(time.perf_counter() - t_call, 1)})
        return "\n\n".join(results)

    def execute(self, state: MultiState) -> Dict[str, Any]:
        worker_id = self.id
        tasks = state.get("variables", {}).get("tasks_to_execute", [])

        my_task = next((t for t in tasks if t["worker_id"] == worker_id), None)
        if not my_task: return {}

        query = my_task["query"]
        print(f"⚙️ [Worker: {worker_id}] 執行: {query}")

        last_human = next((m for m in reversed(state.get("messages", [])) if isinstance(m, HumanMessage)), None)
        raw_user_text = last_human.content if last_human else ""

        context_text = ""
        used_source_type = "None"
        # 系統實際執行紀錄（非 LLM 自述），供 Thinking Log 追溯：工具呼叫、RAG 檢索到的文件、網路搜尋
        t_start = time.perf_counter()
        trace: Dict[str, Any] = {"tools": [], "rag": None, "web": []}

        try:
            # --- 步驟 A: 工具查詢優先（SQLite 統計等）---
            # 修正問題 2：Tool context 優先保留，RAG/Web 填剩餘空間
            charts: List[str] = []
            analysis_req = state.get("variables", {}).get("analysis_request")
            if analysis_req and any(t.name == "generate_chart" for t in self.tools):
                tool_context = self._run_analysis_request(analysis_req, trace["tools"], charts)
            else:
                tool_context = self._gather_tool_context(query, raw_user_text=raw_user_text,
                                                         tool_trace=trace["tools"], chart_sink=charts)
            if tool_context:
                used_source_type = "DB Query"

            # --- 步驟 B: 獲取 RAG / Web Context ---
            is_rag_good = False
            rag_web_parts: List[str] = []

            if self.db:
                db_size = self.db._collection.count()
                if db_size > 10000:
                    k = 15
                elif db_size > 1000:
                    k = 10
                else:
                    k = 5
                docs_with_score = self.db.similarity_search_with_score(query, k=k)
                if docs_with_score:
                    best_score = docs_with_score[0][1]
                    used_docs, rag_mode = select_rag_docs(docs_with_score)
                    print(f"   📊 RAG 篩選：k={k}，採用 {len(used_docs)}/{len(docs_with_score)} 篇，"
                          f"模式={rag_mode}（best={best_score:.3f}）")
                    trace["rag"] = {
                        "k": k,
                        "candidates": len(docs_with_score),
                        "best": round(1 - best_score, 2),
                        "mode": rag_mode,
                        "used": [
                            {"id": f"S{i}", "source": d.metadata.get("source", "unknown_source"), "relevance": round(1 - s, 2)}
                            for i, (d, s) in enumerate(used_docs, 1)
                        ],
                    }
                    for i, (d, score) in enumerate(used_docs, 1):
                        src = d.metadata.get('source', 'unknown_source')
                        rag_web_parts.append(
                            f"【S{i}｜本地知識庫｜{src}｜關聯度 {1-score:.2f}】\n{d.page_content}"
                        )
                    if used_docs:
                        is_rag_good = rag_mode == "local"
                        used_source_type = ("DB Query + Local Database" if tool_context else "Local Database")
                    if rag_mode != "local":
                        print(f"   ⚠️ 本地依據不足（模式={rag_mode}），準備上網...")

            # 本地依據不足（local+web / web）時搜尋網路；local+web 保留已採用的本地片段一起送給 LLM
            if not is_rag_good and not tool_context:
                used_source_type = ("Local Database + Internet Search"
                                    if used_source_type == "Local Database" else "Internet Search")
                print(f"   🌐 啟動網路搜尋...")
                t_web = time.perf_counter()
                web_result = web_search.invoke({"query": query})
                web_trace = {"kind": "fallback", "query": query, "results": [],
                             "sec": round(time.perf_counter() - t_web, 1)}
                trace["web"].append(web_trace)
                # 修正問題 3：精確捕捉 JSON 解析錯誤
                try:
                    web_items = json.loads(web_result)
                    web_trace["results"] = [
                        {"id": f"W{i}", "title": it.get("title", ""), "url": it.get("url", "")}
                        for i, it in enumerate(web_items, 1)
                    ]
                    for i, item in enumerate(web_items, 1):
                        title = item.get("title", "Web Result")
                        url = item.get("url", "unknown_url")
                        content = item.get("content", "")
                        rag_web_parts.append(
                            f"【W{i}｜網路搜尋｜{title}｜{url}】\n{content}"
                        )
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"   ⚠️ Web 搜尋結果 JSON 解析失敗: {e}，使用純文字 fallback")
                    # 只取前 2000 字元避免垃圾塞滿 context
                    rag_web_parts.append(f"【W1｜網路搜尋｜（原始結果）】\n{str(web_result)[:2000]}")

            # --- 步驟 B.5: 法律條文雙重驗證（僅限法律 Worker）---
            if worker_id in LAW_WORKER_IDS:
                print(f"   ⚖️ [法律驗證] 啟動網路雙重驗證...")
                verify_parts: List[str] = []
                try:
                    t_web = time.perf_counter()
                    verify_result = web_search.invoke({"query": f"台灣法律 {query}"})
                    verify_trace = {"kind": "verify", "query": f"台灣法律 {query}", "results": [],
                                    "sec": round(time.perf_counter() - t_web, 1)}
                    trace["web"].append(verify_trace)
                    try:
                        verify_items = json.loads(verify_result)
                        verify_trace["results"] = [
                            {"id": f"V{i}", "title": it.get("title", ""), "url": it.get("url", "")}
                            for i, it in enumerate(verify_items, 1)
                        ]
                        for i, item in enumerate(verify_items, 1):
                            title = item.get("title", "法律驗證來源")
                            url = item.get("url", "unknown_url")
                            content = item.get("content", "")
                            verify_parts.append(
                                f"【V{i}｜法條驗證搜尋｜{title}｜{url}】\n{content}"
                            )
                    except (json.JSONDecodeError, ValueError):
                        verify_parts.append(f"【V1｜法條驗證搜尋｜（原始結果）】\n{str(verify_result)[:2000]}")
                    # 截斷時優先保留：本地 S → 法條驗證 V → 一般網路 W（V 排在最後曾被截掉，模型仍引用不存在的 V 編號）
                    n_local = sum(1 for part in rag_web_parts if part.startswith("【S"))
                    rag_web_parts[n_local:n_local] = verify_parts
                    if used_source_type == "Local Database":
                        used_source_type = "Local Database + Web Verification"
                    elif used_source_type == "None":
                        used_source_type = "Web Verification"
                except Exception as e:
                    print(f"   ⚠️ 法律條文驗證搜尋失敗: {e}")

            # --- 步驟 C: 組裝 Context（有優先度的截斷）---
            # 修正問題 1 & 2：Tool context 優先，RAG/Web 逐段填剩餘空間
            MAX_CONTEXT_CHARS = 8000
            assembled_parts: List[str] = []
            remaining = MAX_CONTEXT_CHARS

            # Tool context 優先放入
            if tool_context:
                tool_block = f"【資料庫精確統計】\n{tool_context}"
                assembled_parts.append(tool_block)
                remaining -= len(tool_block)

            # 逐段加入 RAG/Web 文件，超過閾值就停止（以文件為邊界）
            truncated = False
            for part in rag_web_parts:
                if len(part) <= remaining:
                    assembled_parts.append(part)
                    remaining -= len(part)
                else:
                    truncated = True
                    break

            context_text = "\n\n".join(assembled_parts)
            if truncated:
                context_text += "\n...[部分參考文件因長度限制已省略]"

            if not context_text:
                context_text = "查無相關資料。"

            print(f"   🧠 [Worker]{worker_id} 正在撰寫結構化報告 ({used_source_type})...")

            # --- 步驟 D: 生成結構化報告（最多重試 3 次，每次縮短 context）---
            if worker_id in LAW_WORKER_IDS:
                system_content = f"""{self.description}

【法律回答準則】
- 引用任何法律條文時（如「第X條」），必須以 V 編號（法條驗證搜尋）的來源確認條號與條文內容正確。
- 若本地法條與網路驗證有出入，以最新的網路資料為準，並在回答中說明差異。
- confidence_score 需同時反映 RAG 與驗證來源的一致程度：完全一致 0.9+；有輕微差異 0.7；有衝突 0.5 以下。
- sources 必須同時列出本地來源（rag_docs）與網路驗證來源，不可只列其一。
- 若查無網路驗證資料，在 missing_info 中明確標註「條文驗證失敗，建議至全國法規資料庫 law.moj.gov.tw 確認」。
{_CITATION_RULES}"""
            else:
                base_role = self.description if self.description else f"你是 {worker_id}，能夠回答各類問題。"
                system_content = f"""{base_role}

任務：根據參考資料回答問題，並填入指定的結構化欄位：
- 若資料充足，confidence_score 給高分。
- sources 請列出具體的標題與網址。
{_CITATION_RULES}"""
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_content),
                ("human", "【參考資料】\n{context}\n\n【使用者問題】\n{query}"),
            ])

            structured_llm = self.llm.with_structured_output(WorkerOutput)
            chain = prompt | structured_llm

            # 每次重試逐步縮減 context，避免相同錯誤反覆出現
            RETRY_CONTEXT_LIMITS = [8000, 4000, 2000]

            result_obj = None
            last_err = None
            ctx_used = ""  # 成功那次實際送出的 context，用來判定哪些引用編號有效
            for attempt in range(3):
                try:
                    limit = RETRY_CONTEXT_LIMITS[attempt]
                    ctx = context_text[:limit] + ("\n...[因長度限制已截斷]" if len(context_text) > limit else "")
                    result_obj = chain.invoke({"context": ctx, "query": query})
                    ctx_used = ctx
                    break
                except Exception as parse_err:
                    last_err = parse_err
                    print(f"   ⚠️ 結構化輸出第 {attempt+1} 次失敗（context={RETRY_CONTEXT_LIMITS[attempt]} 字元），重試...")

            # 所有 structured output 嘗試都失敗，改用純文字 fallback 解析
            if result_obj is None:
                print(f"   ⚠️ Structured output 全數失敗，嘗試純文字 fallback...")
                try:
                    # 直接用訊息物件：ChatPromptTemplate 會把 JSON 範例的 {…} 當成模板變數而拋 KeyError
                    fallback_ctx = context_text[:2000]
                    fallback_messages = [
                        SystemMessage(content=(
                            f"你是 {worker_id}。根據參考資料回答問題。\n"
                            "請以 JSON 格式回答，包含以下欄位（不要有任何額外文字）：\n"
                            '{"worker_id":"...","content":"完整回答","sources":[],'
                            '"confidence_score":0.8,"thought_process":"...","missing_info":null,'
                            '"claims":[{"text":"重點","source_ids":["S1"]}]}\n'
                            + _CITATION_RULES
                        )),
                        HumanMessage(content=f"【參考資料】\n{fallback_ctx}\n\n【問題】\n{query}"),
                    ]
                    raw_response = self.llm.invoke(fallback_messages)
                    raw_content = _content_to_text(raw_response.content) if hasattr(raw_response, "content") else str(raw_response)
                    import re as _re
                    m = _re.search(r"\{.*\}", raw_content, flags=_re.S)
                    parsed = json.loads(m.group(0)) if m else {}
                    result_obj = WorkerOutput(
                        worker_id=worker_id,
                        content=parsed.get("content", raw_content[:500]),
                        sources=parsed.get("sources", []),
                        confidence_score=float(parsed.get("confidence_score", 0.5)),
                        thought_process=parsed.get("thought_process", "Fallback parsing"),
                        missing_info=parsed.get("missing_info"),
                        claims=[c for c in parsed.get("claims", []) if isinstance(c, dict) and c.get("text")],
                    )
                    ctx_used = fallback_ctx
                    print(f"   ✅ Fallback 解析成功")
                except Exception as fb_err:
                    print(f"   ❌ Fallback 也失敗: {fb_err}")
                    raise last_err

            output_data = result_obj.model_dump()
            output_data["worker_id"] = worker_id
            output_data["query"] = query
            output_data["chart_images"] = charts
            output_data["trace"] = trace
            output_data["elapsed_sec"] = round(time.perf_counter() - t_start, 1)
            output_data["grounding"] = assess_grounding(output_data.get("claims", []), _present_evidence_ids(ctx_used))
            g = output_data["grounding"]
            print(f"   🔎 [Worker]{worker_id} 依據等級：{g['level']}（{g['reason']}）")
            print(f"Worker{worker_id}輸出{output_data}")

            return {
                "worker_results": [output_data]
            }

        except Exception as e:
            print(f"❌ Worker Error: {e}")

            fallback = WorkerOutput(
                worker_id=worker_id,
                content=f"處理過程發生錯誤，無法生成報告: {str(e)}",
                confidence_score=0.0,
                thought_process="System Error",
                sources=[],
                missing_info="Error during execution"
            )
            fallback_data = fallback.model_dump()
            fallback_data["query"] = query
            fallback_data["trace"] = trace
            fallback_data["elapsed_sec"] = round(time.perf_counter() - t_start, 1)
            fallback_data["grounding"] = assess_grounding([], {})

            return {
                "worker_results": [fallback_data]
            }
