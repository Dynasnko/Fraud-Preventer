"""
165 詐騙案例資料唯讀查詢模組
DB 路徑: AllInOneProject/chroma_dbs/scam_records.sqlite3（由 165 同步工具產生，此模組不寫入）
"""
import sqlite3
import os
import pathlib

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "AllInOneProject", "chroma_dbs", "scam_records.sqlite3",
)


def _conn():
    if not os.path.exists(_DB_PATH):
        return None
    conn = sqlite3.connect(f"{pathlib.Path(_DB_PATH).as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_indexes():
    """建立查詢索引（冪等）。唯讀連線無法寫入，改用一般連線執行一次。"""
    if not os.path.exists(_DB_PATH):
        return
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_city ON scam_cases(city)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_date ON scam_cases(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_title ON scam_cases(title)")
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def list_scam_cases(search="", city="", page=1, page_size=50):
    conn = _conn()
    if not conn:
        return [], 0
    w, p = [], []
    if search:
        w.append("(title LIKE ? OR city LIKE ?)")
        s = f"%{search}%"; p.extend([s, s])
    if city:
        w.append("city = ?"); p.append(city)
    ws = (" WHERE " + " AND ".join(w)) if w else ""
    total = conn.execute(f"SELECT COUNT(*) FROM scam_cases{ws}", p).fetchone()[0]
    off = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM scam_cases{ws} ORDER BY date DESC LIMIT ? OFFSET ?",
        p + [page_size, off]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_scam_case(case_id):
    conn = _conn()
    if not conn:
        return None
    r = conn.execute("SELECT * FROM scam_cases WHERE case_id = ?", (case_id,)).fetchone()
    conn.close()
    return dict(r) if r else None
