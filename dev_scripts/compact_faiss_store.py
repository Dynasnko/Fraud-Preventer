"""
一次性整理大型 FAISS 向量庫（預設：防詐騙專家、_merged）。

背景
----
舊版 rag_builder 以「絕對路徑」作為向量的 source key。專案曾從 Windows 搬到
TestingProject0429、再搬到目前目錄，每次路徑改變都讓增量更新把所有檔案當成新檔
重新 embed，舊路徑的向量又從未清除，導致同一批內容存了三份。

本腳本做的事（不呼叫 embedding 模型）
------------------------------------
  1. 只保留 source 指向「目前 rag_docs/ 底下、且檔案仍存在」的列；
     丟棄：已 tombstone 的列、舊專案 / Windows 路徑、檔案已不存在、同一檔案的重複來源。
  2. source 欄位與 meta JSON 內的 source 改寫為相對於 rag_docs/ 的 key（以 / 分隔），
     與新版 rag_builder._source_key() 一致。
  3. 依原 rowid 順序寫入新的 SQLite（rowid 重新連號），再由 SQLite 重建 HNSW 索引。
  4. 逐項驗證（筆數、rowid 連續、key 合法、抽樣比對內容與向量、抽樣搜尋）。
  5. 所有庫都驗證通過後才替換：原目錄更名為 <name>.bak_<時間戳> 保留。

安全性
------
  - 預設 dry-run，只輸出統計；加 --apply 才寫入。
  - 偵測到系統（port 8081）仍在執行則拒絕執行。
  - 替換前任一步驟失敗都不會動到原資料；暫存目錄 <name>.compact_tmp 可直接刪除。
  - 還原：刪除（或更名）新目錄，把 <name>.bak_<時間戳> 改回 <name>。

用法（在 MyBigProject/ 目錄下，先停止 main.py）
----
  python dev_scripts/compact_faiss_store.py             # dry-run，只看統計
  python dev_scripts/compact_faiss_store.py --apply     # 實際執行
"""

import argparse
import json
import os
import random
import shutil
import socket
import sqlite3
import sys
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from AllInOneProject.Model.config import RAG_ROOT_DIR, DB_PERSIST_ROOT
from AllInOneProject.Agent.faiss_rag_store import FaissRAGStore

DEFAULT_STORES = ["防詐騙專家", "_merged"]
_FOLD = str.lower if os.name == "nt" else (lambda s: s)  # Windows 檔名不分大小寫
_BATCH = 5_000
_SAMPLE = 300


def _is_legacy(source: str) -> bool:
    import re
    return os.path.isabs(source) or bool(re.match(r"^([A-Za-z]:)?[\\/]", source))


def _disk_keys(rag_root: str) -> Dict[str, str]:
    """磁碟上所有知識檔案：fold(key) → key（實際大小寫），key 算法同 rag_builder._source_key。

    與 rag_builder 相同，只計入 <Worker>/Domain_Knowledge/ 底下的檔案。
    """
    keys: Dict[str, str] = {}
    root_abs = os.path.abspath(rag_root)
    for worker in os.listdir(root_abs):
        data_path = os.path.join(root_abs, worker, "Domain_Knowledge")
        for root, _, files in os.walk(data_path):
            for f in files:
                k = os.path.relpath(os.path.join(root, f), root_abs).replace(os.sep, "/")
                keys[_FOLD(k)] = k
    return keys


def _resolve_key(source: str, root_abs: str, disk_keys: Dict[str, str]) -> Tuple[Optional[str], str]:
    """把資料庫中的 source 對應到目前磁碟上的 key。回傳 (key 或 None, 丟棄原因)。"""
    if _is_legacy(source):
        a = os.path.abspath(source)
        try:
            under_root = os.path.commonpath([_FOLD(a), _FOLD(root_abs)]) == _FOLD(root_abs)
        except ValueError:  # Windows 不同磁碟機
            under_root = False
        if not under_root:
            return None, "舊專案或其他路徑"
        cand = os.path.relpath(a, root_abs).replace(os.sep, "/")
    else:
        cand = source
    key = disk_keys.get(_FOLD(cand))
    if key is None:
        return None, "檔案已不存在"
    return key, ""


def _scan(db_path: str, root_abs: str, disk_keys: Dict[str, str]):
    """第一遍：只讀 source / deleted，決定每個 source 的去留。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(vectors)")}
        del_expr = "deleted" if "deleted" in cols else "0"
        total = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        rows_by_source = Counter()
        tomb = 0
        for source, deleted, n in conn.execute(
            f"SELECT source, {del_expr}, COUNT(*) FROM vectors GROUP BY source, {del_expr}"
        ):
            if deleted:
                tomb += n
            else:
                rows_by_source[source] += n
    finally:
        conn.close()

    source_map: Dict[str, str] = {}    # 保留的原 source → 新 key
    key_owner: Dict[str, str] = {}     # 新 key → 取得它的原 source（避免同檔案兩份）
    dropped = Counter()
    dropped_examples: Dict[str, str] = {}
    # 以「本來就是相對 key」或目前路徑優先取得 key，排序確保結果穩定
    for source in sorted(rows_by_source, key=lambda s: (_is_legacy(s), s)):
        key, reason = _resolve_key(source, root_abs, disk_keys)
        if key is not None and key in key_owner:
            key, reason = None, "同一檔案的重複來源"
        if key is None:
            dropped[reason] += rows_by_source[source]
            dropped_examples.setdefault(reason, source)
            continue
        key_owner[key] = source
        source_map[source] = key
    kept = sum(rows_by_source[s] for s in source_map)
    return {
        "total": total, "tomb": tomb, "kept": kept, "dropped": dropped,
        "dropped_examples": dropped_examples, "source_map": source_map,
        "del_expr": del_expr,
    }


def _prefix_summary(sources) -> Counter:
    c = Counter()
    for s in sources:
        i = s.lower().find("rag_docs")
        c[s[:i] if (i >= 0 and _is_legacy(s)) else "(相對路徑 key)"] += 1
    return c


def _build_tmp(name: str, db_path: str, tmp_dir: str, plan) -> None:
    """第二遍：串流複製保留的列到新 SQLite，再重建 HNSW。"""
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)
    FaissRAGStore(tmp_dir, None)  # 只為了用同一份 schema 建立空的 vectors 表

    source_map = plan["source_map"]
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(os.path.join(tmp_dir, "vectors.sqlite3"))
    written = 0
    t0 = time.time()
    try:
        cur = src.execute(
            f"SELECT id, source, content, meta, vec, {plan['del_expr']}"
            f" FROM vectors ORDER BY rowid"
        )
        while True:
            rows = cur.fetchmany(_BATCH)
            if not rows:
                break
            out = []
            for rid, source, content, meta, vec, deleted in rows:
                if deleted or source not in source_map:
                    continue
                key = source_map[source]
                m = json.loads(meta)
                m["source"] = key
                out.append((rid, key, content, json.dumps(m, ensure_ascii=False), vec))
            if out:
                dst.executemany(
                    "INSERT INTO vectors (id, source, content, meta, vec, deleted)"
                    " VALUES (?, ?, ?, ?, ?, 0)",
                    out,
                )
                written += len(out)
            if written and written % 50_000 < len(out):
                dst.commit()
                print(f"    📝 [{name}] 已寫入 {written:,}/{plan['kept']:,}（{time.time()-t0:.0f}s）", flush=True)
        dst.commit()
    finally:
        src.close()
        dst.close()
    print(f"    📝 [{name}] 寫入完成 {written:,} 筆（{time.time()-t0:.0f}s）")

    # 由新 SQLite 重建 HNSW（與 FaissRAGStore 啟動時的重建路徑相同，不呼叫 embedding）
    store = FaissRAGStore(tmp_dir, None)
    store._rebuild_from_db()


def _verify(name: str, db_path: str, tmp_dir: str, plan, disk_keys: Dict[str, str]) -> None:
    """任何一項不符即 raise，替換不會發生。"""
    new_db = os.path.join(tmp_dir, "vectors.sqlite3")
    conn = sqlite3.connect(f"file:{new_db}?mode=ro", uri=True)
    old = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        n, max_rowid = conn.execute("SELECT COUNT(*), MAX(rowid) FROM vectors").fetchone()
        assert n == plan["kept"], f"筆數不符：新 {n} vs 預期 {plan['kept']}"
        assert max_rowid == n, f"rowid 不連續：MAX(rowid)={max_rowid}, COUNT={n}"
        assert conn.execute("SELECT COUNT(*) FROM vectors WHERE deleted != 0").fetchone()[0] == 0

        keys = {r[0] for r in conn.execute("SELECT DISTINCT source FROM vectors")}
        assert keys == set(plan["source_map"].values()), "新庫的 source 集合與預期不符"
        valid = set(disk_keys.values())
        bad = [k for k in keys if _is_legacy(k) or k not in valid]
        assert not bad, f"有 {len(bad)} 個 source 不是合法的相對 key，例如 {bad[:3]}"

        # 抽樣：內容與向量需與原庫同一 id 的列完全相同，meta.source 需等於新 key
        sample_ids = random.sample(range(1, n + 1), min(_SAMPLE, n))
        for rowid in sample_ids:
            rid, source, content, meta, vec = conn.execute(
                "SELECT id, source, content, meta, vec FROM vectors WHERE rowid = ?", (rowid,)
            ).fetchone()
            o = old.execute(
                "SELECT source, content, vec FROM vectors WHERE id = ?", (rid,)
            ).fetchone()
            assert o is not None, f"id {rid} 在原庫中不存在"
            assert o[1] == content and o[2] == vec, f"id {rid} 內容或向量不一致"
            assert plan["source_map"][o[0]] == source, f"id {rid} source 對應錯誤"
            assert json.loads(meta)["source"] == source, f"id {rid} meta.source 未改寫"
    finally:
        conn.close()
        old.close()

    # 索引：重新從磁碟載入，筆數需與 SQLite 一致；抽樣向量搜尋 top1 距離需為 0
    store = FaissRAGStore(tmp_dir, None)
    idx = store._ensure_index()
    assert idx.ntotal == n, f"索引筆數 {idx.ntotal} 與 SQLite {n} 不符"
    conn = sqlite3.connect(f"file:{new_db}?mode=ro", uri=True)
    try:
        vecs = np.array([
            np.frombuffer(conn.execute("SELECT vec FROM vectors WHERE rowid = ?", (r,)).fetchone()[0], dtype=np.float32)
            for r in sample_ids
        ])
    finally:
        conn.close()
    dists, ids = idx.search(vecs, 1)
    exact = sum(1 for r, i in zip(sample_ids, ids[:, 0]) if i + 1 == r)
    near_zero = int((dists[:, 0] < 1e-4).sum())
    # HNSW 為近似搜尋，自我查詢偶有漏網；索引若錯位，命中率會趨近 0
    assert near_zero >= 0.95 * len(sample_ids), f"抽樣搜尋只有 {near_zero}/{len(sample_ids)} 筆找到自己"
    print(f"    ✅ [{name}] 驗證通過：{n:,} 筆、rowid 連續、{len(keys):,} 個合法 key、"
          f"抽樣 {len(sample_ids)} 筆內容/向量一致、搜尋命中 {near_zero}/{len(sample_ids)}"
          f"（同 rowid {exact}，其餘為內容完全相同的片段）")


def _server_running(port: int = 8081) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設只 dry-run）")
    ap.add_argument("--stores", nargs="+", default=DEFAULT_STORES)
    ap.add_argument("--rag-root", default=RAG_ROOT_DIR, help=argparse.SUPPRESS)  # 測試用
    ap.add_argument("--db-root", default=DB_PERSIST_ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--skip-server-check", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if not args.skip_server_check and _server_running():
        print("❌ 偵測到 port 8081 仍有服務在執行，請先停止 main.py 再執行本腳本。")
        return 1

    root_abs = os.path.abspath(args.rag_root)
    print(f"📂 rag_docs：{root_abs}")
    print(f"📂 向量庫：  {os.path.abspath(args.db_root)}")
    disk_keys = _disk_keys(root_abs)
    print(f"📄 磁碟上共 {len(disk_keys):,} 個知識檔案\n")

    plans = {}
    for name in args.stores:
        store_dir = os.path.join(args.db_root, name)
        db_path = os.path.join(store_dir, "vectors.sqlite3")
        if not os.path.exists(db_path):
            print(f"⚠️ [{name}] 找不到 {db_path}，略過")
            continue
        print(f"🔍 [{name}] 分析中...")
        plan = _scan(db_path, root_abs, disk_keys)
        plans[name] = plan
        print(f"    原始列數：{plan['total']:,}（其中 tombstone {plan['tomb']:,}）")
        print(f"    來源路徑分布（依前綴，檔案數）：")
        for p, c in _prefix_summary(plan["source_map"]).most_common():
            print(f"      保留  {c:>9,}  {p}")
        print(f"    保留：{plan['kept']:,} 列 / {len(plan['source_map']):,} 個檔案")
        for reason, c in plan["dropped"].most_common():
            print(f"    丟棄：{c:>9,} 列  {reason}（例：{plan['dropped_examples'][reason]}）")
        if plan["tomb"]:
            print(f"    丟棄：{plan['tomb']:>9,} 列  已標記刪除（tombstone）")
        if name != "_merged":
            prefix = name + "/"
            on_disk = {k for k in disk_keys.values() if k.startswith(prefix)}
            missing = on_disk - set(plan["source_map"].values())
            print(f"    磁碟上此 Worker 共 {len(on_disk):,} 個檔案，整理後尚未收錄 {len(missing):,} 個"
                  f"（下次啟動會增量 embed）")
        print()

    if not plans:
        return 0
    if not args.apply:
        print("ℹ️ dry-run 結束，未寫入任何資料。確認數字無誤後加上 --apply 執行。")
        return 0

    need = sum(p["kept"] for p in plans.values()) * 4600  # 每列約 4 KB 向量 + 文字
    free = shutil.disk_usage(args.db_root).free
    if free < need * 1.5:
        print(f"❌ 磁碟空間不足：需要約 {need/1e9:.1f} GB，剩餘 {free/1e9:.1f} GB")
        return 1

    # 1) 全部建好並驗證
    for name, plan in plans.items():
        store_dir = os.path.join(args.db_root, name)
        tmp_dir = store_dir + ".compact_tmp"
        print(f"🛠️ [{name}] 建立整理後的新庫...")
        _build_tmp(name, os.path.join(store_dir, "vectors.sqlite3"), tmp_dir, plan)
        _verify(name, os.path.join(store_dir, "vectors.sqlite3"), tmp_dir, plan, disk_keys)
        print()

    # 2) 全部通過才替換
    if not args.skip_server_check and _server_running():
        print("❌ 替換前偵測到 port 8081 有服務啟動，已中止；新庫保留在 *.compact_tmp。")
        return 1
    ts = time.strftime("%Y%m%d_%H%M%S")
    for name in plans:
        store_dir = os.path.join(args.db_root, name)
        bak = f"{store_dir}.bak_{ts}"
        os.rename(store_dir, bak)
        os.rename(store_dir + ".compact_tmp", store_dir)
        print(f"🔁 [{name}] 已替換；原資料保留於 {bak}")

    print("\n✅ 完成。啟動 main.py 確認正常後，可自行刪除 *.bak_* 目錄。")
    print("   還原方式：把新目錄移走，再將 <name>.bak_<時間戳> 改回 <name>。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
