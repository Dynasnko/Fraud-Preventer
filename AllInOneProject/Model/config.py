import os
from dotenv import load_dotenv

# __file__ 現在在 Model/ 內，需往上兩層取得 AllInOneProject/ 根目錄
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

RAG_ROOT_DIR = os.path.join(BASE_DIR, "rag_docs")
DB_PERSIST_ROOT = os.path.join(BASE_DIR, "chroma_dbs")

# RAG 片段篩選（相對門檻）；數值為 L2² 距離，越小越相關。
# 由 dev_scripts/rag_eval 評測決定：現行絕對門檻 0.7 命中 19/23，此組 22/23，且不相關題誤用 0/7。
RAG_STRONG = 0.70  # 最佳距離 < STRONG → 只用本地知識庫
RAG_WEAK = 0.85    # STRONG ≤ 最佳距離 < WEAK → 本地 + 網路搜尋；≥ WEAK → 只用網路（不相關題最佳距離實測皆 ≥ 0.92）
RAG_MARGIN = 0.10  # 只採用與最佳距離相差 MARGIN 以內（且 < WEAK）的片段
RAG_THRESHOLD = RAG_STRONG  # 舊名稱，保留相容

EMBED_BATCH_SIZE = 32  # SentenceTransformer.encode() 的 batch size；實測 RTX 4090 + bge-m3 在 32 已飽和，調大只會多吃 VRAM 沒有加速（見 dev_scripts/benchmark_embed_batch_size.py）
