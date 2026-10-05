"""
FaissRAGStore: crash-safe vector store for large collections (e.g. 防詐騙專家).

Architecture
------------
- SQLite  (vectors.sqlite3) : ground truth — text, metadata, and float vectors
- FAISS   (hnsw.faiss)      : ANN search index — rebuilt from SQLite if corrupted

Crash safety
------------
- SQLite writes are ACID-protected  →  vectors are NEVER permanently lost
- FAISS index saved with os.replace() (atomic rename)  →  no partial-write corruption
- On startup: if FAISS missing / corrupted → rebuild from SQLite in ~60 s for 300 K records
  WITHOUT calling the embedding model again

FAISS id ↔ SQLite rowid invariant
----------------------------------
FAISS assigns sequential ids (0, 1, 2, …) in the order vectors are added via add().
SQLite assigns sequential rowids (1, 2, 3, …) in insertion order.
As long as we never DELETE rows:  faiss_id == sqlite_rowid - 1

This invariant is maintained because:
  • add_documents() writes to SQLite first, then calls index.add() in the same order
  • _rebuild_from_db() loads vectors ORDER BY rowid, so FAISS ids re-align with rowids
  • We never delete rows (incremental updates only append)

Removing documents
------------------
delete_sources() only flags rows with deleted = 1 (tombstone) instead of
DELETE-ing them, so rowids stay contiguous and the FAISS index stays aligned
without a rebuild. Tombstoned rows are excluded from search results,
get_embedded_sources() and get_all_records(); count() still includes them
because it must match the FAISS index's ntotal.
"""

import json
import os
import sqlite3
import threading
import uuid
from typing import Any, List, Set, Tuple

import numpy as np


class _CollectionProxy:
    """Proxy so callers can use db._collection.count() without changes."""

    def __init__(self, store: "FaissRAGStore") -> None:
        self._store = store

    def count(self) -> int:
        return self._store.count()


class FaissRAGStore:
    _DEFAULT_DIM   = 1024  # BGE-M3 output dimension
    _HNSW_M        = 16    # HNSW graph degree  (matches ChromaDB default)
    _EF_CONSTRUCT  = 100
    _EF_SEARCH     = 100

    def __init__(self, persist_dir: str, embedding_function: Any) -> None:
        self._persist_dir   = persist_dir
        self._embedding_fn  = embedding_function
        self._sqlite_path   = os.path.join(persist_dir, "vectors.sqlite3")
        self._index_path    = os.path.join(persist_dir, "hnsw.faiss")
        self._unsaved       = 0   # vectors added to in-memory index but not yet on disk

        os.makedirs(persist_dir, exist_ok=True)
        self._init_db()
        # HNSW 索引延遲載入：count()/get_embedded_sources() 只查 SQLite，
        # 不需要把整份索引（可能上百萬筆）攤進記憶體。只有真的要新增向量
        # 或做相似度搜尋時才觸發 _load_or_rebuild()。
        self._index = None
        self._dim   = None
        self._load_lock = threading.Lock()
        # 實例會跨 rebuild 共用：新 graph 建構時寫入索引，舊 graph 可能同時在查詢，
        # HNSW 的 add 與 search 並行不安全
        self._index_lock = threading.Lock()
        self._collection = _CollectionProxy(self)

    def _ensure_index(self) -> Any:
        if self._index is None:
            # 背景預熱執行緒可能跟真正的使用者查詢同時搶著載入，鎖住避免重複載入。
            with self._load_lock:
                if self._index is None:
                    self._index, self._dim = self._load_or_rebuild()
        return self._index

    def warm(self) -> None:
        """Eagerly load the FAISS index now (e.g. from a background thread
        right after startup), so the first real query doesn't pay the
        deserialization cost inline."""
        self._ensure_index()

    # ── SQLite ──────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._sqlite_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vectors (
                    id      TEXT PRIMARY KEY,
                    source  TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    meta    TEXT NOT NULL DEFAULT '{}',
                    vec     BLOB NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                )
            """)
            # 舊版資料庫沒有 deleted 欄位；帶常數預設值的 ADD COLUMN 在 SQLite 是 O(1)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(vectors)")}
            if "deleted" not in cols:
                conn.execute(
                    "ALTER TABLE vectors ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_source ON vectors(source)"
            )
            conn.commit()
            self._n_deleted = conn.execute(
                "SELECT COUNT(*) FROM vectors WHERE deleted = 1"
            ).fetchone()[0]
        finally:
            conn.close()

    def count(self) -> int:
        conn = sqlite3.connect(self._sqlite_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        finally:
            conn.close()

    def get_embedded_sources(self) -> Set[str]:
        """Return all distinct source file paths already stored in SQLite."""
        conn = sqlite3.connect(self._sqlite_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT source FROM vectors WHERE deleted = 0"
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows}

    def delete_sources(self, sources: List[str]) -> int:
        """Tombstone every row whose source is in `sources`. Returns rows affected."""
        sources = list(sources)
        if not sources:
            return 0
        affected = 0
        conn = sqlite3.connect(self._sqlite_path)
        try:
            # 分批避免 SQLite 999 參數上限
            for i in range(0, len(sources), 500):
                batch = sources[i : i + 500]
                placeholders = ",".join("?" * len(batch))
                cur = conn.execute(
                    f"UPDATE vectors SET deleted = 1"
                    f" WHERE deleted = 0 AND source IN ({placeholders})",
                    batch,
                )
                affected += cur.rowcount
            conn.commit()
        finally:
            conn.close()
        self._n_deleted += affected
        return affected

    # ── FAISS index lifecycle ────────────────────────────────────────────────

    @classmethod
    def _make_index(cls, dim: int) -> Any:
        import faiss
        idx = faiss.IndexHNSWFlat(dim, cls._HNSW_M)
        idx.hnsw.efConstruction = cls._EF_CONSTRUCT
        idx.hnsw.efSearch       = cls._EF_SEARCH
        return idx

    def _load_or_rebuild(self) -> Tuple[Any, int]:
        try:
            import faiss  # noqa: F401
        except ImportError:
            raise ImportError(
                "faiss-cpu 未安裝，請執行：pip install faiss-cpu"
            )

        db_count = self.count()

        if os.path.exists(self._index_path):
            try:
                import faiss
                with open(self._index_path, "rb") as _f:
                    _data = np.frombuffer(_f.read(), dtype=np.uint8)
                idx = faiss.deserialize_index(_data)
                if idx.ntotal == db_count:
                    print(
                        f"  ✅ [FAISS] 載入索引（{idx.ntotal:,} 筆，dim={idx.d}）"
                    )
                    return idx, idx.d
                print(
                    f"  ⚠️ [FAISS] 筆數不符"
                    f"（索引:{idx.ntotal:,} vs DB:{db_count:,}），重建..."
                )
            except Exception as e:
                print(f"  ⚠️ [FAISS] 索引損壞（{e}），從 SQLite 重建...")

        return self._rebuild_from_db()

    def _rebuild_from_db(self) -> Tuple[Any, int]:
        """Rebuild FAISS HNSW from SQLite — no embedding model call needed."""
        db_count = self.count()
        if db_count == 0:
            dim = self._DEFAULT_DIM
            print(f"  [FAISS] 向量庫為空，建立空索引（dim={dim}）")
            return self._make_index(dim), dim

        print(
            f"  🔄 [FAISS] 從 SQLite 重建索引"
            f"（{db_count:,} 筆，無需重新 embed）..."
        )

        # 用 fetchmany 分批讀取，避免百萬筆規模時 fetchall() 把整份 BLOB
        # 一次攤進記憶體、又額外複製成一份 np.array（曾經兩個大型 store 同時
        # 重建時疊加到 ~30GB 導致被系統 OOM killer 終止整個 process）。
        step = 10_000
        idx = None
        dim = None
        done = 0
        conn = sqlite3.connect(self._sqlite_path)
        try:
            cursor = conn.execute("SELECT vec FROM vectors ORDER BY rowid")
            while True:
                rows = cursor.fetchmany(step)
                if not rows:
                    break
                batch = np.array(
                    [np.frombuffer(r[0], dtype=np.float32) for r in rows]
                )
                if idx is None:
                    dim = batch.shape[1]
                    idx = self._make_index(dim)
                idx.add(batch)
                done += len(rows)
                print(f"    🔢 [FAISS] {done:,}/{db_count:,} 筆已建索引", flush=True)
        finally:
            conn.close()

        self._write_index(idx)
        print("  ✅ [FAISS] 索引重建完成")
        return idx, dim

    def _write_index(self, idx: Any = None) -> None:
        """Atomically save FAISS index: write to .tmp then os.replace().

        Uses faiss.serialize_index() → Python file I/O to avoid FAISS C++
        FileIOWriter which fails on Windows paths containing non-ASCII chars.
        """
        import faiss
        target = idx if idx is not None else self._index
        tmp = self._index_path + ".tmp"
        data = faiss.serialize_index(target)  # returns numpy uint8 array
        with open(tmp, "wb") as f:
            f.write(data.tobytes())
        os.replace(tmp, self._index_path)
        self._unsaved = 0

    def save(self) -> None:
        """Flush in-memory FAISS index to disk (atomic). Call after bulk add."""
        if self._unsaved > 0:
            self._write_index()

    def add_precomputed(
        self,
        sources: List[str],
        contents: List[str],
        metas: List[Any],
        vecs: np.ndarray,
    ) -> None:
        """Append already-embedded vectors WITHOUT calling the embedding model.

        Lets one store (e.g. the cross-domain _merged index) reuse vectors
        already computed for the same chunks in another store (e.g. a large
        per-worker FaissRAGStore), instead of re-embedding hundreds of
        thousands of chunks. Writes SQLite then the FAISS index in the same
        order, preserving the faiss_id == sqlite_rowid - 1 invariant.
        """
        if len(sources) == 0:
            return
        arr = np.asarray(vecs, dtype=np.float32)
        # 必須在寫 SQLite 之前載入索引：延遲載入時若 DB 已多出新列，會判定筆數不符
        # 而從 DB 重建（已含新列），接著再 add 一次就重複了
        index = self._ensure_index()
        conn = sqlite3.connect(self._sqlite_path)
        try:
            for src, content, meta, vec in zip(sources, contents, metas, arr):
                conn.execute(
                    "INSERT INTO vectors (id, source, content, meta, vec)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        src,
                        content,
                        json.dumps(meta, ensure_ascii=False),
                        vec.tobytes(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        with self._index_lock:
            index.add(arr)
        self._unsaved += len(sources)

    def get_all_records(self) -> Tuple[List[str], List[str], List[Any], np.ndarray]:
        """Return every stored (source, content, meta, vector), ordered by rowid.

        Lets another store copy this one's vectors via add_precomputed()
        without re-embedding.
        """
        conn = sqlite3.connect(self._sqlite_path)
        try:
            rows = conn.execute(
                "SELECT source, content, meta, vec FROM vectors"
                " WHERE deleted = 0 ORDER BY rowid"
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            dim = self._dim if self._dim is not None else self._DEFAULT_DIM
            return [], [], [], np.zeros((0, dim), dtype=np.float32)
        sources  = [r[0] for r in rows]
        contents = [r[1] for r in rows]
        metas    = [json.loads(r[2]) for r in rows]
        vecs     = np.array(
            [np.frombuffer(r[3], dtype=np.float32) for r in rows]
        )
        return sources, contents, metas, vecs

    # ── Public API (drop-in for langchain Chroma) ───────────────────────────

    def add_documents(self, documents: List[Any]) -> None:
        """Embed documents, persist to SQLite, update in-memory FAISS index.

        Crash safety:
          - SQLite commit happens BEFORE index.add() → vectors safe even on crash
          - FAISS is only written to disk explicitly via save(), not here
          - If process dies here: SQLite intact, FAISS rebuilt on next startup
        """
        if not documents:
            return

        index = self._ensure_index()  # 同 add_precomputed：先載入再寫 SQLite
        texts = [d.page_content for d in documents]
        vecs  = np.array(
            self._embedding_fn.embed_documents(texts), dtype=np.float32
        )

        rows = [
            (
                str(uuid.uuid4()),
                doc.metadata.get("source", ""),
                doc.page_content,
                json.dumps(doc.metadata, ensure_ascii=False),
                vec.tobytes(),
            )
            for doc, vec in zip(documents, vecs)
        ]
        conn = sqlite3.connect(self._sqlite_path)
        try:
            conn.executemany(
                "INSERT INTO vectors (id, source, content, meta, vec)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

        with self._index_lock:
            index.add(vecs)
        self._unsaved += len(documents)

    def similarity_search_with_score(
        self, query: str, k: int = 5
    ) -> List[Tuple[Any, float]]:
        """Return List[(Document, l2_squared_distance)].

        Same format as langchain Chroma.similarity_search_with_score().
        For BGE-M3 normalised vectors, l2² = 2*(1 - cosine_similarity),
        so RAG_THRESHOLD = 0.7 means cosine ≥ 0.65 — identical to ChromaDB.
        """
        from langchain_core.documents import Document

        idx = self._ensure_index()
        if idx.ntotal == 0:
            return []

        q_vec    = np.array(
            [self._embedding_fn.embed_query(query)], dtype=np.float32
        )
        # 有 tombstone 時多取一些，補回被過濾掉的已刪除片段
        actual_k = min(k * 2 if self._n_deleted else k, idx.ntotal)
        with self._index_lock:
            dists, faiss_ids = idx.search(q_vec, actual_k)

        valid = [
            (float(d), int(i))
            for d, i in zip(dists[0], faiss_ids[0])
            if i >= 0
        ]
        if not valid:
            return []

        # faiss_id (0-based) → sqlite rowid (1-based)
        rowids       = [i + 1 for _, i in valid]
        placeholders = ",".join("?" * len(rowids))
        conn = sqlite3.connect(self._sqlite_path)
        try:
            rows = conn.execute(
                f"SELECT rowid, content, meta"
                f" FROM vectors WHERE deleted = 0 AND rowid IN ({placeholders})",
                rowids,
            ).fetchall()
        finally:
            conn.close()

        row_map = {r[0]: (r[1], json.loads(r[2])) for r in rows}
        results: List[Tuple[Any, float]] = []
        for dist, faiss_id in valid:
            rowid = faiss_id + 1
            if rowid in row_map:
                content, meta = row_map[rowid]
                results.append(
                    (Document(page_content=content, metadata=meta), dist)
                )
        return results[:k]
