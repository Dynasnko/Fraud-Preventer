"""
模擬 165 同步管線：不呼叫真正的 Ollama（本機未安裝/未啟動），改用手動建構的
ScamCaseRecord 假資料（代表 LLM 可能回傳的各種情況，含邊界案例），
接上 tools.py 裡「真正」的清洗函式與 INSERT 邏輯，驗證：

1. 欄位是否跟 scam_cases 資料表 schema 對得上（型別、欄位數）
2. 清洗函式（_general_clean_entities / _general_clean_phones）對各種輸入的行為
3. 實際 INSERT OR REPLACE 進 SQLite 後，讀回來的值是否符合預期

用法：
    python dev_scripts/simulate_165_sync_pipeline.py

寫入獨立的暫存 DB（不會動到正式的 scam_records.sqlite3），結束後自動刪除。
"""
import os
import sqlite3
import sys
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from AllInOneProject.Agent.tools.tools import (
    ScamCaseRecord, _normalize_date, _general_clean_entities, _general_clean_phones,
)

try:
    import opencc
    tw_converter = opencc.OpenCC('s2twp')
except ImportError:
    print("❌ 缺少 opencc，無法完整模擬（正式流程也依賴它）。")
    sys.exit(1)


# 模擬情境：(case 說明, 原始 165 API item, 假設 Ollama 回傳的 ScamCaseRecord)
SCENARIOS = [
    (
        "一般案例：金額明確 + 平台/帳號/電話齊全",
        {"Id": "SIM001", "CaseDate": "2026-04-13T00:00:00Z", "CityName": "臺北市",
         "CaseTitle": "假投資詐騙", "Summary": "被害人於LINE認識自稱陳經理之人，下載超級發財APP，匯款至台新銀行帳戶，損失15000元。"},
        ScamCaseRecord(loss_amount=15000, fuzzy_loss_text="", platforms=["超級發財APP"],
                        websites=[], phone_numbers=["0911222333"], scam_accounts=["陳經理", "台新銀行帳戶"]),
    ),
    (
        "邊界案例：只有模糊損失描述，無法換算精確金額",
        {"Id": "SIM002", "CaseDate": "2026-04-14T00:00:00Z", "CityName": "新北市",
         "CaseTitle": "假交友詐騙", "Summary": "一名女網友說她家人生病需要錢，我陸續匯款給她，損失數萬元，後來她就消失了。"},
        ScamCaseRecord(loss_amount=0, fuzzy_loss_text="損失數萬元", platforms=[], websites=[],
                        phone_numbers=[], scam_accounts=[]),
    ),
    (
        "邊界案例：完全沒有可萃取實體（全空列表）",
        {"Id": "SIM003", "CaseDate": "2026-04-15T00:00:00Z", "CityName": "桃園市",
         "CaseTitle": "可疑訊息通報", "Summary": "收到一則不明簡訊，內容空泛未進一步互動，無損失。"},
        ScamCaseRecord(loss_amount=0, fuzzy_loss_text="", platforms=[], websites=[],
                        phone_numbers=[], scam_accounts=[]),
    ),
    (
        "邊界案例：LLM 萃取到雜訊實體（通用稱呼/過長字串），應被 _general_clean_entities 過濾",
        {"Id": "SIM004", "CaseDate": "2026-04-16T00:00:00Z", "CityName": "臺中市",
         "CaseTitle": "假網購詐騙", "Summary": "在網路上被網友以優惠價誘導，透過賣貨便平台下單，事後未出貨，損失3000元。"},
        ScamCaseRecord(
            loss_amount=3000, fuzzy_loss_text="", platforms=["賣貨便", "網友"],  # "網友"應被過濾
            websites=[], phone_numbers=["abc-123"],  # 非數字電話，應被過濾
            scam_accounts=["這是一段超過二十個字而且完全不含任何數字的化名描述文字用來測試長度過濾規則"],  # 應被過濾
        ),
    ),
    (
        "邊界案例：多筆平台/帳號/電話，且含全形字元與空白，測試 join 與清洗",
        {"Id": "SIM005", "CaseDate": "2026-04-17T00:00:00Z", "CityName": "高雄市",
         "CaseTitle": "假檢警詐騙", "Summary": "自稱調查局人員來電，要求監管帳戶，並提供多個帳戶與電話。"},
        ScamCaseRecord(
            loss_amount=800000, fuzzy_loss_text="",
            platforms=["  網銀APP  ", "ATM"],
            websites=["www.fake-gov.com", "www.fake-gov.com"],  # 重複值，應被去重
            phone_numbers=["02-1234-5678", "0911", "0922333444"],  # "0911" 太短應被過濾
            scam_accounts=["王股長", "調查局科員"],
        ),
    ),
]


def parse_item(item: dict) -> dict:
    """完全複製 tools.py 的 parse_item 邏輯，確保跟正式流程一致。"""
    return {
        "case_id": str(item.get("Id", "")),
        "date":    _normalize_date(item.get("CaseDate")),
        "city":    item.get("CityName") or "未知縣市",
        "title":   item.get("CaseTitle") or "無標題",
        "summary": item.get("Summary") or "無摘要",
    }


def main():
    tmp_dir = tempfile.mkdtemp(prefix="sim_165_")
    db_path = os.path.join(tmp_dir, "scam_records_sim.sqlite3")
    print(f"暫存測試 DB：{db_path}\n")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # 與 tools.py 完全一致的 schema
    cursor.execute('''
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

    all_passed = True
    for label, raw_item, cleaned_data in SCENARIOS:
        print(f"=== {label} ===")
        case = parse_item(raw_item)

        final_platforms = _general_clean_entities(cleaned_data.platforms, tw_converter)
        final_websites  = _general_clean_entities(cleaned_data.websites, tw_converter)
        final_accounts  = _general_clean_entities(cleaned_data.scam_accounts, tw_converter)
        final_phones    = _general_clean_phones(cleaned_data.phone_numbers)
        fuzzy_loss_text = tw_converter.convert(cleaned_data.fuzzy_loss_text).strip()

        print(f"  原始 LLM 輸出：platforms={cleaned_data.platforms} websites={cleaned_data.websites} "
              f"phones={cleaned_data.phone_numbers} accounts={cleaned_data.scam_accounts}")
        print(f"  清洗後      ：platforms={final_platforms} websites={final_websites} "
              f"phones={final_phones} accounts={final_accounts}")

        try:
            cursor.execute('''
                INSERT OR REPLACE INTO scam_cases
                (case_id, date, city, title, summary, loss_amount, fuzzy_loss_text,
                 platforms, websites, scam_accounts, phone_numbers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                case["case_id"], case["date"], case["city"], case["title"], case["summary"],
                cleaned_data.loss_amount, fuzzy_loss_text,
                ", ".join(final_platforms), ", ".join(final_websites),
                ", ".join(final_accounts), ", ".join(final_phones),
            ))
            conn.commit()
        except Exception as e:
            print(f"  ❌ INSERT 失敗：{e}")
            all_passed = False
            continue

        row = conn.execute("SELECT * FROM scam_cases WHERE case_id=?", (case["case_id"],)).fetchone()
        cols = [d[0] for d in conn.execute("SELECT * FROM scam_cases LIMIT 0").description]
        result = dict(zip(cols, row))

        checks = []
        checks.append(("欄位集合與 schema 完全一致", set(result.keys()) == expected_columns))
        checks.append(("loss_amount 是 int", isinstance(result["loss_amount"], int)))
        checks.append(("case_id 正確寫回", result["case_id"] == case["case_id"]))
        checks.append(("date 已轉換為 YYYY-MM-DD 格式", len(result["date"]) == 10 and result["date"].count("-") == 2))

        ok = all(c[1] for c in checks)
        all_passed = all_passed and ok
        for desc, passed in checks:
            print(f"  {'✅' if passed else '❌'} {desc}")
        print(f"  → 讀回結果：{result}\n")

    conn.close()
    os.remove(db_path)
    os.rmdir(tmp_dir)

    print("=" * 60)
    if all_passed:
        print("✅ 全部情境通過：清洗函式輸出的欄位型別、數量都符合 scam_cases schema，INSERT/讀回一致。")
    else:
        print("❌ 有情境未通過，請往上檢查標記 ❌ 的項目。")


if __name__ == "__main__":
    main()
