import os
import re
import json
import sqlite3
import pathlib
from typing import Iterable

from langchain_core.tools import StructuredTool

DEFAULT_FORBIDDEN_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "ATTACH", "PRAGMA", "VACUUM", "REINDEX")

# 比對關鍵字前先把字串常值內容清空，避免 LIKE '%update%' 這類合法查詢被誤判為修改指令。
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


def _run_readonly_query(db_path: str, sql_query: str, forbidden_keywords: Iterable[str]) -> str:
    if not os.path.exists(db_path):
        return "錯誤：找不到資料庫檔案，請先確認資料同步已完成。"

    sql_without_literals = _STRING_LITERAL_RE.sub("''", sql_query).upper()
    if any(keyword in sql_without_literals for keyword in forbidden_keywords):
        return "錯誤：基於安全考量，此工具僅供唯讀查詢 (SELECT)，禁止執行修改、刪除或附加資料庫等指令。"

    conn = None
    try:
        # 使用 URI 參數開啟唯讀模式 (Read-Only)，確保資料庫絕對安全
        uri = f"{pathlib.Path(os.path.abspath(db_path)).as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()

        cursor.execute(sql_query)
        results = cursor.fetchall()

        if not results:
            return "查詢成功，但資料庫中沒有符合該條件的紀錄。"

        column_names = [description[0] for description in cursor.description]

        # 將結果與欄位名稱打包成 JSON 格式回傳，方便大模型解讀
        output = {"columns": column_names, "data": results}
        return json.dumps(output, ensure_ascii=False)

    except sqlite3.Error as e:
        return f"SQL 執行錯誤: {str(e)}。請檢查您的 SQL 語法是否完全符合 SQLite 標準。"
    finally:
        if conn:
            conn.close()


def make_sql_query_tool(
    name: str,
    description: str,
    db_path: str,
    forbidden_keywords: Iterable[str] = DEFAULT_FORBIDDEN_KEYWORDS,
) -> StructuredTool:
    """依 db_path + schema 描述產生一個唯讀 SQL 查詢工具，供 WorkerNode 掛載使用。"""

    def _query(sql_query: str) -> str:
        return _run_readonly_query(db_path, sql_query, forbidden_keywords)

    return StructuredTool.from_function(func=_query, name=name, description=description)
