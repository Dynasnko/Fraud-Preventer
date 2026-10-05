"""
[獨立測試腳本，不接入系統] 對同一批真實 165 案件資料，依序用不同的併發數
（1/3/5/10/20）打同一顆 vLLM，找出吞吐量/延遲/失敗率的甜蜜點。

只抓一次 165 真實資料，所有併發等級都用同一批案例測，確保比較公平
（165 是即時 API，資料會一直變動，分開抓會導致每個併發等級測到的內容不同）。

用法：
    python dev_scripts/test_vllm_165_concurrency_sweep.py
    python dev_scripts/test_vllm_165_concurrency_sweep.py --n-cases 20 --levels 1 3 5 10 20
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
import time

from pydantic import ValidationError

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from AllInOneProject.Agent.tools.tools import ScamCaseRecord
from test_vllm_165_extraction import (
    BASE_PROMPT, discover_model, call_vllm, extract_json, parse_item,
    fetch_real_165_cases, flag_possible_missed_loss, TEST_CASES,
)


def call_and_parse(base_url: str, model: str, raw_item: dict) -> dict:
    case = parse_item(raw_item)
    try:
        raw_output, usage, elapsed = call_vllm(base_url, model, BASE_PROMPT + case["summary"], timeout=180)
    except RuntimeError as e:
        return {"case": case, "ok": False, "error": str(e), "elapsed": None}
    try:
        parsed = extract_json(raw_output)
        record = ScamCaseRecord(**parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        return {"case": case, "ok": False, "error": str(e), "elapsed": elapsed}
    flagged = flag_possible_missed_loss(case["summary"], record.loss_amount, record.fuzzy_loss_text)
    usage = usage or {}
    return {"case": case, "ok": True, "elapsed": elapsed,
            "completion_tokens": usage.get("completion_tokens"), "flagged": flagged}


def run_one_level(base_url: str, model: str, items: list[dict], concurrency: int) -> dict:
    print(f"\n{'='*60}\n併發數 = {concurrency}（{len(items)} 筆請求）\n{'='*60}")
    n_ok, n_fail, n_flagged = 0, 0, 0
    latencies: list[float] = []
    tokens: list[int] = []
    done = 0

    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(call_and_parse, base_url, model, item) for item in items]
        for fut in cf.as_completed(futures):
            done += 1
            r = fut.result()
            if r["elapsed"] is not None:
                latencies.append(r["elapsed"])
            if not r["ok"]:
                n_fail += 1
                print(f"  [{done}/{len(items)}] {r['case']['case_id']} ❌ {r['error']}")
                continue
            n_ok += 1
            if r.get("completion_tokens"):
                tokens.append(r["completion_tokens"])
            if r.get("flagged"):
                n_flagged += 1
    wall = time.perf_counter() - t0

    print(f"完成：{n_ok} 成功 / {n_fail} 失敗，wall-clock = {wall:.2f}s")

    return {
        "concurrency": concurrency, "wall": wall, "n_ok": n_ok, "n_fail": n_fail,
        "n_flagged": n_flagged, "latencies": latencies, "tokens": tokens,
        "n_total": len(items),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://192.168.1.101:8080/v1")
    parser.add_argument("--model", default=None)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--n-cases", type=int, default=20)
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 3, 5, 10, 20])
    args = parser.parse_args()

    print(f"vLLM base_url: {args.base_url}")
    model = args.model or discover_model(args.base_url)
    if not model:
        print("❌ 未指定 --model 且自動偵測失敗。")
        sys.exit(1)
    print(f"使用模型：{model}")
    print(f"測試併發數：{args.levels}")

    if args.synthetic:
        items = TEST_CASES
    else:
        print(f"從 165 官方 API 抓取 {args.n_cases} 筆真實案件（僅抓一次，所有併發等級共用同一批）...")
        try:
            items = fetch_real_165_cases(args.page, args.n_cases)
            if not items:
                raise RuntimeError("沒有符合條件的案件")
        except Exception as e:
            print(f"⚠️ 抓取真實資料失敗（{e}），改用內建合成範例。")
            items = TEST_CASES
    print(f"共 {len(items)} 筆測試資料，所有併發等級都用這批同樣的資料。")

    results = []
    for level in args.levels:
        results.append(run_one_level(args.base_url, model, items, level))

    print("\n\n" + "#" * 70)
    print("# 併發數 vs 速度總表")
    print("#" * 70)
    header = f"{'併發數':>6} | {'wall-clock':>10} | {'吞吐量(筆/秒)':>13} | {'平均延遲':>8} | {'最慢延遲':>8} | {'失敗數':>6} | {'加速倍率':>8}"
    print(header)
    print("-" * len(header))

    baseline_throughput = None
    for r in results:
        throughput = r["n_ok"] / r["wall"] if r["wall"] > 0 else 0
        if r["concurrency"] == 1 or baseline_throughput is None:
            baseline_throughput = throughput if r["concurrency"] == 1 else baseline_throughput
        avg_lat = sum(r["latencies"]) / len(r["latencies"]) if r["latencies"] else 0
        max_lat = max(r["latencies"]) if r["latencies"] else 0
        speedup = (throughput / baseline_throughput) if baseline_throughput else 1.0
        print(f"{r['concurrency']:>6} | {r['wall']:>9.2f}s | {throughput:>13.3f} | {avg_lat:>7.2f}s | "
              f"{max_lat:>7.2f}s | {r['n_fail']:>6} | {speedup:>7.2f}x")

    print("\n各併發數的關鍵字安全網命中數：" +
          ", ".join(f"併發{r['concurrency']}={r['n_flagged']}" for r in results))


if __name__ == "__main__":
    main()
