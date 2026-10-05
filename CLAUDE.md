# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 啟動指令

```powershell
# 儀表板主系統（登入 + 儀表板 + AI 助理 + 通報，port 8081）
python main.py

# 防詐騙 AI 助理獨立 UI（port 8080，深色主題）
python AI_assistantWeb.py

# 舊版獨立 UI（port 8080，已由 AI_assistantWeb.py 取代，勿與上者同時啟動；僅供手動除錯用）
python AllInOneProject/View/legacy_main.py
```

> ⚠️ `AI_assistantWeb.py` 與 `AllInOneProject/View/legacy_main.py` 皆佔用 port 8080，不可同時執行。

## 目錄結構

根目錄與 `AllInOneProject/` 都採用 View / Model / Controller 分層。**兩者是不同的套件**（`from View import dashboard` 是根目錄的 UI 頁面層；`from AllInOneProject.View import legacy_main` 是子專案內部的舊版獨立 UI），命名相同但責任不同：根目錄的 Model/View/Controller 服務儀表板系統本身，`AllInOneProject/` 的則是 Agent 系統的執行架構。

```
MyBigProject/
├── main.py                  # 儀表板主入口（port 8081）：整合登入、儀表板、AI 助理、通報、管理
├── AI_assistantWeb.py       # 防詐騙 AI 助理獨立 UI（port 8080，深色主題 + 常用提示詞側欄）
├── View/                    # 頁面層（NiceGUI @ui.page）
│   ├── dashboard.py          # /dashboard：KPI 卡片、月趨勢、詐騙類型排行、縣市統計
│   ├── assistant.py          # /assistant：整合 Agent + 進階問答表單 + Thinking Log 側欄
│   ├── report_page.py        # /report：使用者詐騙通報表單
│   ├── admin_page.py         # /admin：管理員頁面（需 admin role）
│   ├── auth_pages.py         # /login、/register、/logout 頁面
│   ├── case_query.py         # /cases：案例查詢（唯讀）
│   ├── my_reports.py         # /my-reports：使用者查看自己的通報
│   └── components.py         # 共用 UI 元件（render_navbar）
├── Model/                   # 資料存取層（SQLite）
│   ├── auth_db.py             # 使用者認證（bcrypt、WAL 模式）
│   ├── report_db.py           # 通報資料 CRUD
│   └── scam_db.py             # 165 案例唯讀查詢
├── Controller/               # 中介邏輯層
│   └── auth_middleware.py     # NiceGUI session 認證：require_login / require_admin 裝飾器
├── dev_scripts/              # 手動 smoke-test 腳本（非自動化測試，需手動執行）
│   ├── scratch_agent_test.py
│   ├── scratch_callback_test.py
│   ├── scratch_sqlite.py
│   ├── benchmark_embed_batch_size.py         # 量測 bge-m3 embedding 在不同 batch_size 下的速度/VRAM
│   ├── simulate_165_sync_pipeline.py         # 用假資料模擬 165 同步管線（不呼叫 Ollama），驗證清洗邏輯與 DB schema
│   ├── test_vllm_165_extraction.py           # [獨立測試腳本，不接入系統] 拿真實 165 資料測自架 vLLM 實體抽取（循序版）
│   ├── test_vllm_165_extraction_concurrent.py # 同上，改為併發呼叫，量測併發負載下的吞吐量
│   ├── test_vllm_165_concurrency_sweep.py    # 對同一批 165 案件掃不同併發數，找吞吐量/延遲/失敗率甜蜜點
│   ├── demo_autofill.py                      # 錄影 Demo：Playwright 開真瀏覽器逐字填入表單（範例在 demo_autofill_data.py；只填不送出）
│   ├── compact_faiss_store.py                # 離線整理大型 FAISS 庫：清除舊路徑重複向量/tombstone、source 轉相對路徑（需先停 main.py）
│   └── rag_eval/                             # RAG 檢索評測：questions.json（含標準答案）+ eval_rag.py（collect / report / e2e）
└── AllInOneProject/
    ├── View/legacy_main.py      # [已棄用] 最早期獨立測試 UI，僅供手動除錯
    ├── Controller/
    │   ├── agent_system.py      # HolisticAgentSystem singleton + AgentResponse + 事件串流
    │   └── bridge.py            # 對外唯一介面：AllInOneAgent.ask()
    ├── Model/
    │   ├── config.py            # 路徑常數（BASE_DIR, RAG_ROOT_DIR, DB_PERSIST_ROOT, RAG_THRESHOLD）
    │   ├── state.py             # MultiState, SubTask, ExecutionPlan
    │   └── worker_config.py     # 使用者自訂 Worker 的啟用/停用狀態（讀寫 user_workers.json）
    ├── Agent/
    │   ├── base_node.py         # BaseNode / AgentNode 基底類別
    │   ├── graph.py             # LangGraph StateGraph 建構（build_chat_flow）
    │   ├── rag_builder.py       # MultiAgentRAGBuilder，掃描 rag_docs/
    │   ├── requirement.py       # HumanRequirementNode
    │   ├── planner.py           # PlannerNode
    │   ├── synthesizer.py       # SynthesizerNode
    │   ├── composer.py          # ComposerNode（品質評估 + retry 閘門）
    │   ├── worker.py            # WorkerNode（RAG + web fallback + tool calling）
    │   └── tools/tools.py       # web_search（Tavily）、sync_165_data_on_startup、analyze_scam_database
    ├── rag_docs/                # 各 Worker 知識庫（不可刪除）
    ├── chroma_dbs/              # ChromaDB/FAISS 向量庫 + SQLite 資料庫（自動產生）
    │   ├── scam_records.sqlite3 # 165 防詐騙案例（sync 自動產生）
    │   ├── auth.sqlite3         # 使用者帳號（main.py 啟動時建立）
    │   └── reports.sqlite3      # 使用者通報（main.py 啟動時建立）
    └── .env                     # GOOGLE_API_KEY, TAVILY_API_KEY
```

## 架構重點

### 儀表板系統（main.py，port 8081）
`main.py` 整合多個頁面模組，啟動時初始化兩個 DB：

```python
auth_db.init_db()    # 建立 users 表 + 預設 admin/admin123
report_db.init_db()  # 建立 reports 表
```

根路由 `/` 依登入狀態跳轉：已登入 → `/dashboard`，未登入 → `/login`。

**認證流程**：`Controller/auth_middleware.py` 使用 `app.storage.user["auth_user"]` 儲存 session，提供：
- `require_login`：未登入導向 `/login`
- `require_admin`：非 admin 導向 `/dashboard`
- `get_current_user()` / `is_logged_in()` / `is_admin()`

**View/dashboard.py**：直接讀取 `AllInOneProject/chroma_dbs/scam_records.sqlite3`，顯示即時 KPI（總案件、財損、近期通報、電話舉報）、月趨勢長條圖、詐騙類型 Top 5、縣市統計表。資料庫不存在時顯示靜態 placeholder。

**View/assistant.py**：三欄佈局（進階問答表單 | 對話區 | 快速提示 + Thinking Log），透過 `on_step` callback 即時顯示 Agent 執行事件。

### Agent 執行流程
```
使用者輸入 → requirement（澄清需求）→ planner（分派任務）
  → [workers 平行執行]（RAG 查詢 or 網路搜尋 + 可選 tool calling）
  → composer（品質評估）→ synthesizer（整合回答）
              ↑__________ retry（最多 2 次）
```

### 對外介面（AllInOneProject/Controller/bridge.py）
`main.py`（透過 `View/assistant.py`）、`AI_assistantWeb.py` 皆透過 `AllInOneProject/Controller/bridge.py` 整合 Agent：
```python
from AllInOneProject.Controller.bridge import agent
response = await agent.ask(user_id, text, is_reply=False, on_step=None)
# response: AgentResponse(response_text, thread_id, status, planner_thought, metadata)
# status: "completed" | "interrupted" | "error"
```
`is_reply=True` 用於回覆系統的追問（LangGraph interrupt/resume 機制）。
`on_step(step_type, detail)` 為可選 callback，由 `agent_system.py` 的事件串流呼叫。

### 事件串流（AllInOneProject/Controller/agent_system.py）
`process_request()` 透過 `on_step(step_type, detail[, data])` 發送即時事件（callback 若接受第三個參數，會另外收到結構化 `data` 供排版），`View/assistant.py` 的 `ThinkingLog` 依此繪製時間軸（每個問題一組、舊的自動收合、標示相對秒數與總耗時）。

**detail 慣例：第一行為標題，其餘各行為可展開內容**（Thinking Log 預設收合）。`on_step` 由背景執行緒呼叫，`ThinkingLog.on_step` 只排入佇列，由頁面 `ui.timer` 在主事件迴圈繪製，不可在 callback 內直接操作 UI。

| step_type | 時機 / 內容 |
|---|---|
| `system` | 收到新問題 / 繼續上一輪對話 |
| `requirement` | HumanRequirementNode 完成 |
| `interrupt` | 需要使用者補充資訊（流程在此結束） |
| `planner` | 規劃完成（展開：plan_summary） |
| `planner_dispatch` | `分派 N 位專家：...`（UI 依 N 顯示執行進度，勿改格式） |
| `planner_task` | 每個子任務（展開：query） |
| `worker_done` | Worker 完成・依據等級・耗時（展開：依據原因、模型自評、每個重點的引用）。`stream_mode="updates"` 在節點完成後才送出，因此沒有「開始」事件 |
| `worker_tool` | Worker 呼叫的工具（展開：參數、結果摘要） |
| `worker_rag` | 知識庫檢索採用筆數（展開：每份文件的完整 source 與關聯度） |
| `worker_web` | 網路搜尋 / 法條驗證搜尋（展開：查詢與結果網址） |
| `worker_thought` | Worker 推論過程 |
| `worker_sources` | Worker LLM 自述的引用來源（完整、不截斷） |
| `worker_chart` | 產生圖表 |
| `composer` | 品質評估通過 / 不足重試（展開：原因） |
| `synthesizer` | SynthesizerNode 整合 |
| `done` / `error` | 流程結束 |

`worker_tool` / `worker_rag` / `worker_web` 來自 Worker 回傳的 `trace`（系統實際執行紀錄，非 LLM 自述），與 `elapsed_sec` 一起放在 `worker_results`；Composer / Synthesizer 只取特定欄位，不會把 trace 送進 LLM。

### AI_assistantWeb.py 架構
防詐騙 AI 助理的獨立 UI，使用 NiceGUI 建構，透過 `AllInOneProject.Controller.bridge` 呼叫 Agent。

- **`@ui.page("/")`**：每個連線各自建立獨立頁面實例（`chat_log`、`is_reply` 狀態互不干擾）。
- **`app.storage.user`**：per-user 的 `session_id`、`is_reply` 狀態儲存。
- **`rag_agent_instance`**：module 載入時取得 bridge singleton，所有連線共用同一 Agent 實例。

### 節點繼承架構
```
BaseNode（介面定義）
  └── AgentNode（持有 self.llm，提供 _safe_invoke / _build_system_prompt）
        ├── HumanRequirementNode
        ├── PlannerNode（build_runner 返回 llm.with_structured_output(ExecutionPlan)）
        ├── SynthesizerNode
        ├── ComposerNode（額外持有 self.worker_map；Worker → Composer → Synthesizer 品質閘門）
        └── WorkerNode（額外持有 self.db、self.tools）
```
**重要**：`WorkerNode.__init__` 必須在 `super().__init__()` **之前**設好 `self.db`、`self.tools`、`self.RAG_THRESHOLD`，因為父類別的 `__init__` 會呼叫 `build_runner()`。同理，`ComposerNode.__init__` 必須在 `super().__init__()` 前設好 `self.worker_map`。

### State 設計（AllInOneProject/Model/state.py）
```python
class MultiState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]          # LangChain 標準合併
    variables: Annotated[Dict[str, Any], merge_dicts]             # shallow merge
    worker_results: Annotated[List[Dict], reduce_results]         # "RESET" 字串可清空
```
`variables` 的重要 key：`tasks_to_execute`（Planner 輸出的任務清單）、`plan_summary`、`last_question`。

### WorkerNode 執行邏輯
每個 Worker 依序執行：
1. **RAG 查詢**：`similarity_search_with_score(k=5~15)`（依 DB 大小動態調整），由 `select_rag_docs()` 以**相對門檻**篩選（`config.py` 的 `RAG_STRONG/RAG_WEAK/RAG_MARGIN`）：最佳距離 < 0.70 只用本地；0.70～0.85 本地片段照用並另外搜尋網路（`local+web`）；≥ 0.85 只用網路；只採用與最佳距離相差 0.10 以內的片段。
   - 門檻由評測決定，**調整前後務必跑** `python dev_scripts/rag_eval/eval_rag.py collect && ... report`（檢索層、確定性）；`e2e` 用真實 Gemini 檢查回答關鍵字（會耗 token，且逐次會有 1～2 題波動）。
   - 舊做法為絕對門檻 0.7 且「全有或全無」，實測正確片段常落在 0.70～0.80 而被整批丟棄（命中 19/23 → 新做法 22/23，不相關題誤用皆 0/7）。
   - 已知限制：一句話同時問兩件事時，單一查詢向量只會靠近其中一件（例如 coffee-02），需另行做問題拆解。
2. **Web fallback**：本地依據不足（`local+web` / `web`）時呼叫 Tavily。法律 Worker 另外做法條驗證搜尋；截斷時優先保留順序為 本地 S → 法條驗證 V → 一般網路 W。
3. **Tool calling**（可選）：`_gather_tool_context()` 讓 LLM 自主決定是否呼叫工具（最多 3 輪）。`worker_防詐騙專家` 掛載 `analyze_scam_database`；`worker_數據分析專家` 另掛 `compute_statistics`、`generate_chart`。
   - **數據分析表單不走 LLM 決定**：表單勾選的統計項目與圖表是明確參數，UI 以結構化 `analysis_request`（`data_text`、`operations`、`charts`、`target_column`、`group_by`）經 `bridge.ask(..., analysis_request=)` → `variables["analysis_request"]` 傳給 Worker，由 `run_analysis_request()`（`data_analysis_tools.py`）直接執行；LLM 只解讀結果寫報告。圖表一律 X=分組欄位、Y=目標欄位。
   - 舊做法把參數寫成文字請 LLM 呼叫工具，實測 LLM 只算統計沒畫圖，報告卻捏造 4 段圖表說明。
   - `variables` 在同一 thread 跨輪保留，`process_request` 每個新問題都會覆寫 `analysis_request`（無則 None）。
   - 圖表 base64 走 `chart_sink` 參數（每次請求獨立），不存在 `self`，避免並行請求互相覆蓋。
4. **Context 截斷**：合併後超過 8000 字元自動截斷，避免 structured output 失敗。
5. **結構化報告**：`llm.with_structured_output(WorkerOutput)` 最多重試 3 次。

`WorkerOutput` schema：`worker_id`, `content`, `sources(List[Reference])`, `confidence_score`, `thought_process`, `missing_info`, `claims(List[Claim])`

### 依據等級（grounding，worker.py `assess_grounding`）
`confidence_score` 是 LLM 自評、不可信（曾在答錯時自評 100%），**品質判斷改看系統檢查引用得出的依據等級**：
- 送進 LLM 的每段參考資料都有編號：`S`=本地知識庫、`T`=工具查詢結果、`W`=網路搜尋、`V`=法條驗證搜尋（格式 `【S1｜…】`）。
- Worker 在 `claims` 逐條列出回答重點與引用編號；系統只承認「確實出現在實際送出的 context 中」的編號（被截斷或捏造的編號無效）。
- `grounded`（有依據）：≥80% 重點有有效引用且 ≥80% 有本地（S/T）依據；`partial`（部分依據）：≥50% 有有效引用（含僅網路）；其餘 `ungrounded`（無依據）。
- 結果存在 `worker_results[i]["grounding"]`；Composer 遇 `ungrounded` 判定品質不足並重試。
- 尚未做（第二階段）：逐條驗證引用內容是否真的支持該重點（需額外 LLM 呼叫）。

### 165 防詐騙資料同步（tools/tools.py）
`sync_165_data_on_startup(new_pages=3, backlog_pages=0)` 在 `build_chat_flow()` 啟動時自動執行：

- **Phase 1**（每次都跑）：抓最新 `new_pages` 頁，遇到 `sync_state.newest_synced_id` 即停止，確保新案件不遺漏。
- **Phase 2**（積壓補齊）：從 `sync_state.next_backlog_page` 繼續往後抓，`backlog_pages=0` 表示本次跳過。手動批量補齊歷史時調大此值（例如 `backlog_pages=50`，一次補 2500 筆）。

資料流：165 API JSON → **Ollama（`qwen2.5:7b-instruct-q4_K_M`）實體抽取** → SQLite `scam_cases` 表 + Markdown 檔案（`rag_docs/防詐騙專家/Domain_Knowledge/<縣市>/`）。
`description.txt` 由同步工具自動建立，確保 RAG Builder 能識別該 Worker。
每筆資料獨立 `conn.commit()`（crash safe），使用 `INSERT OR REPLACE` 確保冪等。

### `analyze_scam_database` 工具
掛載於 `worker_防詐騙專家`，讓 LLM 將自然語言轉為 SQL 查詢 SQLite。
欄位：`case_id`, `date`, `city`, `title`, `summary`, `loss_amount`, `platforms`, `scam_accounts`, `phone_numbers`。
LLM 自動生成完整 SQL（含 `GROUP BY`、`SUM`、`AVG`、`WHERE`）；安全限制：禁止 `DROP`、`DELETE`、`UPDATE`、`INSERT`、`ALTER`，以 read-only 模式開啟 DB。

### RAG Builder 增量更新（rag_builder.py）
- `count == 0`：全量建立（`_build_all_chunks`）。
- `count > 0`：從 ChromaDB metadata 取得 `embedded_sources`，只對新檔案執行 embedding（`_build_new_chunks`）。
- **source key 一律是相對於 `rag_docs/` 的路徑、以 `/` 分隔**（`_source_key()`，例如 `防詐騙專家/Domain_Knowledge/臺北市/xxx.md`）。**不可改回絕對路徑**：專案搬移或跨 Windows/Linux 時絕對路徑全變，會把所有檔案重新 embed 且舊向量殘留（防詐騙專家曾因此累積三份重複）。
- 檔案已從磁碟移除（含 Worker 刪除/改名）時，重建會自動清除其向量：Chroma 直接刪除，FAISS（`_merged`）以 `deleted = 1` tombstone 標記（保持 rowid 與 FAISS id 對齊）。大量刪除請改用 `dev_scripts/compact_faiss_store.py` 離線整理。
- 向量庫資料夾以 Worker 名稱命名（`chroma_dbs/<名稱>/`）。Worker 改名 / 刪除 / 建立失敗時，`bridge.py` 會呼叫 `drop_worker_vectors()` 清空舊名稱的 Chroma collection（否則之後再建同名 Worker 會沿用舊向量，同檔名的新內容不會被 embed）；空資料夾於下次啟動時由 `_cleanup_stale_stores()` 刪除（執行中 Chroma 會快取 client，不可直接刪檔）。Worker 名稱不可以 `.`/`_` 開頭或含路徑字元。
- 大型 FAISS 庫若偵測到舊版絕對路徑 key 會直接拒絕啟動，須先執行 `python dev_scripts/compact_faiss_store.py --apply`。
- embedding 模型與 FAISS store 在整個 process 內共用單一實例（rebuild 不重新載入），避免新舊 graph 並存時 VRAM / RAM 翻倍；embedding 遇 GPU OOM 會自動將 batch 減半重試。
- `.md` 檔案由 `MarkdownHeaderTextSplitter`（按 `#`/`##` 切分）+ `RecursiveCharacterTextSplitter`（中文分隔符）雙層處理。
- 非 `.md` 檔案用原生 `open()` 讀取（不依賴 `UnstructuredFileLoader`）。

### Planner 路由機制
Planner 輸出 `ExecutionPlan`（structured output），Worker ID 若不在合法清單，自動嘗試補前綴 `worker_`，仍無效則 fallback 到 `internet_search`。
`description.txt` 的內容直接決定 Planner 如何選擇專家——寫得越清晰，路由越準確。

### 新增 Worker
在 `AllInOneProject/rag_docs/` 新增資料夾，結構如下：
```
rag_docs/<WorkerName>/
├── description.txt        # Worker 的角色描述（一段話），Planner 依此判斷是否分派任務
└── Domain_Knowledge/      # 知識文件（支援 .txt、.md 等）
```
系統啟動時自動掃描並建立向量索引，Worker ID 格式為 `worker_<WorkerName>`。若要掛載工具，在 `graph.py` 的 WorkerNode 建構時傳入 `tools=[...]`。

### sys.path 機制
`AI_assistantWeb.py`、`View/assistant.py`、`AllInOneProject/View/legacy_main.py`、`AllInOneProject/Controller/bridge.py` 頂端都有路徑自修正，確保 **`MyBigProject/`（不是 `AllInOneProject/`）根目錄**在 sys.path 中：
```python
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 依檔案深度調整 dirname 次數
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
```
`AllInOneProject/` 內部所有跨模組 import 一律使用 **`AllInOneProject.` 前綴的完整路徑**：`from AllInOneProject.Model.state import MultiState`、`from AllInOneProject.Agent.graph import build_chat_flow`。

> ⚠️ **不可改回 bare import（如 `from Model.state import ...`）**：根目錄現在也有同名的 `Model/`、`View/`、`Controller/` 套件。若 `AllInOneProject/` 內部用 bare import 又把 `AllInOneProject/` 本身插入 sys.path，會與根目錄同名套件搶命名（哪個先被 import 就快取哪個），導致 `ModuleNotFoundError`。務必保持 `AllInOneProject.` 完整前綴。

### Model/config.py 路徑計算
`AllInOneProject/Model/config.py` 的 `BASE_DIR` 以 `__file__` 絕對位置計算（dirname 兩次），與執行目錄無關，確保 `rag_docs/`、`chroma_dbs/`、`scam_records.sqlite3` 路徑永遠正確。

## 常見問題

**import 錯誤 / ModuleNotFoundError**
```powershell
Get-ChildItem -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force
```

**Port 被佔用（Errno 10048）**
```powershell
netstat -ano | findstr ":8081"
Stop-Process -Id <PID> -Force
```

**新 Worker 未被載入**
確認資料夾內有 `description.txt`（缺少此檔案會被 `rag_builder.py` 跳過）。


**Structured output 解析失敗（Invalid json output）**
Worker 已內建截斷（8000 字元）與重試（3 次）機制。若仍失敗，檢查 context 是否包含特殊字元或過長的工具輸出。

**Port 8080 已被佔用（AI_assistantWeb.py 或 AllInOneProject/View/legacy_main.py）**
兩者不可同時執行。確認哪個 process 佔用後擇一關閉：
```powershell
netstat -ano | findstr ":8080"
Stop-Process -Id <PID> -Force
```

**Planner 路由到錯誤的 Worker**
調整 `description.txt` 描述，使其更明確地標示專業範圍；或檢查 Planner prompt 中的合法 ID 清單是否正確載入。

**Embedding 速度異常慢 / 確認 GPU 是否生效**
`rag_builder.py` 啟動時會印出目前 embedding 裝置：
```
🖥️  Embedding 裝置：CUDA   # 或 CPU
```
若顯示 `CPU`，多半是目前執行的 Python 直譯器沒裝到 CUDA 版 torch（例如用了系統 PATH 的 `python` 而非專案 `venv`）。確認方式：
```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
若 `torch.__version__` 沒有 `+cuXXX` 後綴或 `cuda.is_available()` 為 `False`，需依 `requirements.txt` 內的 `--extra-index-url` 重新安裝 CUDA 版 torch。`EMBED_BATCH_SIZE`（`AllInOneProject/Model/config.py`）控制 embedding 的 batch size，GPU VRAM 充足時可調大以加速。

**165 資料同步需要 Ollama**
`sync_165_data_on_startup` 依賴本地 Ollama 服務（`qwen2.5:7b-instruct-q4_K_M`）進行實體抽取。確認 Ollama 服務已啟動：
```powershell
ollama list
ollama run qwen2.5:7b-instruct-q4_K_M
```
