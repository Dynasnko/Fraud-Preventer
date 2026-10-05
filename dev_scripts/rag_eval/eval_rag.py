"""
RAG 檢索篩選評測（對應 dev_scripts/rag_eval/questions.json）。

  python dev_scripts/rag_eval/eval_rag.py collect   # 以真實向量庫查詢，結果存到 cache.json（CPU embedding，不影響執行中的系統）
  python dev_scripts/rag_eval/eval_rag.py report    # 用 cache.json 比較各篩選策略（不需重新查詢）
  python dev_scripts/rag_eval/eval_rag.py e2e       # 用真實 Gemini 跑 WorkerNode，檢查回答關鍵字與依據等級（會消耗 token）

指標：
  - 正例命中率：採用的片段中至少有一個是標準答案
  - 不相關題誤用率：知識庫沒有答案的題目卻採用了本地片段（越低越好）
  - 平均採用數 / 精確率：採用的片段有多少是標準答案
"""
import json
import os
import sys
from functools import lru_cache

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from AllInOneProject.Model.config import RAG_ROOT_DIR, DB_PERSIST_ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "questions.json")
CACHE = os.path.join(HERE, "cache.json")
K_DIAG = 30


def load_questions():
    with open(QUESTIONS, encoding="utf-8") as f:
        return json.load(f)["questions"]


@lru_cache(maxsize=None)
def _case_title(source: str) -> str:
    try:
        with open(os.path.join(RAG_ROOT_DIR, source), encoding="utf-8") as f:
            for line in f:
                if "案件標題：" in line:
                    return line.split("案件標題：", 1)[1].strip()
    except OSError:
        pass
    return ""


def is_gold(q, source: str, content: str) -> bool:
    g = q.get("gold") or {}
    if "contains" in g and any(s in content for s in g["contains"]):
        return True
    if "case_title" in g and any(s in _case_title(source) for s in g["case_title"]):
        return True
    if "source" in g and "case_title" not in g and source in g["source"]:
        return True
    return False


def _open_store(worker, emb):
    persist = os.path.join(DB_PERSIST_ROOT, worker)
    if worker == "防詐騙專家":
        from AllInOneProject.Agent.faiss_rag_store import FaissRAGStore
        return FaissRAGStore(persist, emb)
    from langchain_chroma import Chroma
    return Chroma(persist_directory=persist, embedding_function=emb)


def collect():
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # 用 CPU，避免和執行中的系統搶 GPU
    import AllInOneProject.Agent.rag_builder as rb
    emb = rb.MultiAgentRAGBuilder()._get_embeddings()
    stores, out = {}, {}
    for q in load_questions():
        w = q["worker"]
        if w not in stores:
            stores[w] = _open_store(w, emb)
        st = stores[w]
        docs = st.similarity_search_with_score(q["question"], k=K_DIAG)
        out[q["id"]] = {
            "db_size": st._collection.count(),
            "results": [
                {"dist": float(s), "source": d.metadata.get("source", ""), "gold": is_gold(q, d.metadata.get("source", ""), d.page_content),
                 "exact": d.metadata.get("source", "") in (q.get("gold") or {}).get("source", []),
                 "preview": d.page_content[:40].replace("\n", " ")}
                for d, s in docs
            ],
        }
        top = out[q["id"]]["results"][0]
        print(f"  {q['id']:10s} best={top['dist']:.3f} gold@1={top['gold']}")
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"已寫入 {CACHE}")


def k_for(db_size: int) -> int:  # 與 WorkerNode 相同
    return 15 if db_size > 10000 else 10 if db_size > 1000 else 5


def evaluate(policy, cache, questions):
    """policy(results[k]) -> (used_results, mode)；mode ∈ local / local+web / web"""
    pos = [q for q in questions if q["type"] == "positive"]
    neg = [q for q in questions if q["type"] == "negative"]
    hit, exact_hit, used_n, gold_n, modes, rows = 0, 0, 0, 0, {}, []
    for q in pos:
        c = cache[q["id"]]
        used, mode = policy(c["results"][:k_for(c["db_size"])])
        h = any(r["gold"] for r in used)
        hit += h
        exact_hit += any(r["exact"] for r in used)
        used_n += len(used)
        gold_n += sum(r["gold"] for r in used)
        modes[mode] = modes.get(mode, 0) + 1
        rows.append((q["id"], h, len(used), mode))
    false_use = 0
    for q in neg:
        c = cache[q["id"]]
        used, mode = policy(c["results"][:k_for(c["db_size"])])
        false_use += bool(used)
        rows.append((q["id"], not used, len(used), mode))
    return {
        "hit": f"{hit}/{len(pos)}",
        "exact": f"{exact_hit}/{sum(1 for q in pos if 'source' in (q.get('gold') or {}))}",
        "false_use": f"{false_use}/{len(neg)}",
        "avg_used": round(used_n / len(pos), 1),
        "precision": round(gold_n / used_n, 2) if used_n else 0,
        "modes": modes,
        "rows": rows,
    }


# ── 候選策略 ────────────────────────────────────────────────────────────
def current_policy(results, threshold=0.7):
    """現行 WorkerNode：dist < 0.7（二次過濾 0.85/0.9 比 0.7 寬鬆，實際無作用）；全無則改網路"""
    used = [r for r in results if r["dist"] < threshold]
    return used, ("local" if used else "web")


def absolute(t):
    return lambda res: current_policy(res, t)


def relative(strong, weak, margin):
    """best < strong → 只用本地；strong ≤ best < weak → 本地 + 網路；其餘只用網路。
    採用 dist < min(best + margin, weak) 的片段。"""
    def pol(res):
        if not res:
            return [], "web"
        best = res[0]["dist"]
        if best >= weak:
            return [], "web"
        used = [r for r in res if r["dist"] < min(best + margin, weak)]
        return used, ("local" if best < strong else "local+web")
    return pol


def report():
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)
    qs = load_questions()

    print("\n=== 距離分布（每題最佳距離 / 第一個標準答案的名次與距離）")
    for q in qs:
        res = cache[q["id"]]["results"]
        gi = next((i for i, r in enumerate(res) if r["gold"]), None)
        g = f"gold#{gi + 1} {res[gi]['dist']:.3f}" if gi is not None else "gold 不在前 30"
        print(f"  {q['id']:10s} {q['type']:8s} best={res[0]['dist']:.3f}  {g if q['type'] == 'positive' else ''}")

    policies = {"現行 <0.70": current_policy}
    for t in (0.75, 0.80, 0.85):
        policies[f"絕對 <{t:.2f}"] = absolute(t)
    for strong, weak, margin in ((0.70, 0.85, 0.10), (0.70, 0.85, 0.15), (0.75, 0.90, 0.10), (0.70, 0.90, 0.15)):
        policies[f"相對 強{strong}/弱{weak}/差{margin}"] = relative(strong, weak, margin)
    try:
        from AllInOneProject.Agent.worker import select_rag_docs
        def _impl(res):
            used, mode = select_rag_docs([(r, r["dist"]) for r in res])
            return [r for r, _ in used], mode
        policies["worker.select_rag_docs（實作）"] = _impl
    except ImportError:
        pass

    print("\n=== 策略比較（正例命中 / 精準題命中 / 不相關題誤用 / 平均採用數 / 精確率 / 模式分布）")
    for name, pol in policies.items():
        r = evaluate(pol, cache, qs)
        print(f"  {name:34s} 命中 {r['hit']:6s} 精準 {r['exact']:4s} 誤用 {r['false_use']:4s} "
              f"採用 {r['avg_used']:4} 精確 {r['precision']:.2f}  {r['modes']}")
    return policies, cache, qs


def e2e(ids=None):
    """真實 Gemini + 真實向量庫跑 WorkerNode，檢查回答關鍵字與依據等級。"""
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, "AllInOneProject", ".env"))
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    import AllInOneProject.Agent.rag_builder as rb
    import AllInOneProject.Agent.worker as wmod
    emb = rb.MultiAgentRAGBuilder()._get_embeddings()
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    nodes, ok_n, total = {}, 0, 0
    for q in load_questions():
        if q["type"] != "positive" or not q.get("answer_keywords") or (ids and q["id"] not in ids):
            continue
        w = q["worker"]
        if w not in nodes:
            nodes[w] = wmod.WorkerNode(f"worker_{w}", llm=llm, db=_open_store(w, emb), tools=[], description="")
        state = {"variables": {"tasks_to_execute": [{"worker_id": f"worker_{w}", "query": q["question"]}]},
                 "messages": [HumanMessage(content=q["question"])]}
        out = nodes[w].execute(state)["worker_results"][0]
        # 每個關鍵字可為字串或「任一皆可」的清單（例如 ["339-4", "339條之4"]）
        def _has(k):
            return any(x in out["content"] for x in ([k] if isinstance(k, str) else k))
        missing = [k for k in q["answer_keywords"] if not _has(k)]
        ok = not missing
        ok_n += ok
        total += 1
        rag = (out.get("trace") or {}).get("rag") or {}
        print(f"  {'✅' if ok else '❌'} {q['id']:10s} 依據={out['grounding']['level']:10s} "
              f"本地採用={len(rag.get('used', []))} 網路={len((out.get('trace') or {}).get('web', []))}  "
              f"缺少關鍵字={missing}")
    print(f"\n回答正確（含全部關鍵字）：{ok_n}/{total}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "collect":
        collect()
    elif cmd == "report":
        report()
    elif cmd == "e2e":
        e2e(set(sys.argv[2:]) or None)
    else:
        print(__doc__)
