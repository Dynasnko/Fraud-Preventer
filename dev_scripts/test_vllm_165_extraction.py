"""
[獨立測試腳本，不接入系統] 呼叫使用者自架的 vLLM（OpenAI 相容 API，預設
http://192.168.1.101:8080/v1）跑一次真實的 165 案件實體抽取，驗證：

1. vLLM 回傳的 JSON 是否能被 ScamCaseRecord（tools.py 正式使用的 pydantic schema）驗證通過
2. 清洗函式（複用 tools.py 的 _general_clean_entities / _general_clean_phones）處理起來是否正常
3. 最終欄位組合寫進 SQLite 後是否符合 scam_cases 表結構

只匯入 tools.py 裡「純函式」（ScamCaseRecord / _normalize_date / _general_clean_entities /
_general_clean_phones，皆無副作用、不碰任何全域狀態或 sys.path），沒有呼叫 sync_165_data_on_startup、
沒有動到正式的 scam_records.sqlite3、沒有改動 tools.py 本身 —— 純粹是另外拿來對照驗證用的腳本，
跟正式系統的執行路徑（Ollama）完全分開，不會互相影響。

用法：
    python dev_scripts/test_vllm_165_extraction.py
    python dev_scripts/test_vllm_165_extraction.py --base-url http://192.168.1.101:8080/v1 --model Qwen3-32B
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time

import requests

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from AllInOneProject.Agent.tools.tools import (
    ScamCaseRecord, _normalize_date, _general_clean_entities, _general_clean_phones,
)
from pydantic import ValidationError

try:
    import opencc
    tw_converter = opencc.OpenCC('s2twp')
except ImportError:
    print("缺少 opencc（正式流程也依賴它），改用不轉換簡繁的替代版本。")
    class _NoopConverter:
        def convert(self, s): return s
    tw_converter = _NoopConverter()


# 與 tools.py 的 base_prompt 完全一致（獨立複製一份，避免這個測試腳本反過來 import
# 正式流程內部的 local 變數；如果之後正式 prompt 有調整，記得同步更新這裡）。
BASE_PROMPT = """
你是一個資料萃取系統。任務是從文本中提取「具體實體(Named Entities)」。
如果文本沒有提供具體實體，必須回傳空列表 []。

【萃取規則】
1. loss_amount: 提取最終淨損失金額(整數)。排除年份、次數。有獲利需扣除。無損失填0。
2. fuzzy_loss_text: 若摘要只有模糊描述（如「損失數萬元」、「損失不明」）而無法換算成精確整數時，填入該原文片段；能算出精確整數時留空字串。
3. platforms: 提取具體的「應用程式」或「特定平台名稱」（不含網址）。
4. websites: 提取假網站的「網址」或「網域」。
5. phone_numbers: 提取 7 碼以上的電話號碼。
6. scam_accounts: 提取具體的「英文/數字ID」、「銀行帳號」或「帶有名字的化名」。絕對不要提取單獨的"客服"、"網友"、"女子"等一般稱呼。

請只回傳一個 JSON 物件，格式為：
{"loss_amount": int, "fuzzy_loss_text": str, "platforms": [str], "websites": [str], "phone_numbers": [str], "scam_accounts": [str]}

【學習範例】
摘要：我在交友軟體認識自稱「陳經理」的人，他要我下載「超級發財APP」並轉帳到台新銀行帳戶，我共被騙了 15000 元。
輸出：{"loss_amount": 15000, "fuzzy_loss_text": "", "platforms": ["超級發財APP"], "websites": [], "phone_numbers": [], "scam_accounts": ["陳經理", "台新銀行帳戶"]}

摘要：收到簡訊說包裹退件，要我打 0911-222-333，並登入 www.fake-post.com，結果被刷卡 3000 元。
輸出：{"loss_amount": 3000, "fuzzy_loss_text": "", "platforms": [], "websites": ["www.fake-post.com"], "phone_numbers": ["0911-222-333"], "scam_accounts": []}

摘要：一名女網友說她家人生病需要錢，我陸續匯款給她，損失數萬元，後來她就消失了。
輸出：{"loss_amount": 0, "fuzzy_loss_text": "損失數萬元", "platforms": [], "websites": [], "phone_numbers": [], "scam_accounts": []}

【請處理以下案件摘要】
"""

# 真實感的測試摘要（模仿 165 API 資料型態），涵蓋一般案例與邊界情況
TEST_CASES = [
    {"Id": "VLLM_SIM_001", "CaseDate": "2026-04-13T00:00:00Z", "CityName": "臺北市",
     "CaseTitle": "假投資詐騙",
     "Summary": "被害人於LINE認識自稱陳經理之人，下載超級發財APP並加入投資群組，"
                "陸續依指示匯款至台新銀行帳戶共15萬元，事後平台無法出金，對方即失聯。"},
    {"Id": "VLLM_SIM_002", "CaseDate": "2026-04-14T00:00:00Z", "CityName": "新北市",
     "CaseTitle": "假交友詐騙",
     "Summary": "一名網友自稱在國外工作，透過交友軟體認識後表示家人生病需要用錢，"
                "被害人陸續匯款，損失數萬元，後來對方即失去聯絡。"},
    {"Id": "VLLM_SIM_003", "CaseDate": "2026-04-15T00:00:00Z", "CityName": "桃園市",
     "CaseTitle": "可疑訊息通報",
     "Summary": "被害人收到一封來路不明的簡訊，內容空泛，並未點擊連結也未進一步互動，無財物損失。"},
    {"Id": "VLLM_SIM_004", "CaseDate": "2026-04-16T00:00:00Z", "CityName": "臺中市",
     "CaseTitle": "假網購詐騙",
     "Summary": "被害人於社群平台看到低價商品廣告，透過賣貨便平台完成付款3000元，"
                "賣家收款後未出貨並封鎖帳號。"},
    {"Id": "VLLM_SIM_005", "CaseDate": "2026-04-17T00:00:00Z", "CityName": "高雄市",
     "CaseTitle": "假檢警詐騙",
     "Summary": "自稱調查局王股長之人來電，宣稱被害人涉入洗錢案，需將帳戶資金轉入所謂"
                "安全帳戶接受監管，被害人依指示以ATM操作轉帳共80萬元，聯絡電話為0912345678。"},
]


# ── 關鍵字安全網（僅供本測試腳本使用，不寫回 tools.py）─────────────────────────
# 若摘要含這些字詞、但模型判斷 loss_amount==0 且 fuzzy_loss_text 為空，代表可能是
# 「有暗示財損但未量化」被誤判成無損失，標記出來供人工複核，而不是直接寫入正式庫。
_LOSS_HINT_KEYWORDS = [
    "匯款", "轉帳", "被騙", "詐騙", "盜刷", "損失", "扣款", "付款", "刷卡",
    "匯出", "交付", "騙走", "被騙走", "詐財", "款項", "索要", "詐取",
]


def flag_possible_missed_loss(summary: str, loss_amount: int, fuzzy_loss_text: str) -> bool:
    if loss_amount != 0 or fuzzy_loss_text.strip():
        return False
    return any(kw in summary for kw in _LOSS_HINT_KEYWORDS)


def discover_model(base_url: str, timeout: float = 5) -> str | None:
    try:
        resp = requests.get(f"{base_url}/models", timeout=timeout)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if data:
            return data[0]["id"]
    except Exception as e:
        print(f"⚠️ 無法自動偵測模型名稱（GET /models 失敗：{e}）")
    return None


def call_vllm(base_url: str, model: str, prompt: str, timeout: float = 60) -> tuple[str, dict, float]:
    """回傳 (內容, usage token 統計, 耗時秒數)。"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    t0 = time.perf_counter()
    try:
        payload_with_json_mode = {**payload, "response_format": {"type": "json_object"}}
        resp = requests.post(f"{base_url}/chat/completions", json=payload_with_json_mode, timeout=timeout)
        if resp.status_code >= 400:
            # 有些 vLLM/模型組合不支援 response_format，退回不帶這個參數重試
            resp = requests.post(f"{base_url}/chat/completions", json=payload, timeout=timeout)
        resp.raise_for_status()
        elapsed = time.perf_counter() - t0
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {}) or {}
        return content, usage, elapsed
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"呼叫 vLLM 失敗：{e}") from e


def extract_json(text: str) -> dict:
    """優先直接 json.loads；失敗則從文字中找出第一個 {...} 區塊再試一次。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def parse_item(item: dict) -> dict:
    return {
        "case_id": str(item.get("Id", "")),
        "date":    _normalize_date(item.get("CaseDate")),
        "city":    item.get("CityName") or "未知縣市",
        "title":   item.get("CaseTitle") or "無標題",
        "summary": item.get("Summary") or "無摘要",
    }


# 與 tools.py 的 fetch_page() 完全相同的真實 165 API 呼叫，獨立複製一份供本腳本使用。
_165_API_URL = "https://165dashboard.tw/CIB_DWS_API/api/CaseSummary/GetCaseSummaryList"
_165_API_HEADERS = {"Content-Type": "application/json", "Referer": "https://165dashboard.tw/"}


def fetch_real_165_cases(start_page: int, n_cases: int, max_pages: int = 20) -> list[dict]:
    """從 start_page 開始逐頁抓，直到湊滿 n_cases 筆「有實質摘要」的案件或抓完 max_pages 頁為止。"""
    collected: list[dict] = []
    page = start_page
    for _ in range(max_pages):
        if len(collected) >= n_cases:
            break
        payload = {
            "PageIndex": page, "NumberOfPerPage": 50,
            "SortOrderInfos": [{"SortField": "CaseDate", "SortOrder": "DESC"}],
            "UsingPaging": True,
        }
        resp = requests.post(_165_API_URL, headers=_165_API_HEADERS, json=payload, timeout=15)
        resp.raise_for_status()
        details = resp.json().get("body", {}).get("Detail", []) or []
        if not details:
            break
        # 只挑有實質摘要內容的案件，避免測到空白/過短摘要
        collected.extend(it for it in details if len(it.get("Summary") or "") > 20)
        page += 1
    return collected[:n_cases]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://192.168.1.101:8080/v1")
    parser.add_argument("--model", default=None, help="不指定則自動用 GET /models 偵測第一個")
    parser.add_argument("--synthetic", action="store_true",
                         help="使用腳本內建的合成範例，而非真實 165 即時資料")
    parser.add_argument("--page", type=int, default=1, help="165 API 的起始頁碼（真實資料模式用）")
    parser.add_argument("--n-cases", type=int, default=50, help="測試筆數")
    args = parser.parse_args()

    print(f"vLLM base_url: {args.base_url}")
    model = args.model or discover_model(args.base_url)
    if not model:
        print("❌ 未指定 --model 且自動偵測失敗，請確認 vLLM 服務是否啟動、位址是否正確，"
              "或手動加上 --model <名稱>。")
        sys.exit(1)
    print(f"使用模型：{model}\n")

    if args.synthetic:
        print("使用內建合成範例（--synthetic）。\n")
        test_items = TEST_CASES
    else:
        print(f"從 165 官方 API 抓取第 {args.page} 頁真實案件資料...")
        try:
            test_items = fetch_real_165_cases(args.page, args.n_cases)
            if not test_items:
                raise RuntimeError("該頁沒有符合條件（摘要長度 > 20）的案件")
            print(f"實際取得 {len(test_items)} 筆真實案件（來源：165dashboard.tw 即時 API）。\n")
        except Exception as e:
            print(f"⚠️ 抓取真實資料失敗（{e}），改用內建合成範例作為 fallback。\n")
            test_items = TEST_CASES

    tmp_dir = tempfile.mkdtemp(prefix="vllm_sim_")
    db_path = os.path.join(tmp_dir, "scam_records_vllm_sim.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS scam_cases (
            case_id TEXT PRIMARY KEY,
            date TEXT, city TEXT, title TEXT, summary TEXT,
            loss_amount INTEGER, fuzzy_loss_text TEXT,
            platforms TEXT, websites TEXT, scam_accounts TEXT, phone_numbers TEXT
        )
    ''')
    conn.commit()
    expected_columns = {"case_id", "date", "city", "title", "summary", "loss_amount",
                         "fuzzy_loss_text", "platforms", "websites", "scam_accounts", "phone_numbers"}

    n_ok, n_fail = 0, 0
    flagged_cases: list[str] = []
    latencies: list[float] = []
    completion_tokens_list: list[int] = []
    suite_t0 = time.perf_counter()

    for i, raw_item in enumerate(test_items, 1):
        case = parse_item(raw_item)
        prefix = f"[{i}/{len(test_items)}] {case['case_id']} | {case['city']} | {case['title']}"

        try:
            raw_output, usage, elapsed = call_vllm(args.base_url, model, BASE_PROMPT + case["summary"])
            latencies.append(elapsed)
            if usage.get("completion_tokens"):
                completion_tokens_list.append(usage["completion_tokens"])
        except RuntimeError as e:
            print(f"{prefix}\n  ❌ {e}\n  摘要：{case['summary']}\n")
            n_fail += 1
            continue

        try:
            parsed = extract_json(raw_output)
            record = ScamCaseRecord(**parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"{prefix}\n  ❌ 解析/schema 驗證失敗：{e}\n  vLLM 原始回應：{raw_output.strip()[:300]}\n"
                  f"  摘要：{case['summary']}\n")
            n_fail += 1
            continue

        final_platforms = _general_clean_entities(record.platforms, tw_converter)
        final_websites  = _general_clean_entities(record.websites, tw_converter)
        final_accounts  = _general_clean_entities(record.scam_accounts, tw_converter)
        final_phones    = _general_clean_phones(record.phone_numbers)
        fuzzy_loss_text = tw_converter.convert(record.fuzzy_loss_text).strip()

        try:
            conn.execute('''
                INSERT OR REPLACE INTO scam_cases
                (case_id, date, city, title, summary, loss_amount, fuzzy_loss_text,
                 platforms, websites, scam_accounts, phone_numbers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                case["case_id"], case["date"], case["city"], case["title"], case["summary"],
                record.loss_amount, fuzzy_loss_text,
                ", ".join(final_platforms), ", ".join(final_websites),
                ", ".join(final_accounts), ", ".join(final_phones),
            ))
            conn.commit()
        except Exception as e:
            print(f"{prefix}\n  ❌ INSERT 失敗：{e}\n")
            n_fail += 1
            continue

        row = conn.execute("SELECT * FROM scam_cases WHERE case_id=?", (case["case_id"],)).fetchone()
        cols = [d[0] for d in conn.execute("SELECT * FROM scam_cases LIMIT 0").description]
        result = dict(zip(cols, row))

        schema_ok = set(result.keys()) == expected_columns
        type_ok = isinstance(result["loss_amount"], int)
        flagged = flag_possible_missed_loss(case["summary"], record.loss_amount, fuzzy_loss_text)

        status = "✅" if (schema_ok and type_ok) else "❌"
        flag_str = "  ⚠️ 疑似漏判財損（關鍵字命中但 loss_amount=0 且 fuzzy_loss_text 為空）" if flagged else ""
        print(f"{prefix}  [{elapsed:.2f}s]  loss={record.loss_amount} fuzzy='{fuzzy_loss_text}' {status}{flag_str}")
        if flagged:
            flagged_cases.append(case["case_id"])
            print(f"  摘要：{case['summary']}\n  → 寫入結果：{result}\n")

        n_ok += 1 if (schema_ok and type_ok) else 0
        n_fail += 0 if (schema_ok and type_ok) else 1

    suite_elapsed = time.perf_counter() - suite_t0

    conn.close()
    os.remove(db_path)
    os.rmdir(tmp_dir)

    print("\n" + "=" * 60)
    print(f"完成：{n_ok} 筆通過 / {n_fail} 筆失敗（共 {len(test_items)} 筆）")
    print(f"⚠️ 關鍵字安全網命中 {len(flagged_cases)} 筆：{flagged_cases if flagged_cases else '無'}")

    if latencies:
        total_time = sum(latencies)
        avg_latency = total_time / len(latencies)
        print(f"\n--- {model} 速度統計 ---")
        print(f"整體耗時（含抓取165資料等）：{suite_elapsed:.2f} 秒")
        print(f"純模型呼叫總耗時：{total_time:.2f} 秒（{len(latencies)} 次呼叫）")
        print(f"平均延遲：{avg_latency:.2f} 秒/筆　最快：{min(latencies):.2f}s　最慢：{max(latencies):.2f}s")
        print(f"吞吐量：{len(latencies) / total_time:.2f} 筆/秒")
        if completion_tokens_list:
            avg_tokens = sum(completion_tokens_list) / len(completion_tokens_list)
            total_tokens = sum(completion_tokens_list)
            print(f"平均輸出 token 數：{avg_tokens:.1f} tokens/筆")
            print(f"輸出吞吐量：{total_tokens / total_time:.1f} tokens/秒")


if __name__ == "__main__":
    main()
