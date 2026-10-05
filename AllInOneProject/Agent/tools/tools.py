import os
import re
import json
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import List

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from AllInOneProject.Agent.tools.sql_query_tool import make_sql_query_tool

# ==========================================
# 既有工具：日期計算與網路搜尋
# ==========================================
def build_date_hint(user_text: str) -> str:
    now = datetime.now().astimezone()
    now_iso = now.isoformat()
    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", user_text or "")
    if not m:
        return f"CURRENT_TIME={now_iso}; DATE_HINT=none"

    y, mo, d = map(int, m.groups())
    try:
        dt = datetime(y, mo, d, tzinfo=now.tzinfo)
        delta_days = (dt.date() - now.date()).days
        return (
            f"CURRENT_TIME={now_iso}; "
            f"DATE_HINT={{'asked_date':'{dt.date()}','delta_days':{delta_days}}}"
        )
    except Exception:
        return f"CURRENT_TIME={now_iso}; DATE_HINT=parse_error"

@tool
def web_search(query: str, k: int = 5) -> str:
    """使用網路搜尋取得最新資訊。回傳 JSON 字串。"""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return json.dumps([{"title": "Error", "content": "ConfigError: TAVILY_API_KEY 未設定"}])

    tavily = TavilySearch(max_results=max(1, min(k, 8)))
    try:
        res = tavily.invoke({"query": query})
    except Exception:
        res = tavily.invoke(query)

    if isinstance(res, dict) and "results" in res:
        items = res["results"]
    elif isinstance(res, list):
        items = res
    else:
        items = [res]

    out = []
    for it in items[:k]:
        if isinstance(it, dict):
            out.append({
                "title": it.get("title") or it.get("url") or "",
                "url": it.get("url", ""),
                "content": it.get("content") or it.get("snippet") or "",
            })
        else:
            out.append({"title": "result", "url": "", "content": str(it)})
    return json.dumps(out, ensure_ascii=False)


# ==========================================
# 新增功能：啟動時 165 防詐騙資料 ETL 同步工具
# ==========================================

class ScamCaseRecord(BaseModel):
    loss_amount: int = Field(default=0, description="最終淨損失金額(整數)。無損失請填0。")
    fuzzy_loss_text: str = Field(default="", description="無法換算成整數時，摘要中描述損失的原文片段（如「損失數萬元」）。")
    platforms: List[str] = Field(default_factory=list, description="應用程式或特定平台名稱（不含網址）。")
    websites: List[str] = Field(default_factory=list, description="假網站網址或網域（如 www.fake-post.com）。")
    phone_numbers: List[str] = Field(default_factory=list, description="電話號碼列表。")
    scam_accounts: List[str] = Field(default_factory=list, description="具體帳號、ID或專屬稱呼。")

def _normalize_date(utc_date_str: str) -> str:
    """將 API 的 UTC 時間轉換為 YYYY-MM-DD 格式"""
    try:
        if not utc_date_str:
            return ""
        dt_utc = datetime.strptime(utc_date_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
        dt_taiwan = dt_utc + timedelta(hours=8)
        return dt_taiwan.strftime('%Y-%m-%d')
    except Exception:
        return str(utc_date_str)

def _general_clean_entities(entities: List[str], tw_converter) -> List[str]:
    """通用特徵過濾器"""
    cleaned = []
    generic_nouns = {"對方", "不明人士", "詐騙集團", "網站", "網路", "軟體", "APP", "朋友", "網友", "平台"}
    
    for item in entities:
        item = tw_converter.convert(item).strip()
        if not item: continue
        if len(item) > 20 and not any(char.isdigit() for char in item): continue
        if item in generic_nouns: continue
        if len(item) == 1 and not item.isalnum(): continue
        cleaned.append(item)
    return list(dict.fromkeys(cleaned))

def _general_clean_phones(phones: List[str]) -> List[str]:
    """電話號碼特徵過濾器"""
    cleaned = []
    for p in phones:
        clean_p = ''.join(char for char in p if char.isdigit() or char in '-+')
        if len(clean_p) >= 7:
            cleaned.append(clean_p)
    return list(dict.fromkeys(cleaned))

def sync_165_data_on_startup(new_pages: int = 3, backlog_pages: int = 0):
    """
    雙階段同步，解決大量積壓與長時間未開機的問題：

    Phase 1（新案件）: 從第 1 頁往後抓，直到命中上次儲存的 newest_synced_id 為止。
                       確保永遠不漏掉最新資料，即使積壓大量新案也能逐批追上。

    Phase 2（歷史積壓）: 從 next_backlog_page 游標繼續往舊資料推進，每次固定處理
                          backlog_pages 頁。每次啟動都穩定前進，直到全部 14 萬筆補完。

    state 儲存在 SQLite 的 sync_state 表，重啟後可無縫接續。
    每筆寫入後立即 commit，中途崩潰不會遺失已處理資料。
    """
    print("[Data Sync] 啟動防詐騙資料庫同步檢查...")

    try:
        import opencc
        from langchain_ollama import ChatOllama
    except ImportError:
        print("[Data Sync] 警告：缺少 opencc 或 langchain_ollama 套件，略過同步。")
        return

    tw_converter = opencc.OpenCC('s2twp')

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db_dir = os.path.join(project_root, "chroma_dbs")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "scam_records.sqlite3")

    # 確保 description.txt 存在，讓 rag_builder 能識別此 Worker
    desc_path = os.path.join(project_root, "rag_docs", "防詐騙專家", "description.txt")
    if not os.path.exists(desc_path):
        os.makedirs(os.path.dirname(desc_path), exist_ok=True)
        with open(desc_path, "w", encoding="utf-8") as f:
            f.write(
                "我是防詐騙專家，專精於分析真實詐騙案例（來源：165反詐騙諮詢專線）。"
                "我能查詢詐騙統計數據、識別詐騙手法、分析受害情境，並提供具體防詐騙建議。"
            )

    md_base_dir = os.path.join(project_root, "rag_docs", "防詐騙專家", "Domain_Knowledge")
    os.makedirs(md_base_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scam_cases (
            case_id TEXT PRIMARY KEY,
            date TEXT, city TEXT, title TEXT, summary TEXT,
            loss_amount INTEGER, fuzzy_loss_text TEXT,
            platforms TEXT, websites TEXT, scam_accounts TEXT, phone_numbers TEXT
        )
    ''')
    # 相容舊資料庫：若表已存在但缺少新欄位，補上（ALTER 失敗代表欄位已存在，忽略即可）
    for col in ("fuzzy_loss_text TEXT", "websites TEXT"):
        try:
            cursor.execute(f"ALTER TABLE scam_cases ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    # sync_state 儲存同步進度：newest_synced_id、next_backlog_page、backlog_complete
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()

    def get_state(key, default=None):
        cursor.execute("SELECT value FROM sync_state WHERE key=?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

    def set_state(key, value):
        cursor.execute("INSERT OR REPLACE INTO sync_state VALUES (?, ?)", (key, str(value)))
        conn.commit()

    # 載入所有已知 case_id（不設 LIMIT，ID 字串很小，14 萬筆約 20MB）
    cursor.execute("SELECT case_id FROM scam_cases")
    all_known_ids = {row[0] for row in cursor.fetchall()}

    # 讀取上次同步進度
    newest_synced_id  = get_state("newest_synced_id")           # Phase 1 的止損點
    next_backlog_page = int(get_state("next_backlog_page", new_pages + 1))  # Phase 2 游標
    backlog_complete  = get_state("backlog_complete") == "true"

    api_url = "https://165dashboard.tw/CIB_DWS_API/api/CaseSummary/GetCaseSummaryList"
    api_headers = {"Content-Type": "application/json", "Referer": "https://165dashboard.tw/"}

    def fetch_page(page_num) -> list:
        payload = {
            "PageIndex": page_num, "NumberOfPerPage": 50,
            "SortOrderInfos": [{"SortField": "CaseDate", "SortOrder": "DESC"}],
            "UsingPaging": True
        }
        try:
            resp = requests.post(api_url, headers=api_headers, json=payload, timeout=15)
            if resp.status_code != 200:
                return []
            return resp.json().get("body", {}).get("Detail", []) or []
        except Exception as e:
            print(f"[Data Sync] 頁面 {page_num} 請求失敗: {e}")
            return []

    def parse_item(item: dict) -> dict:
        return {
            "case_id": str(item.get("Id", "")),
            "date":    _normalize_date(item.get("CaseDate")),
            "city":    item.get("CityName") or "未知縣市",
            "title":   item.get("CaseTitle") or "無標題",
            "summary": item.get("Summary") or "無摘要",
        }

    # =========================================================
    # Phase 1：抓最新案件，直到命中 newest_synced_id 為止
    # =========================================================
    phase1_cases = []
    first_seen_id = None   # 本批最新案件的 ID，用來更新 newest_synced_id
    phase1_hit_boundary = False

    print(f"[Data Sync] Phase 1：檢查最新 {new_pages} 頁是否有新案件...")
    for page in range(1, new_pages + 1):
        details = fetch_page(page)
        if not details:
            phase1_hit_boundary = True
            break
        for item in details:
            cid = str(item.get("Id", ""))
            if first_seen_id is None:
                first_seen_id = cid  # 記錄本次看到的最新 ID
            if cid == newest_synced_id:
                phase1_hit_boundary = True
                break
            if cid not in all_known_ids:
                phase1_cases.append(parse_item(item))
        if phase1_hit_boundary:
            break

    if not phase1_hit_boundary:
        print(f"[Data Sync] Phase 1：{new_pages} 頁內未命中邊界，積壓案件超過 {new_pages * 50} 筆，下次啟動繼續追。")

    # =========================================================
    # Phase 2：從歷史游標繼續補齊舊資料
    # =========================================================
    phase2_cases = []
    if not backlog_complete:
        print(f"[Data Sync] Phase 2：從第 {next_backlog_page} 頁補齊歷史資料（{backlog_pages} 頁）...")
        fetched = 0
        for page in range(next_backlog_page, next_backlog_page + backlog_pages):
            details = fetch_page(page)
            if not details:
                set_state("backlog_complete", "true")
                backlog_complete = True
                print("[Data Sync] Phase 2：歷史資料已全部同步完畢！")
                break
            fetched += 1
            for item in details:
                cid = str(item.get("Id", ""))
                if cid not in all_known_ids:
                    phase2_cases.append(parse_item(item))
        else:
            set_state("next_backlog_page", next_backlog_page + fetched)
            print(f"[Data Sync] Phase 2：本次補至第 {next_backlog_page + fetched - 1} 頁，下次從第 {next_backlog_page + fetched} 頁繼續。")
    else:
        print("[Data Sync] Phase 2：歷史資料已全數同步，略過。")

    # 合併：先舊（phase2 最舊在 list 末端，reversed）再新（phase1 最舊在 list 末端，reversed）
    all_to_process = list(reversed(phase2_cases)) + list(reversed(phase1_cases))
    total_new = len(all_to_process)

    if total_new == 0:
        print("[Data Sync] 無新案例需同步。")
        conn.close()
        return

    print(f"[Data Sync] 共 {total_new} 筆待處理（Phase1: {len(phase1_cases)}, Phase2: {len(phase2_cases)}），啟動 Ollama 清洗...")

    # 先檢查 Ollama 是否可連線，避免逐筆失敗浪費時間
    try:
        requests.get("http://localhost:11434", timeout=3)
    except Exception:
        print("[Data Sync] ⚠️ Ollama 未啟動（連線被拒絕），略過本次資料清洗。請啟動 Ollama 後重啟系統。")
        conn.close()
        return

    try:
        llm = ChatOllama(model="qwen2.5:7b-instruct-q4_K_M", temperature=0, format="json")
        structured_llm = llm.with_structured_output(ScamCaseRecord)
    except Exception as e:
        print(f"[Data Sync] 本地模型載入失敗，略過資料清洗: {e}")
        conn.close()
        return

    base_prompt = """
    你是一個資料萃取系統。任務是從文本中提取「具體實體(Named Entities)」。
    如果文本沒有提供具體實體，必須回傳空列表 []。

    【萃取規則】
    1. loss_amount: 提取最終淨損失金額(整數)。排除年份、次數。有獲利需扣除。無損失填0。
    2. fuzzy_loss_text: 若摘要只有模糊描述（如「損失數萬元」、「損失不明」）而無法換算成精確整數時，填入該原文片段；能算出精確整數時留空字串。
    3. platforms: 提取具體的「應用程式」或「特定平台名稱」（不含網址）。
    4. websites: 提取假網站的「網址」或「網域」。
    5. phone_numbers: 提取 7 碼以上的電話號碼。
    6. scam_accounts: 提取具體的「英文/數字ID」、「銀行帳號」或「帶有名字的化名」。絕對不要提取單獨的"客服"、"網友"、"女子"等一般稱呼。

    【學習範例】
    摘要：我在交友軟體認識自稱「陳經理」的人，他要我下載「超級發財APP」並轉帳到台新銀行帳戶，我共被騙了 15000 元。
    輸出：{"loss_amount": 15000, "fuzzy_loss_text": "", "platforms": ["超級發財APP"], "websites": [], "phone_numbers": [], "scam_accounts": ["陳經理", "台新銀行帳戶"]}

    摘要：收到簡訊說包裹退件，要我打 0911-222-333，並登入 www.fake-post.com，結果被刷卡 3000 元。
    輸出：{"loss_amount": 3000, "fuzzy_loss_text": "", "platforms": [], "websites": ["www.fake-post.com"], "phone_numbers": ["0911-222-333"], "scam_accounts": []}

    摘要：一名女網友說她家人生病需要錢，我陸續匯款給她，損失數萬元，後來她就消失了。
    輸出：{"loss_amount": 0, "fuzzy_loss_text": "損失數萬元", "platforms": [], "websites": [], "phone_numbers": [], "scam_accounts": []}

    【請處理以下案件摘要】
    """

    success_count = 0
    for i, case in enumerate(all_to_process, 1):
        print(f"  [{i}/{total_new}] {case['case_id']} ({case['city']}) {case['title'][:20]}...")
        try:
            cleaned_data = structured_llm.invoke(base_prompt + case["summary"])
            final_platforms = _general_clean_entities(cleaned_data.platforms, tw_converter)
            final_websites  = _general_clean_entities(cleaned_data.websites, tw_converter)
            final_accounts  = _general_clean_entities(cleaned_data.scam_accounts, tw_converter)
            final_phones    = _general_clean_phones(cleaned_data.phone_numbers)
            fuzzy_loss_text = tw_converter.convert(cleaned_data.fuzzy_loss_text).strip()

            print(f"         損失 {cleaned_data.loss_amount} 元 | 平台: {', '.join(final_platforms) or '無'}")

            cursor.execute('''
                INSERT OR REPLACE INTO scam_cases
                (case_id, date, city, title, summary, loss_amount, fuzzy_loss_text,
                 platforms, websites, scam_accounts, phone_numbers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                case["case_id"], case["date"], case["city"], case["title"], case["summary"],
                cleaned_data.loss_amount,
                fuzzy_loss_text,
                ", ".join(final_platforms),
                ", ".join(final_websites),
                ", ".join(final_accounts),
                ", ".join(final_phones)
            ))
            conn.commit()  # 每筆立即 commit，崩潰後不需重跑已成功的案件

            city_dir = os.path.join(md_base_dir, case["city"])
            os.makedirs(city_dir, exist_ok=True)
            md_path = os.path.join(city_dir, f"{case['case_id']}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# 案件編號：{case['case_id']}\n")
                f.write(f"- 發生日期：{case['date']}\n")
                f.write(f"- 發生縣市：{case['city']}\n")
                f.write(f"- 案件標題：{case['title']}\n")
                f.write(f"- 損失金額：{cleaned_data.loss_amount} 元" + (f"（{fuzzy_loss_text}）" if fuzzy_loss_text else "") + "\n")
                f.write(f"- 涉及平台：{', '.join(final_platforms)}\n")
                f.write(f"- 假網站：{', '.join(final_websites)}\n")
                f.write(f"- 詐騙帳號/ID：{', '.join(final_accounts)}\n")
                f.write(f"- 涉及門號：{', '.join(final_phones)}\n\n")
                f.write(f"## 案件摘要\n{case['summary']}\n")

            success_count += 1
        except Exception as e:
            print(f"         處理失敗: {e}")

    # 更新 Phase 1 的邊界（下次啟動用這個 ID 作為止損點）
    if first_seen_id:
        set_state("newest_synced_id", first_seen_id)

    conn.close()
    print(f"[Data Sync] 同步完成！新增 {success_count} 筆（Phase1: {len(phase1_cases)}, Phase2: {len(phase2_cases)}）。")

_SCAM_DB_DESCRIPTION = """
強大的防詐騙資料庫統計與分析工具。
當使用者詢問「數量統計」、「金額加總」、「極值計算」、「特定條件分組排行」等需要精確運算的問題時，必須呼叫此工具。

【資料表結構 (Schema)】
Table Name: scam_cases
Columns:
- case_id (TEXT): 案件編號 (Primary Key)
- date (TEXT): 發生日期，格式 YYYY-MM-DD
- city (TEXT): 發生縣市 (例如：臺北市, 臺中市)
- title (TEXT): 案件標題
- summary (TEXT): 案件完整內容摘要
- loss_amount (INTEGER): 淨損失金額 (整數)
- fuzzy_loss_text (TEXT): 無法換算成精確整數時的損失金額原文描述
- platforms (TEXT): 涉及的應用程式、平台(逗號分隔)
- websites (TEXT): 假網站或網址 (逗號分隔)
- scam_accounts (TEXT): 詐騙帳號、ID或專屬化名 (逗號分隔)
- phone_numbers (TEXT): 涉及的電話門號 (逗號分隔)

【輸入與語法限制】
1. 必須傳入一組標準的 SQLite 查詢語法。
2. 絕對禁止使用未列出的欄位名稱。
3. 範例：查詢臺北市總損失與件數：SELECT COUNT(*), SUM(loss_amount) FROM scam_cases WHERE city = '臺北市';
4. 範例：查詢包含特定平台的案件：SELECT title, loss_amount FROM scam_cases WHERE platforms LIKE '%賣貨便%';
"""

analyze_scam_database = make_sql_query_tool(
    name="analyze_scam_database",
    description=_SCAM_DB_DESCRIPTION,
    db_path=os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "chroma_dbs",
        "scam_records.sqlite3",
    ),
)