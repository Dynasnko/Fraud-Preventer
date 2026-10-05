import sys
import os
import asyncio
from typing import Any, Dict, List, Optional, Tuple

# 確保 MyBigProject/ 根目錄在 sys.path 中，無論從哪裡 import 都能正確解析
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from AllInOneProject.Controller.agent_system import HolisticAgentSystem
from AllInOneProject.Agent.rag_builder import drop_worker_vectors
from AllInOneProject.Model.config import RAG_ROOT_DIR
from AllInOneProject.Model.worker_config import (
    get_user_created_workers,
    add_user_created_worker,
    rename_user_created_worker,
    remove_user_created_worker,
    get_disabled_workers,
    set_worker_disabled,
)


_INVALID_NAME_CHARS = '/\\:*?"<>|'


def _check_worker_name(name: str) -> str:
    """回傳錯誤訊息；合法則回傳空字串。

    名稱同時是 rag_docs/<名稱>/ 與 chroma_dbs/<名稱>/ 的資料夾名：含路徑字元會寫到目錄外，
    _ 開頭會與 _merged 等系統向量庫衝突，. 開頭則與隱藏檔 / 備份資料夾混淆。
    """
    if not name:
        return "❌ Worker 名稱不可為空"
    if name.startswith((".", "_")) or any(c in name for c in _INVALID_NAME_CHARS):
        return f"❌ Worker 名稱不可以 . 或 _ 開頭，也不可包含 {' '.join(_INVALID_NAME_CHARS)}"
    return ""


async def _drop_vectors_quietly(name: str) -> None:
    """清空向量庫；失敗只記錄，不影響操作結果（下次啟動時仍會清除過時的資料夾）。"""
    try:
        await asyncio.to_thread(drop_worker_vectors, name)
    except Exception as e:
        print(f"⚠️ [Worker] 清空「{name}」向量庫失敗：{e}")


class AllInOneAgent:
    _instance = None

    def __init__(self):
        self.core = HolisticAgentSystem()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def ask(self, user_id: str, text: str, is_reply: bool = False, on_step=None,
                  analysis_request: Optional[Dict[str, Any]] = None):
        """
        給 UI 呼叫的唯一方法。
        自動處理了 thread_id, asyncio 轉換。
        on_step: 可選的 callback(step_type, detail)，即時回報中間狀態。
        analysis_request: 「數據分析請求」表單的結構化參數（資料、統計項目、圖表、欄位），
            數據分析專家會直接照參數執行，不靠 LLM 從文字判斷。
        """
        return await asyncio.to_thread(
            self.core.process_request,
            user_input=text,
            thread_id=user_id,
            is_resume=is_reply,
            on_step=on_step,
            analysis_request=analysis_request,
        )

    async def create_worker(
        self,
        name: str,
        description: str,
        file_data: List[Tuple[str, bytes]],
    ) -> str:
        """建立新 Worker 資料夾結構並觸發 graph 重建。回傳結果訊息。"""
        name = name.strip()
        if err := _check_worker_name(name):
            return err

        worker_dir = os.path.join(RAG_ROOT_DIR, name)
        knowledge_dir = os.path.join(worker_dir, "Domain_Knowledge")

        if os.path.exists(worker_dir):
            return f"❌ Worker「{name}」已存在"

        # 同名 Worker 以前可能存在過（刪除或改名），先清掉殘留向量，避免沿用舊內容
        await _drop_vectors_quietly(name)

        try:
            os.makedirs(knowledge_dir, exist_ok=True)

            with open(os.path.join(worker_dir, "description.txt"), "w", encoding="utf-8") as f:
                f.write(description.strip())

            for filename, content in file_data:
                safe_name = os.path.basename(filename)
                with open(os.path.join(knowledge_dir, safe_name), "wb") as f:
                    f.write(content)

            add_user_created_worker(name)
            await asyncio.to_thread(HolisticAgentSystem.rebuild)
            return f"✅ Worker「{name}」已建立並完成載入"
        except Exception as e:
            # 回復原狀，避免留下半建立的資料夾導致重試時被判定「已存在」
            import shutil
            remove_user_created_worker(name)
            shutil.rmtree(worker_dir, ignore_errors=True)
            # 重建失敗時新 graph 未啟用，可安全清掉可能已寫入一半的向量
            await _drop_vectors_quietly(name)
            return f"❌ 建立失敗：{e}"

    def toggle_worker(self, worker_id: str, enabled: bool) -> None:
        """啟用或停用指定 worker（即時生效，不需重建）。"""
        set_worker_disabled(worker_id, not enabled)

    def get_worker_description(self, name: str) -> str:
        """讀取指定 worker 的 description.txt 內容。"""
        path = os.path.join(RAG_ROOT_DIR, name, "description.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def get_worker_files(self, name: str) -> List[str]:
        """列出指定 worker 的知識文件（相對於 Domain_Knowledge 的路徑）。"""
        knowledge_dir = os.path.join(RAG_ROOT_DIR, name, "Domain_Knowledge")
        return sorted(
            os.path.relpath(os.path.join(root, f), knowledge_dir)
            for root, _, files in os.walk(knowledge_dir)
            for f in files
        )

    async def update_worker(
        self,
        name: str,
        new_description: str,
        new_name: str = "",
        add_files: Optional[List[Tuple[str, bytes]]] = None,
        remove_files: Optional[List[str]] = None,
    ) -> str:
        """更新 description.txt、新增/移除知識文件，可選改名（重新命名目錄）並重建 Agent。

        移除的檔案會在重建時由 RAG builder 一併清除其向量。
        """
        new_name = new_name.strip() or name
        old_dir = os.path.join(RAG_ROOT_DIR, name)
        new_dir = os.path.join(RAG_ROOT_DIR, new_name)
        knowledge_dir = os.path.join(old_dir, "Domain_Knowledge")
        add_files = add_files or []
        remove_files = remove_files or []

        if not os.path.exists(old_dir):
            return f"❌ Worker「{name}」不存在"
        if new_name != name:
            if err := _check_worker_name(new_name):
                return err
            if os.path.exists(new_dir):
                return f"❌ Worker「{new_name}」已存在"

        # 全部驗證完才動磁碟，避免只做一半
        existing = {os.path.normcase(f): f for f in self.get_worker_files(name)}
        for rel in remove_files:
            if os.path.normcase(rel) not in existing:
                return f"❌ 檔案「{rel}」不存在"
        # 同路徑覆寫不會觸發重新 embedding（增量更新以路徑判斷），所以不允許同名
        seen = set()
        for filename, _ in add_files:
            key = os.path.normcase(os.path.basename(filename))
            if key in existing or key in seen:
                return f"❌ 檔案「{os.path.basename(filename)}」已存在，請先移除並儲存後再上傳"
            seen.add(key)

        try:
            for rel in remove_files:
                os.remove(os.path.join(knowledge_dir, existing[os.path.normcase(rel)]))
            if add_files:
                os.makedirs(knowledge_dir, exist_ok=True)
            for filename, content in add_files:
                with open(os.path.join(knowledge_dir, os.path.basename(filename)), "wb") as f:
                    f.write(content)

            if new_name != name:
                await _drop_vectors_quietly(new_name)  # 新名稱可能有以前留下的殘留向量
                os.rename(old_dir, new_dir)
                rename_user_created_worker(name, new_name)

            desc_path = os.path.join(new_dir, "description.txt")
            with open(desc_path, "w", encoding="utf-8") as f:
                f.write(new_description.strip())

            await asyncio.to_thread(HolisticAgentSystem.rebuild)
            if new_name != name:
                # 新 graph 已改用新名稱的向量庫，舊的不再被引用
                await _drop_vectors_quietly(name)
            return f"✅ Worker「{new_name}」已更新"
        except Exception as e:
            return f"❌ 更新失敗：{e}"

    async def delete_worker(self, name: str) -> str:
        """從追蹤清單移除 worker，刪除磁碟資料夾，並重建 Agent。"""
        import shutil
        worker_dir = os.path.join(RAG_ROOT_DIR, name)
        try:
            remove_user_created_worker(name)
            if os.path.exists(worker_dir):
                await asyncio.to_thread(shutil.rmtree, worker_dir)
            await asyncio.to_thread(HolisticAgentSystem.rebuild)
            await _drop_vectors_quietly(name)  # 新 graph 已不含此 Worker
            return f"✅ Worker「{name}」已刪除"
        except Exception as e:
            return f"❌ 刪除失敗：{e}"

    def get_user_worker_status(self) -> List[dict]:
        """回傳使用者新增的 worker 清單及其啟用狀態。"""
        disabled = get_disabled_workers()
        return [
            {
                "name": name,
                "worker_id": f"worker_{name}",
                "enabled": f"worker_{name}" not in disabled,
            }
            for name in get_user_created_workers()
        ]


# 預先建立一個全域物件，方便外部 import
agent = AllInOneAgent.get_instance()
