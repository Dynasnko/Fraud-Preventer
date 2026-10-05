import os
import re
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Any, Dict, Optional, Tuple

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from AllInOneProject.Model.config import RAG_ROOT_DIR, DB_PERSIST_ROOT, EMBED_BATCH_SIZE
from AllInOneProject.Agent.faiss_rag_store import FaissRAGStore

# I/O-bound file reads benefit from oversubscribing beyond CPU core count.
_IO_MAX_WORKERS = min(32, (os.cpu_count() or 4) * 4)

# Workers that use FaissRAGStore instead of ChromaDB.
# Reason: these collections exceed ChromaDB 1.x's HNSW sync_threshold (1000),
# triggering non-atomic compaction that permanently loses vectors on crash.
_FAISS_WORKERS = {"防詐騙專家"}

# ChromaDB 1.x HNSW crash detection: compaction writes index_metadata.pickle
# BEFORE binary files, then deletes vectors from embeddings_queue.
# A mid-compaction crash leaves pickle present but binary files missing — unrecoverable.
_HNSW_BINARY_FILES = {"header.bin", "data_level0.bin", "length.bin", "link_lists.bin"}

# For _merged (ChromaDB): raise sync_threshold so HNSW compaction never auto-triggers.
# Keeps all vectors safely in embeddings_queue (SQLite). Query uses linear scan,
# acceptable for the _merged collection's moderate size.
_SAFE_SYNC_THRESHOLD = 10_000_000

# bge-m3 在 GPU 上約佔 2 GB。新增/編輯 Worker 觸發 rebuild 時，舊 graph 仍在服務並持有
# 模型，若每次都重新載入，重建期間 GPU 上會同時存在兩份，VRAM 吃緊時直接 OOM。
# 因此整個 process 只載入一次、所有 build 共用。
_EMBEDDINGS = None
_EMBEDDINGS_LOCK = threading.Lock()

# 同理：防詐騙專家與 _merged 各約百萬筆，HNSW 索引各佔約 4 GB RAM。rebuild 若建立新的
# FaissRAGStore，新舊 graph 會各持有一份已載入的索引，RAM 直接翻倍被 OOM killer 終止。
# 以 persist_dir 為 key 共用同一個實例。
_FAISS_STORES: Dict[str, FaissRAGStore] = {}


def _get_faiss_store(persist_dir: str, embeddings: Any) -> FaissRAGStore:
    with _EMBEDDINGS_LOCK:
        store = _FAISS_STORES.get(persist_dir)
        if store is None:
            store = FaissRAGStore(persist_dir, embeddings)
            _FAISS_STORES[persist_dir] = store
        return store


# 向量庫資料夾以 Worker 名稱命名（chroma_dbs/<名稱>/）。Worker 改名或刪除後舊資料夾若留著，
# 之後再建立同名 Worker 會沿用裡面的舊向量；由於增量更新以檔案路徑判斷是否已 embed，
# 同檔名的新內容會被略過，RAG 實際查到的仍是舊內容。
_STARTUP_CLEANUP_DONE = False


def drop_worker_vectors(worker_name: str) -> None:
    """清空指定 Worker 的 Chroma collection（Worker 刪除 / 改名 / 建立失敗後，或建立前清除殘留）。

    只清 collection、不刪資料夾：執行中 Chroma 會快取已開啟的 client，直接刪檔在 Windows 會失敗，
    在 Linux 則會讓快取的連線寫進已刪除的檔案。空資料夾由下次啟動時的
    _cleanup_stale_stores() 移除。呼叫前須確認已無 graph 在使用該 Worker 的向量庫。
    """
    if worker_name in _FAISS_WORKERS:
        return
    persist_dir = os.path.join(DB_PERSIST_ROOT, worker_name)
    if not os.path.exists(os.path.join(persist_dir, "chroma.sqlite3")):
        return
    Chroma(persist_directory=persist_dir).delete_collection()
    print(f"  🗑️ [RAG] 已清空 {worker_name} 的向量庫")


class MultiAgentRAGBuilder:
    def __init__(self, root_dir: str = RAG_ROOT_DIR):
        self.root_dir = root_dir

    def _get_embeddings(self):
        global _EMBEDDINGS
        with _EMBEDDINGS_LOCK:
            if _EMBEDDINGS is None:
                _EMBEDDINGS = self._load_embeddings()
        return _EMBEDDINGS

    def _load_embeddings(self):
        # 只有在本機確實已經快取 bge-m3 時，才略過每次啟動都會做的 HF Hub
        # 連線檢查（省約 2 秒）。全新環境（尚未下載過模型）仍要能連網下載，
        # 避免被誤設為 offline 導致下載失敗。若要強制重新檢查，啟動前手動
        # 設定 HF_HUB_OFFLINE=0 即可覆蓋。
        from huggingface_hub import try_to_load_from_cache
        if try_to_load_from_cache("BAAI/bge-m3", filename="config.json") is not None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import torch
        from sentence_transformers import SentenceTransformer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"  🖥️  Embedding 裝置：{device.upper()}")
        st_model = SentenceTransformer("BAAI/bge-m3", device=device)
        st_model.max_seq_length = 512

        class _WrappedEmbeddings:
            def embed_documents(self, texts):
                # GPU 與其他程序（例如本機 LLM 推論服務）共用時可用 VRAM 可能只剩幾百 MB，
                # OOM 時清快取並將 batch 減半重試，寧可變慢也不要讓整個啟動失敗
                batch_size = EMBED_BATCH_SIZE
                while True:
                    try:
                        return st_model.encode(
                            texts, normalize_embeddings=True,
                            batch_size=batch_size, convert_to_numpy=True,
                        ).tolist()
                    except torch.OutOfMemoryError:
                        if batch_size == 1:
                            raise
                        torch.cuda.empty_cache()
                        batch_size //= 2
                        print(f"    ⚠️ GPU 記憶體不足，embedding batch 降為 {batch_size} 重試", flush=True)
            def embed_query(self, text):
                return st_model.encode(
                    [text], normalize_embeddings=True, convert_to_numpy=True,
                )[0].tolist()
        return _WrappedEmbeddings()

    def _add_in_batches(self, vector_store, chunks: List[Any],
                        batch_size: int = 500, label: str = "") -> None:
        total = len(chunks)
        for i in range(0, total, batch_size):
            batch = chunks[i : i + batch_size]
            vector_store.add_documents(documents=batch)
            done = min(i + batch_size, total)
            print(f"    💾 [{label}] {done}/{total} 片段已寫入", flush=True)

    def load_documents_from_folder(self, folder_path: str) -> List[Any]:
        from langchain_core.documents import Document

        file_paths = [
            os.path.join(root, file)
            for root, _, files in os.walk(folder_path)
            for file in files
            if not file.endswith(".md")
        ]
        if not file_paths:
            return []

        def _read(file_path: str) -> Optional[Any]:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"⚠️ [RAG] 無法讀取 {file_path}: {e}")
                return None
            if not content.strip():
                return None
            return Document(
                page_content=content,
                metadata={"source": self._source_key(file_path)},
            )

        with ThreadPoolExecutor(max_workers=_IO_MAX_WORKERS) as executor:
            results = executor.map(_read, file_paths)
            return [doc for doc in results if doc is not None]

    def split_documents(self, docs: List[Any]) -> List[Any]:
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        return splitter.split_documents(docs) if docs else []

    @staticmethod
    def _make_markdown_splitters() -> Tuple[MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter]:
        headers_to_split_on = [("#", "案件編號"), ("##", "段落")]
        try:
            markdown_splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=headers_to_split_on, strip_headers=False
            )
        except TypeError:
            markdown_splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=headers_to_split_on
            )
        chinese_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400, chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " "],
        )
        return markdown_splitter, chinese_splitter

    def _split_markdown_file(
        self, file_path: str,
        markdown_splitter: MarkdownHeaderTextSplitter,
        chinese_splitter: RecursiveCharacterTextSplitter,
    ) -> List[Any]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            print(f"⚠️ [RAG] 無法讀取 {file_path}: {e}")
            return []
        if not text.strip():
            return []
        md_splits = markdown_splitter.split_text(text)
        for doc in md_splits:
            doc.metadata["source"] = self._source_key(file_path)
        return chinese_splitter.split_documents(md_splits)

    def _split_markdown_files_parallel(self, file_paths: List[str]) -> List[Any]:
        if not file_paths:
            return []
        # markdown_splitter/chinese_splitter only read config attributes during
        # split, so a single pair of instances is safe to share read-only across threads.
        markdown_splitter, chinese_splitter = self._make_markdown_splitters()
        all_splits: List[Any] = []
        with ThreadPoolExecutor(max_workers=_IO_MAX_WORKERS) as executor:
            results = executor.map(
                lambda fp: self._split_markdown_file(fp, markdown_splitter, chinese_splitter),
                file_paths,
            )
            for splits in results:
                all_splits.extend(splits)
        return all_splits

    def _load_markdown_documents(self, folder_path: str) -> List[Any]:
        file_paths = [
            os.path.join(root, file)
            for root, _, files in os.walk(folder_path)
            for file in files
            if file.endswith(".md")
        ]
        return self._split_markdown_files_parallel(file_paths)

    def _build_all_chunks(self, data_path: str) -> List[Any]:
        chunks = []
        md_chunks = self._load_markdown_documents(data_path)
        if md_chunks:
            print(f"    📄 MD 切分器：{len(md_chunks)} 個片段")
            chunks.extend(md_chunks)
        raw_docs = self.load_documents_from_folder(data_path)
        other_chunks = self.split_documents(raw_docs)
        if other_chunks:
            print(f"    📄 標準切分器：{len(other_chunks)} 個片段")
            chunks.extend(other_chunks)
        return chunks

    def _source_key(self, file_path: str) -> str:
        """向量庫中 source 欄位的 key：相對於 rag_docs/ 的路徑，一律以 / 分隔。

        不可存絕對路徑：專案搬移目錄或在 Windows / Linux 間切換時，絕對路徑全部改變，
        增量更新會把每個檔案都當成新檔再 embed 一次（防詐騙專家曾因此累積三份重複向量）。
        只對磁碟上的實際路徑呼叫；已存在向量庫中的 source 直接比對原值。
        """
        rel = os.path.relpath(os.path.abspath(file_path), os.path.abspath(self.root_dir))
        return rel.replace(os.sep, "/")

    @staticmethod
    def _is_legacy_source(source: str) -> bool:
        """舊版以絕對路徑（POSIX 或 Windows）作為 source。"""
        return os.path.isabs(source) or bool(re.match(r"^([A-Za-z]:)?[\\/]", source))

    def _check_faiss_keys(self, sources: set, label: str) -> None:
        """大型 FAISS 庫若仍是舊版絕對路徑 key，直接停止啟動。

        否則所有 source 都比對不到：防詐騙專家會把十幾萬個檔案全部重新 embed，
        _merged 則會把全部向量標記刪除。必須先離線執行整理腳本轉換 key。
        """
        if any(self._is_legacy_source(s) for s in sources):
            raise RuntimeError(
                f"[RAG] {label} 向量庫仍使用舊版絕對路徑作為 source。"
                f"請先停止系統並執行：python dev_scripts/compact_faiss_store.py --apply"
            )

    def _list_source_files(self, data_path: str) -> set:
        """目前磁碟上 Domain_Knowledge 內所有檔案的 source key，用來比對哪些向量已過期。"""
        return {
            self._source_key(os.path.join(root, file))
            for root, _, files in os.walk(data_path)
            for file in files
        }

    def _build_new_chunks(self, data_path: str, embedded_sources: set) -> List[Any]:
        md_paths = [
            os.path.join(root, file)
            for root, _, files in os.walk(data_path)
            for file in files
            if file.endswith(".md")
            and self._source_key(os.path.join(root, file)) not in embedded_sources
        ]
        chunks = self._split_markdown_files_parallel(md_paths)

        raw_docs = self.load_documents_from_folder(data_path)
        new_other = [
            d for d in raw_docs
            if d.metadata.get("source", "") not in embedded_sources
        ]
        chunks.extend(self.split_documents(new_other))
        return chunks

    def ensure_example_data(self):
        if not os.path.exists(self.root_dir):
            os.makedirs(self.root_dir)
        if not any(
            os.path.isdir(os.path.join(self.root_dir, d))
            for d in os.listdir(self.root_dir)
        ):
            print("⚠️ [RAG] 建立範例資料...")
            dirs = {
                "System_Architect": "我是一位系統架構師，專精於微服務、雲端架構。",
                "Statistician": "我是一位統計學專家，擅長數據分析、機率論。",
            }
            for name, desc in dirs.items():
                p = os.path.join(self.root_dir, name)
                os.makedirs(os.path.join(p, "Domain_Knowledge"), exist_ok=True)
                with open(os.path.join(p, "description.txt"), "w", encoding="utf-8") as f:
                    f.write(desc)

    # ── ChromaDB helpers ────────────────────────────────────────────────────

    def _get_all_metadatas(self, vector_store) -> List[Dict]:
        """Paginated get to avoid SQLite 999-variable limit on large collections."""
        batch_size = 500
        all_metas: List[Dict] = []
        offset = 0
        while True:
            batch = vector_store.get(
                include=["metadatas"], limit=batch_size, offset=offset
            )
            ids = batch.get("ids", [])
            if not ids:
                break
            all_metas.extend(batch.get("metadatas", []))
            if len(ids) < batch_size:
                break
            offset += batch_size
        return all_metas

    def _repair_persist_dir(self, persist_dir: str) -> bool:
        """Detect mid-compaction HNSW crash and wipe the corrupted directory.

        ChromaDB 1.x compaction order:
          1. write index_metadata.pickle
          2. update max_seq_id in SQLite  ← marks compaction "done"
          3. delete compacted vectors from embeddings_queue  ← vectors gone from SQLite
          4. write HNSW binary files  ← if crash here, vectors permanently lost

        Detection: pickle present but no binary files → wiped and rebuilt from source docs.
        Returns True if directory was wiped.
        """
        if not os.path.isdir(persist_dir):
            return False
        for entry in os.scandir(persist_dir):
            if not entry.is_dir():
                continue
            contents = {f.name for f in os.scandir(entry.path) if f.is_file()}
            if "index_metadata.pickle" in contents and not contents & _HNSW_BINARY_FILES:
                print(f"  ⚠️ [RAG] 偵測到損壞的 HNSW 索引：{persist_dir}")
                print(f"     原因：HNSW 壓縮中斷（pickle 存在但二進位索引檔案缺失）")
                print(f"     修復：清除損壞目錄，將從原始文件重建...")
                shutil.rmtree(persist_dir)
                return True
        return False

    def _patch_sync_threshold(self, persist_dir: str,
                               threshold: int = _SAFE_SYNC_THRESHOLD) -> None:
        """Raise HNSW sync_threshold in ChromaDB's SQLite schema.

        Prevents auto-compaction for _merged. Must be called BEFORE adding documents
        so the in-memory collection uses the new threshold.
        Effective after reopening the Chroma object (schema read at construction).
        """
        db_path = os.path.join(persist_dir, "chroma.sqlite3")
        if not os.path.exists(db_path):
            return
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT id, schema_str FROM collections"
                ).fetchall()
                patched = False
                for col_id, schema_str in rows:
                    if not schema_str:
                        continue
                    marker = f'"sync_threshold": {threshold}'
                    if marker in schema_str:
                        continue
                    new_schema = re.sub(
                        r'"sync_threshold"\s*:\s*\d+',
                        f'"sync_threshold": {threshold}',
                        schema_str,
                    )
                    conn.execute(
                        "UPDATE collections SET schema_str = ? WHERE id = ?",
                        (new_schema, col_id),
                    )
                    patched = True
                if patched:
                    print(
                        f"  🔧 [RAG] _merged sync_threshold → {threshold:,}"
                        f"（停用 HNSW 自動壓縮，向量永久保存於 SQLite）"
                    )
        except Exception as e:
            print(f"  ⚠️ [RAG] 無法更新 sync_threshold: {e}")

    def _migrate_chroma_to_faiss(self, persist_dir: str) -> None:
        """Remove legacy ChromaDB files when a worker switches to FaissRAGStore.

        Keeps only vectors.sqlite3 and hnsw.faiss (the FAISS layout).
        Safe to call even if already migrated (no-op if chroma.sqlite3 absent).
        """
        chroma_db = os.path.join(persist_dir, "chroma.sqlite3")
        if not os.path.exists(chroma_db):
            return
        print(f"  🔄 [FAISS] 偵測到舊 ChromaDB 資料，清除以改用 FAISS...")
        keep = {"vectors.sqlite3", "hnsw.faiss", "hnsw.faiss.tmp"}
        for entry in os.scandir(persist_dir):
            if entry.name in keep:
                continue
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
        print(f"  ✅ [FAISS] 舊 ChromaDB 資料已清除，下次啟動將重建 FAISS 索引")

    # ── Main build / load ───────────────────────────────────────────────────

    def _cleanup_stale_stores(self, worker_folders: List[str]) -> None:
        """刪除對應不到任何 rag_docs/ 資料夾的 Chroma 向量庫資料夾（每個 process 只在首次 build 執行）。

        必須在本 process 開啟任何 Chroma client 之前執行（見 drop_worker_vectors 說明）。
        保守起見只刪 Chroma 資料夾：略過 FAISS Worker、_merged 等 _ 開頭、以及 .bak_ 等含 . 的備份。
        """
        global _STARTUP_CLEANUP_DONE
        if _STARTUP_CLEANUP_DONE:
            return
        _STARTUP_CLEANUP_DONE = True
        live = set(worker_folders)
        for entry in os.scandir(DB_PERSIST_ROOT):
            name = entry.name
            if (
                not entry.is_dir(follow_symlinks=False)
                or name in live
                or name in _FAISS_WORKERS
                or name.startswith("_")
                or "." in name
                or not os.path.exists(os.path.join(entry.path, "chroma.sqlite3"))
            ):
                continue
            shutil.rmtree(entry.path)
            print(f"  🗑️ [RAG] 移除過時的向量庫資料夾：{name}（已無對應的 Worker）")

    def build_or_load(self) -> Dict[str, Any]:
        system_config: Dict[str, Any] = {"stores": {}, "worker_map": {}}
        if not os.path.exists(DB_PERSIST_ROOT):
            os.makedirs(DB_PERSIST_ROOT)
        try:
            worker_folders = [
                d for d in os.listdir(self.root_dir)
                if os.path.isdir(os.path.join(self.root_dir, d))
            ]
        except Exception:
            return system_config

        self._cleanup_stale_stores(worker_folders)
        embeddings = self._get_embeddings()
        print(f"\n🚀 [RAG] 掃描專家目錄...")

        for worker_name in worker_folders:
            worker_root = os.path.join(self.root_dir, worker_name)
            desc_path   = os.path.join(worker_root, "description.txt")
            data_path   = os.path.join(worker_root, "Domain_Knowledge")
            if not os.path.exists(desc_path):
                continue
            try:
                with open(desc_path, "r", encoding="utf-8") as f:
                    description = f.read().strip()
            except Exception:
                continue

            worker_id   = f"worker_{worker_name}"
            persist_dir = os.path.join(DB_PERSIST_ROOT, worker_name)
            print(f"  🔄 [初始化] {worker_name}")

            # ── FAISS path (防詐騙專家 and future large workers) ──────────
            if worker_name in _FAISS_WORKERS:
                self._migrate_chroma_to_faiss(persist_dir)
                vector_store = _get_faiss_store(persist_dir, embeddings)
                db_count = vector_store.count()
                if db_count == 0:
                    print(f"    📥 首次建立 FAISS 索引...")
                    chunks = self._build_all_chunks(data_path)
                    if chunks:
                        self._add_in_batches(vector_store, chunks, label=worker_name)
                        vector_store.save()
                else:
                    embedded_sources = vector_store.get_embedded_sources()
                    self._check_faiss_keys(embedded_sources, worker_name)
                    new_chunks = self._build_new_chunks(data_path, embedded_sources)
                    if new_chunks:
                        print(f"    📥 增量新增 {len(new_chunks)} 個片段")
                        self._add_in_batches(vector_store, new_chunks, label=worker_name)
                        vector_store.save()
                    else:
                        print(f"    ✅ FAISS 向量庫已是最新（{db_count:,} 筆）")

            # ── ChromaDB path (all other workers) ─────────────────────────
            else:
                self._repair_persist_dir(persist_dir)
                vector_store = Chroma(
                    persist_directory=persist_dir, embedding_function=embeddings
                )
                db_count = vector_store._collection.count()
                if db_count == 0:
                    print(f"    📥 首次建立索引...")
                    chunks = self._build_all_chunks(data_path)
                    if chunks:
                        self._add_in_batches(vector_store, chunks, label=worker_name)
                else:
                    all_metas = self._get_all_metadatas(vector_store)
                    stored_sources = {m.get("source", "") for m in all_metas}
                    # 檔案已從 Domain_Knowledge 移除 → 一併刪除其向量，避免 RAG 仍引用舊內容
                    on_disk = self._list_source_files(data_path)
                    # 舊版絕對路徑 key 也會在此被視為過期，清除後以相對路徑重新 embed（僅小型 Chroma 庫）
                    stale = [s for s in stored_sources if s not in on_disk]
                    if stale:
                        vector_store._collection.delete(where={"source": {"$in": stale}})
                        print(f"    🗑️ 移除 {len(stale)} 個已刪除檔案的向量")
                        stored_sources -= set(stale)
                    embedded_sources = stored_sources
                    new_chunks = self._build_new_chunks(data_path, embedded_sources)
                    if new_chunks:
                        print(f"    📥 增量新增 {len(new_chunks)} 個片段")
                        self._add_in_batches(vector_store, new_chunks, label=worker_name)
                    else:
                        print(f"    ✅ 向量庫已是最新（{db_count} 筆）")

            system_config["stores"][worker_id] = vector_store
            system_config["worker_map"][worker_id] = description

        # ── _merged (FaissRAGStore) ────────────────────────────────────────
        # Cross-domain fallback index for internet_search, covering ALL
        # workers including large FAISS ones (e.g. 防詐騙專家's 300K+ chunks).
        # ChromaDB's brute-force linear scan couldn't handle that volume
        # (count() alone took ~100s, full metadata scan ~15-20 min on startup).
        # FaissRAGStore gives O(log n) HNSW search and instant count()/diff,
        # same as the per-worker large stores already use.
        merged_persist_dir = os.path.join(DB_PERSIST_ROOT, "_merged")
        merged_store = _get_faiss_store(merged_persist_dir, embeddings)

        # 目前所有已載入 Worker 的有效來源；_merged 中不在此集合的（檔案被刪、
        # Worker 被刪除或改名）都視為過期並 tombstone。
        live_sources: set = set()
        faiss_worker_sources: Dict[str, set] = {}
        for worker_name in worker_folders:
            worker_root = os.path.join(self.root_dir, worker_name)
            if not os.path.exists(os.path.join(worker_root, "description.txt")):
                continue
            if worker_name in _FAISS_WORKERS:
                src_store = system_config["stores"].get(f"worker_{worker_name}")
                if src_store is None:
                    continue
                srcs = src_store.get_embedded_sources()
                faiss_worker_sources[worker_name] = srcs
                live_sources |= srcs
            else:
                live_sources |= self._list_source_files(
                    os.path.join(worker_root, "Domain_Knowledge")
                )

        merged_raw_sources = merged_store.get_embedded_sources()
        self._check_faiss_keys(merged_raw_sources, "_merged")
        stale_merged = [s for s in merged_raw_sources if s not in live_sources]
        if stale_merged:
            removed = merged_store.delete_sources(stale_merged)
            print(
                f"  🗑️ [Merged RAG] 移除 {len(stale_merged)} 個已刪除檔案"
                f"（{removed} 個片段）"
            )
        existing_merged_sources = merged_raw_sources - set(stale_merged)

        all_new_chunks: List[Any] = []
        for worker_name in worker_folders:
            worker_root = os.path.join(self.root_dir, worker_name)
            desc_path   = os.path.join(worker_root, "description.txt")
            data_path   = os.path.join(worker_root, "Domain_Knowledge")
            if not os.path.exists(desc_path):
                continue

            if worker_name in _FAISS_WORKERS:
                # Reuse this worker's already-computed vectors instead of
                # re-embedding its (potentially huge) corpus a second time.
                src_store = system_config["stores"].get(f"worker_{worker_name}")
                if src_store is None:
                    continue
                src_sources = faiss_worker_sources[worker_name]
                if not (src_sources - existing_merged_sources):
                    print(f"  ✅ [Merged RAG] {worker_name} 向量已是最新，略過")
                    continue
                print(f"  📦 [Merged RAG] 複用 {worker_name} 現成向量（免重新 embed）...")
                sources, contents, metas, vecs = src_store.get_all_records()
                keep_idx = [
                    i for i, s in enumerate(sources)
                    if s not in existing_merged_sources
                ]
                if keep_idx:
                    merged_store.add_precomputed(
                        [sources[i] for i in keep_idx],
                        [contents[i] for i in keep_idx],
                        [metas[i] for i in keep_idx],
                        vecs[keep_idx],
                    )
                    merged_store.save()
                    print(
                        f"    ✅ [Merged RAG] {worker_name} 新增 {len(keep_idx)} 筆"
                        f"（複用向量，未重新 embed）"
                    )
                    existing_merged_sources |= {sources[i] for i in keep_idx}
                continue

            new_chunks = self._build_new_chunks(data_path, existing_merged_sources)
            all_new_chunks.extend(new_chunks)

        if all_new_chunks:
            print(
                f"  📦 [Merged RAG] 新增 {len(all_new_chunks)} 個片段到跨域向量庫"
            )
            self._add_in_batches(merged_store, all_new_chunks, label="_merged")
            merged_store.save()
        elif merged_store.count() == 0:
            print(f"  ⚠️ [Merged RAG] 無任何文件可索引")
        else:
            print(f"  ✅ [Merged RAG] 跨域向量庫已是最新（{merged_store.count()} 筆）")

        system_config["merged_store"] = merged_store
        return system_config
