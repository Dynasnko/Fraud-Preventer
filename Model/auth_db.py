"""
使用者認證 SQLite3 資料庫操作模組
DB 路徑: AllInOneProject/chroma_dbs/auth.sqlite3
"""
import sqlite3
import os
import bcrypt
from datetime import datetime, timezone

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "AllInOneProject", "chroma_dbs", "auth.sqlite3",
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _conn():
    """建立一個帶 WAL 模式的連線（提升併發讀寫效能）"""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ── 初始化 ───────────────────────────────────────────────────────────────────

def init_db():
    """建表 + 預設 admin 帳號（冪等）"""
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    UNIQUE NOT NULL,
            password_hash TEXT   NOT NULL,
            display_name TEXT,
            email        TEXT,
            role         TEXT    DEFAULT 'user',
            created_at   TEXT,
            is_active    INTEGER DEFAULT 1
        )
    """)
    conn.commit()

    # 預設管理員（若不存在才建）
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?", ("admin",)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("admin", _hash_password("admin123"), "系統管理員", "admin", _now_iso()),
        )
        conn.commit()
        print("[auth_db] 預設管理員已建立 (admin / admin123)")
    conn.close()


# ── CRUD ─────────────────────────────────────────────────────────────────────

def create_user(
    username: str,
    password: str,
    display_name: str = "",
    email: str = "",
    role: str = "user",
) -> int | None:
    """建立使用者，成功回傳 user_id，帳號重複回傳 None"""
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, display_name, email, role, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, _hash_password(password), display_name, email, role, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def verify_user(username: str, password: str) -> dict | None:
    """驗證帳密，成功回傳 user dict，失敗回傳 None"""
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
    ).fetchone()
    conn.close()
    if row and _check_password(password, row["password_hash"]):
        return dict(row)
    return None


def get_user(user_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users() -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, username, display_name, email, role, created_at, is_active "
        "FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user(user_id: int, **kwargs) -> bool:
    """更新使用者欄位（支援 display_name, email, role, is_active）"""
    allowed = {"display_name", "email", "role", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [user_id]
    conn = _conn()
    conn.execute(f"UPDATE users SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def toggle_active(user_id: int) -> bool:
    """切換帳號啟用/停用"""
    conn = _conn()
    conn.execute(
        "UPDATE users SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()
    return True


def change_password(user_id: int, new_password: str) -> bool:
    conn = _conn()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (_hash_password(new_password), user_id),
    )
    conn.commit()
    conn.close()
    return True
