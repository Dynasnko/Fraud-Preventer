"""
[獨立測試腳本，不接入系統] 跟 test_vllm_165_extraction.py 做一樣的驗證，
但改成「併發」打 vLLM（多個請求同時送出），用來量測 Qwen3.8 在併發負載下
的實際吞吐量，跟循序（一次一筆）版本的結果互相對照。

依賴同一份 tools.py 純函式，不呼叫、不修改任何正式流程或正式資料庫。
所有 vLLM 呼叫在背景執行緒完成（I/O-bound，呼叫期間會釋放 GIL），
SQLite 寫入則統一放回主執行緒序列處理，避免多執行緒共用同一個連線。

用法：
    python dev_scripts/test_vllm_165_extraction_concurrent.py
    python dev_scripts/test_vllm_165_extraction_concurrent.py --concurrency 20 --n-cases 50
"""
import argparse
import concurrent.futures as cf
import json
import os
import sqlite3
import sys
import tempfile
import time

import requests
from pydantic import ValidationError

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from AllInOneProject.Agent.tools.tools import (
    ScamCaseRecord, _normalize_date, _general_clean_entities, _general_clean_phones,
)

# 直接複用循序版腳本裡的共用邏輯，避免兩份程式碼分岔。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_vllm_165_extraction import (
    BASE_PROMPT, discover_model, call_vllm, extract_json, parse_item,
    fetch_real_165_cases, flag_possible_missed_loss, TEST_CASES,
)

try:
    import opencc
    tw_converter = opencc.OpenCC('s2twp')
except ImportError:
    class _NoopConverter:
        def convert(self, s): return s
    tw_converter = _NoopConverter()


def call_and_parse(base_url: str, model: str, raw_item: dict) -> dict:
    case = parse_item(raw_item)
    try:
        raw_output, usage, elapsed = call_vllm(base_url, model, BASE_PROMPT + case["summary"], timeout=120)
    except RuntimeError as e:
        return {"case": case, "ok": False, "error": str(e), "elapsed": None}

    try:
        parsed = extract_json(raw_output)
        record = ScamCaseRecord(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        return {"case": case, "ok": False, "error": str(e), "raw": raw_output, "elapsed": elapsed}

    return {"case": case, "ok": True, "record": record, "usage": usage, "elapsed": elapsed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://192.168.1.101:8080/v1")
    parser.add_argument("--model", default=None)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--n-cases", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10, help="同時併發送出的請求數")
    args = parser.parse_args()

    print(f"vLLM base_url: {args.base_url}")
    model = args.model or discover_model(args.base_url)
    if not model:
        print("❌ 未指定 --model 且自動偵測失敗。")
        sys.exit(1)
    print(f"使用模型：{model}")
    print(f"併發數：{args.concurrency}\n")

    if args.synthetic:
        test_items = TEST_CASES
    else:
        print(f"從 165 官方 API 抓取第 {args.page} 頁起的真實案件資料...")
        try:
            test_items = fetch_real_165_cases(args.page, args.n_cases)
            if not test_items:
                raise RuntimeError("沒有符合條件的案件")
            print(f"實際取得 {len(test_items)} 筆真實案件。\n")
        except Exception as e:
            print(f"⚠️ 抓取真實資料失敗（{e}），改用內建合成範例。\n")
            test_items = TEST_CASES

    tmp_dir = tempfile.mkdtemp(prefix="vllm_sim_conc_")
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

    print(f"併發送出 {len(test_items)} 筆請求（concurrency={args.concurrency}）...\n")
    n_ok, n_fail = 0, 0
    flagged_cases: list[str] = []
    latencies: list[float] = []
    completion_tokens_list: list[int] = []
    done_count = 0

    suite_t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(call_and_parse, args.base_url, model, item) for item in test_items]
        for fut in cf.as_completed(futures):
            done_count += 1
            result = fut.result()
            case = result["case"]
            prefix = f"[{done_count}/{len(test_items)}] {case['case_id']} | {case['city']} | {case['title']}"

            if result["elapsed"] is not None:
                latencies.append(result["elapsed"])

            if not result["ok"]:
                print(f"{prefix}\n  ❌ {result['error']}\n")
                n_fail += 1
                continue

            record = result["record"]
            usage = result.get("usage") or {}
            if usage.get("completion_tokens"):
                completion_tokens_list.append(usage["completion_tokens"])

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
            db_result = dict(zip(cols, row))

            schema_ok = set(db_result.keys()) == expected_columns
            type_ok = isinstance(db_result["loss_amount"], int)
            flagged = flag_possible_missed_loss(case["summary"], record.loss_amount, fuzzy_loss_text)

            status = "✅" if (schema_ok and type_ok) else "❌"
            flag_str = "  ⚠️ 疑似漏判財損" if flagged else ""
            print(f"{prefix}  [{result['elapsed']:.2f}s]  loss={record.loss_amount} "
                  f"fuzzy='{fuzzy_loss_text}' {status}{flag_str}")
            if flagged:
                flagged_cases.append(case["case_id"])

            n_ok += 1 if (schema_ok and type_ok) else 0
            n_fail += 0 if (schema_ok and type_ok) else 1

    suite_elapsed = time.perf_counter() - suite_t0

    conn.close()
    os.remove(db_path)
    os.rmdir(tmp_dir)

    print("\n" + "=" * 60)
    print(f"完成：{n_ok} 筆通過 / {n_fail} 筆失敗（共 {len(test_items)} 筆，concurrency={args.concurrency}）")
    print(f"⚠️ 關鍵字安全網命中 {len(flagged_cases)} 筆：{flagged_cases if flagged_cases else '無'}")

    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        print(f"\n--- {model} 併發速度統計（concurrency={args.concurrency}）---")
        print(f"整體 wall-clock 時間：{suite_elapsed:.2f} 秒（{len(test_items)} 筆請求同時送出）")
        print(f"平均單筆延遲：{avg_latency:.2f} 秒　最快：{min(latencies):.2f}s　最慢：{max(latencies):.2f}s")
        print(f"實際吞吐量（wall-clock 為準）：{len(test_items) / suite_elapsed:.2f} 筆/秒")
        if completion_tokens_list:
            total_tokens = sum(completion_tokens_list)
            print(f"輸出 token 總數：{total_tokens}　輸出吞吐量：{total_tokens / suite_elapsed:.1f} tokens/秒")
        print(f"\n（對照：循序版本約 0.12 筆/秒、68 tokens/秒 —— "
              f"併發 {args.concurrency} 的加速倍率 ≈ {(len(test_items) / suite_elapsed) / 0.12:.1f}x）")


if __name__ == "__main__":
    main()
