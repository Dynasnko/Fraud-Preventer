# legacy_main.py
"""
[LEGACY / 已棄用] 最早期的獨立測試用 UI，僅供手動測試使用。
從 import graph 角度已無任何模組引用此檔案；正式的對話功能已由
main.py 的 /assistant 頁面（透過 Controller/bridge.py 呼叫 AllInOneAgent.ask()）取代。
保留此檔案僅為方便直接對 Controller/agent_system.py 做手動、無 UI 包裝的除錯。
啟動方式不變：python AllInOneProject/View/legacy_main.py（port 8080，與 AI_assistantWeb.py 衝突，不可同時執行）。
"""
import sys
import os

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# 確保 MyBigProject/ 根目錄在 sys.path 中，無論從哪裡執行都能正確 import
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from nicegui import ui, app
import asyncio

# 匯入我們剛寫好的「整體系統」
from AllInOneProject.Controller.agent_system import HolisticAgentSystem

# 初始化系統 (只會跑一次)
agent_system = HolisticAgentSystem()

@ui.page("/")
def main_page():
    ui.label("Holistic Agent Interface").classes("text-2xl font-bold mb-4")

    with ui.column().classes("w-full h-[85vh]"):
        with ui.card().classes("w-full h-full flex flex-col p-4"):
            chat_box = ui.scroll_area().classes("flex-grow w-full border-b mb-4 p-2")
            # 狀態列可以用來顯示 Planner 的思考
            status_label = ui.label("就緒").classes("text-xs text-gray-400 h-6")

            with ui.row().classes("w-full items-center gap-2"):
                inp = ui.input(placeholder="輸入您的需求...").classes("flex-1").props("outlined rounded")
                btn = ui.button("送出", icon="send").props("color=primary")

    async def send():
        user_text = inp.value.strip()
        if not user_text: return

        inp.value = ""
        with chat_box:
            ui.chat_message(user_text, name="You", sent=True).classes("bg-blue-50")

        status_label.text = "思考中..."
        spinner = ui.spinner("dots", size="lg").classes("absolute center-screen z-10")

        # 1. 準備參數
        thread_id = app.storage.user.get("thread_id")
        # 判斷是否為「回答追問模式」
        is_resume = app.storage.user.get("awaiting_input", False)

        try:
            # 2. 🔥 呼叫系統 (這就是您要的「整體調用」)
            # 透過 run_in_executor 把同步的 process_request 放到背景跑，避免卡住 UI
            result = await asyncio.to_thread(
                agent_system.process_request,
                user_text,
                thread_id,
                is_resume
            )

            # 3. 處理回傳結果 (AgentResponse 物件)

            # 更新 Session ID
            app.storage.user["thread_id"] = result.thread_id

            # 顯示思考過程 (如果有的話)
            if result.planner_thought:
                status_label.text = f"規劃: {result.planner_thought[:30]}..."
                with chat_box:
                    ui.label(f"🧠 思維: {result.planner_thought}").classes("text-xs text-gray-500 italic ml-4")

            # 顯示回答
            msg_color = "bg-green-50"
            sender_name = "Agent"

            if result.status == "interrupted":
                msg_color = "bg-yellow-100" # 追問用黃色
                sender_name = "System"
                app.storage.user["awaiting_input"] = True # 標記下次為 Resume 模式
                status_label.text = "等待您的補充..."

            elif result.status == "error":
                msg_color = "bg-red-100"
                status_label.text = "發生錯誤"
                app.storage.user["awaiting_input"] = False

            else: # completed
                status_label.text = "完成"
                app.storage.user["awaiting_input"] = False # 重置為一般模式

            with chat_box:
                ui.chat_message(result.response_text, name=sender_name, sent=False).classes(msg_color)

        except Exception as e:
            status_label.text = "系統通訊錯誤"
            ui.notify(str(e), type="negative")

        finally:
            spinner.delete()
            chat_box.scroll_to(percent=1.0)

    btn.on_click(send)
    inp.on("keydown.enter", send)

if __name__ in {"__main__", "__mp_main__"}:
    print("🚀 啟動介面...")
    ui.run(title="Holistic Agent", storage_secret="secret", port=8080, reload=False)
