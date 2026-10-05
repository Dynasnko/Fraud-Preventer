"""
量測 BAAI/bge-m3 embedding 在不同 batch_size 下的實際速度與 VRAM 使用量。

用法：
    python dev_scripts/benchmark_embed_batch_size.py
    python dev_scripts/benchmark_embed_batch_size.py --batch-sizes 32 128 256 512 --n-texts 4000

會盡量從 AllInOneProject/rag_docs/ 底下抓真實文件內容切成約 450 字的 chunk 來測，
這樣長度分佈跟 rag_builder.py 實際 embedding 時的資料比較接近；
若找不到足夠文件，會用合成中文文字補足。
"""
import argparse
import glob
import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

CHUNK_SIZE = 450  # 對齊 rag_builder.py 的 RecursiveCharacterTextSplitter chunk_size(400~500)


def collect_real_chunks(min_count: int) -> list[str]:
    rag_docs = os.path.join(_PROJECT_ROOT, "AllInOneProject", "rag_docs")
    chunks: list[str] = []
    patterns = [
        os.path.join(rag_docs, "**", "*.md"),
        os.path.join(rag_docs, "**", "*.txt"),
    ]
    files: list[str] = []
    for p in patterns:
        files.extend(glob.glob(p, recursive=True))

    for path in files:
        if len(chunks) >= min_count:
            break
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue
        text = " ".join(text.split())  # 壓縮空白/換行，避免全是空白的 chunk
        for i in range(0, len(text), CHUNK_SIZE):
            chunk = text[i : i + CHUNK_SIZE].strip()
            if len(chunk) > 50:
                chunks.append(chunk)
            if len(chunks) >= min_count:
                break
    return chunks


def pad_with_synthetic(chunks: list[str], n_texts: int) -> list[str]:
    if not chunks:
        base = (
            "本案為假投資詐騙，被害人於社群平台認識自稱投資老師之對象，"
            "遭誘導加入不明交易平台並多次匯款，事後平台無法出金，經查該帳戶涉及多起詐騙案件。"
        )
        chunks = [base]
    out = list(chunks)
    i = 0
    while len(out) < n_texts:
        out.append(chunks[i % len(chunks)])
        i += 1
    return out[:n_texts]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=[32, 256])
    parser.add_argument("--n-texts", type=int, default=3000, help="本次測試的文字總筆數")
    args = parser.parse_args()

    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"裝置：{device.upper()}")
    if device == "cuda":
        print(f"GPU：{torch.cuda.get_device_name(0)}，"
              f"總 VRAM：{torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

    print("載入模型 BAAI/bge-m3 ...")
    model = SentenceTransformer("BAAI/bge-m3", device=device)
    model.max_seq_length = 512

    print(f"收集測試文字（目標 {args.n_texts} 筆，chunk 約 {CHUNK_SIZE} 字，對齊實際 RAG chunk 大小）...")
    real_chunks = collect_real_chunks(args.n_texts)
    texts = pad_with_synthetic(real_chunks, args.n_texts)
    print(f"實際使用 {len(texts)} 筆文字（其中 {min(len(real_chunks), len(texts))} 筆取自 rag_docs 真實內容）\n")

    results = []
    for bs in args.batch_sizes:
        # 每個 batch_size 各自暖機一次（cuDNN/allocator 對不同 batch shape 有各自的
        # 首次選演算法開銷），暖機結果不計入計時，避免第一個測到的 batch_size 吃虧。
        model.encode(texts[: min(bs * 2, len(texts))], batch_size=bs,
                     normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        if device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()

        t0 = time.perf_counter()
        model.encode(
            texts, batch_size=bs, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0

        throughput = len(texts) / elapsed
        peak_mem_gb = (torch.cuda.max_memory_allocated() / 1024**3) if device == "cuda" else None

        results.append((bs, elapsed, throughput, peak_mem_gb))
        mem_str = f"，峰值 VRAM：{peak_mem_gb:.2f} GB" if peak_mem_gb is not None else ""
        print(f"batch_size={bs:>4}  →  {elapsed:7.2f} 秒  ({throughput:8.1f} 筆/秒){mem_str}")

    print("\n=== 總結 ===")
    baseline = results[0]
    for bs, elapsed, throughput, peak_mem_gb in results:
        speedup = baseline[1] / elapsed
        print(f"batch_size={bs:>4}: {throughput:8.1f} 筆/秒，相對 batch_size={baseline[0]} 的加速倍率 = {speedup:.2f}x")


if __name__ == "__main__":
    main()
