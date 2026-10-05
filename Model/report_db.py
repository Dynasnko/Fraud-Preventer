"""
通報資料 SQLite3 資料庫操作模組
DB 路徑: AllInOneProject/chroma_dbs/reports.sqlite3
"""
import sqlite3
import os
from datetime import datetime, timezone

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "AllInOneProject", "chroma_dbs", "reports.sqlite3",
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 常數（選單選項） ─────────────────────────────────────────────────────────

FRAUD_CHANNELS = ["電話", "LINE", "Facebook", "Instagram", "網頁/App", "簡訊", "Email", "其他"]

FRAUD_TYPES = [
    "假投資詐騙", "假交友（感情）詐騙", "假網路購物詐騙",
    "解除分期付款詐騙", "假冒政府機關（公務員）詐騙",
    "猜猜我是誰詐騙", "假冒親友詐騙", "假求職/打工詐騙",
    "假中獎/博弈詐騙", "色情應召詐騙", "其他",
]

CITIES = [
    "臺北市", "新北市", "基隆市", "桃園市", "新竹市", "新竹縣",
    "苗栗縣", "臺中市", "彰化縣", "南投縣", "雲林縣", "嘉義市",
    "嘉義縣", "臺南市", "高雄市", "屏東縣", "宜蘭縣", "花蓮縣",
    "臺東縣", "澎湖縣", "金門縣", "連江縣",
]

REPORT_STATUSES = ["pending", "reviewing", "resolved", "closed"]

STATUS_LABELS = {
    "pending": "待處理",
    "reviewing": "審核中",
    "resolved": "已結案",
    "closed": "已關閉",
}


# ── 初始化 ───────────────────────────────────────────────────────────────────

def init_db():
    """建表（冪等）"""
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            reporter_name   TEXT,
            reporter_phone  TEXT,
            reporter_email  TEXT,
            is_victim       INTEGER DEFAULT 0,
            fraud_channel   TEXT,
            fraud_type      TEXT,
            suspect_phone   TEXT,
            suspect_line_id TEXT,
            suspect_url     TEXT,
            bank_account    TEXT,
            loss_amount     REAL    DEFAULT 0,
            description     TEXT,
            city            TEXT,
            police_station  TEXT,
            status          TEXT    DEFAULT 'pending',
            created_at      TEXT,
            updated_at      TEXT
        )
    """)
    # 索引加速查詢
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_city ON reports(city)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at)")
    conn.commit()
    conn.close()


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_report(user_id: int | None, data: dict) -> int:
    """建立通報，回傳 report_id"""
    now = _now_iso()
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO reports
           (user_id, reporter_name, reporter_phone, reporter_email,
            is_victim, fraud_channel, fraud_type,
            suspect_phone, suspect_line_id, suspect_url, bank_account,
            loss_amount, description, city, police_station,
            status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            user_id,
            data.get("reporter_name", ""),
            data.get("reporter_phone", ""),
            data.get("reporter_email", ""),
            1 if data.get("is_victim") else 0,
            data.get("fraud_channel", ""),
            data.get("fraud_type", ""),
            data.get("suspect_phone", ""),
            data.get("suspect_line_id", ""),
            data.get("suspect_url", ""),
            data.get("bank_account", ""),
            float(data.get("loss_amount", 0) or 0),
            data.get("description", ""),
            data.get("city", ""),
            data.get("police_station", ""),
            "pending",
            now,
            now,
        ),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_report(report_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_reports(
    status: str = "",
    city: str = "",
    search: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict], int]:
    """
    分頁查詢通報，回傳 (rows, total_count)。
    支援狀態、城市篩選與描述文字搜尋。
    """
    conn = _conn()
    where_clauses = []
    params = []

    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if city:
        where_clauses.append("city = ?")
        params.append(city)
    if search:
        where_clauses.append("(description LIKE ? OR reporter_name LIKE ? OR suspect_phone LIKE ?)")
        s = f"%{search}%"
        params.extend([s, s, s])

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    total = conn.execute(f"SELECT COUNT(*) FROM reports{where_sql}", params).fetchone()[0]

    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM reports{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def get_user_reports(user_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM reports WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_status(report_id: int, new_status: str) -> bool:
    if new_status not in REPORT_STATUSES:
        return False
    conn = _conn()
    conn.execute(
        "UPDATE reports SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, _now_iso(), report_id),
    )
    conn.commit()
    conn.close()
    return True


def update_report(report_id: int, data: dict) -> bool:
    """更新通報欄位（管理員用）"""
    allowed = {
        "reporter_name", "reporter_phone", "reporter_email",
        "is_victim", "fraud_channel", "fraud_type",
        "suspect_phone", "suspect_line_id", "suspect_url", "bank_account",
        "loss_amount", "description", "city", "police_station", "status",
    }
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return False
    fields["updated_at"] = _now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [report_id]
    conn = _conn()
    conn.execute(f"UPDATE reports SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def delete_report(report_id: int) -> bool:
    conn = _conn()
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    return True


def get_report_stats() -> dict:
    """通報統計摘要"""
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM reports WHERE status='pending'").fetchone()[0]
    reviewing = conn.execute("SELECT COUNT(*) FROM reports WHERE status='reviewing'").fetchone()[0]
    resolved = conn.execute("SELECT COUNT(*) FROM reports WHERE status='resolved'").fetchone()[0]
    total_loss = conn.execute("SELECT COALESCE(SUM(loss_amount),0) FROM reports").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "pending": pending,
        "reviewing": reviewing,
        "resolved": resolved,
        "total_loss": total_loss,
    }
