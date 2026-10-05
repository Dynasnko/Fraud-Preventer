import html as _html
import json
import sys
import os

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# ── sys.path 修正：讓 AllInOneProject 從任何工作目錄都能 import ────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from nicegui import ui, app

# ── 載入 Agent Bridge ─────────────────────────────────────────────────────────
try:
    from AllInOneProject.Controller.bridge import agent as rag_agent_instance
    print("✅ [AI_assistantWeb] AllInOneProject bridge 載入成功")
except Exception as _e:
    print(f"❌ [AI_assistantWeb] 無法載入 bridge：{_e}")
    rag_agent_instance = None

ui.add_head_html("""
<style>
/* ===== Force every NiceGUI / Quasar wrapper to fill the full viewport ===== */
html, body {
    width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    background: #111827 !important;
    font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
.q-layout {
    width: 100vw !important;
    min-height: 100vh !important;
    background: #111827 !important;
}
.q-page-container, .q-page, .nicegui-content {
    width: 100% !important;
    min-height: 100vh !important;
    flex: 1 !important;
    padding: 0 !important;
    background: #111827 !important;
    display: flex !important;
    flex-direction: column !important;
}

/* ===== Outer centering wrapper ===== */
.app-wrapper {
    width: 100% !important;
    min-height: 100vh !important;
    flex: 1 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 2rem !important;
    box-sizing: border-box !important;
    background: #111827 !important;
}

/* ===== Main bordered container ===== */
.app-container {
    width: 100% !important;
    max-width: 1280px !important;
    height: calc(100vh - 4rem) !important;
    max-height: 900px !important;
    border: 1px solid white !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    display: flex !important;
    flex-direction: column !important;
    box-sizing: border-box !important;
}

/* ===== Navbar ===== */
.nav-bar {
    padding: 1rem 1.5rem !important;
    border-bottom: 1px solid #374151 !important;
    display: flex !important;
    align-items: center !important;
    gap: 0.75rem !important;
    flex-shrink: 0 !important;
    flex-wrap: wrap !important;
    width: 100% !important;
    box-sizing: border-box !important;
}
.nav-link {
    color: white !important;
    cursor: pointer !important;
    font-size: 0.875rem !important;
    transition: color 0.2s !important;
    white-space: nowrap !important;
}
.nav-link:hover { color: #60a5fa !important; }
.nav-sep { color: #9ca3af !important; font-size: 0.875rem !important; }

/* ===== Body split ===== */
.body-layout {
    display: flex !important;
    flex: 1 !important;
    overflow: hidden !important;
    min-height: 0 !important;
    width: 100% !important;
}

/* ===== Left sidebar 25% ===== */
.sidebar {
    width: 25% !important;
    border-right: 1px solid #374151 !important;
    padding: 1.5rem !important;
    display: flex !important;
    flex-direction: column !important;
    flex-shrink: 0 !important;
    box-sizing: border-box !important;
}
.sidebar-title {
    color: white !important;
    text-align: center !important;
    margin-bottom: 1.5rem !important;
    font-size: 1.1rem !important;
    font-weight: 500 !important;
}
.prompt-list {
    display: flex !important;
    flex-direction: column !important;
    gap: 0.75rem !important;
    width: 100% !important;
}
.prompt-btn,
.prompt-btn.q-btn {
    background: #60a5fa !important;
    color: #111827 !important;
    border-radius: 0.5rem !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
    width: 100% !important;
    min-height: unset !important;
    padding: 0.75rem 1rem !important;
    text-transform: none !important;
    box-shadow: none !important;
    justify-content: center !important;
}
.prompt-btn:hover,
.prompt-btn.q-btn:hover { background: #93c5fd !important; }
.prompt-btn .q-btn__content,
.prompt-btn.q-btn .q-btn__content { color: #111827 !important; }
.prompt-btn .q-focus-helper { opacity: 0 !important; }

/* ===== Right chat panel 75% ===== */
.chat-panel {
    width: 75% !important;
    padding: 1.5rem !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 1rem !important;
    overflow: hidden !important;
    min-height: 0 !important;
    box-sizing: border-box !important;
}

/* ===== Single scrollable chat log ===== */
.chat-log {
    flex: 1 !important;
    overflow-y: auto !important;
    min-height: 0 !important;
    width: 100% !important;
    padding: 1rem !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 0.75rem !important;
    box-sizing: border-box !important;
    background: #1f2937 !important;
    border: 1px solid #374151 !important;
    border-radius: 0.5rem !important;
}
/* NiceGUI html() wraps in an extra <div>; display:contents hides it from flex */
.chat-log > div { display: contents !important; }

/* NiceGUI wraps every ui.element / ui.html in an anonymous div inside chat-panel.
   Force those wrappers to fill the panel width so chat-log and input-row are equal. */
.chat-panel > div {
    width: 100% !important;
    box-sizing: border-box !important;
}
/* Inside input-row, collapse NiceGUI wrappers so <input> and button are
   direct flex children and flex:1 on the input works correctly. */
.input-row > div { display: contents !important; }

/* Row wrappers */
.msg-row-user { display: flex !important; justify-content: flex-end !important; width: 100% !important; }
.msg-row-ai   { display: flex !important; justify-content: flex-start !important; width: 100% !important; }

/* Column: constrains max width & stacks label + bubble */
.bubble-col-user {
    display: flex !important;
    flex-direction: column !important;
    align-items: flex-end !important;
    max-width: 72% !important;
    min-width: 0 !important;
}
.bubble-col-ai {
    display: flex !important;
    flex-direction: column !important;
    align-items: flex-start !important;
    max-width: 72% !important;
    min-width: 0 !important;
}

/* Sender label */
.bubble-label {
    font-size: 0.75rem !important;
    margin-bottom: 0.25rem !important;
    color: #9ca3af !important;
    padding: 0 0.25rem !important;
}

/* Bubbles */
.bubble-user {
    background: #2563eb !important;
    color: #fff !important;
    padding: 0.6rem 1rem !important;
    border-radius: 1rem 1rem 0.25rem 1rem !important;
    font-size: 0.9rem !important;
    line-height: 1.6 !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
    display: inline-block !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}
.bubble-ai {
    background: #374151 !important;
    color: #e5e7eb !important;
    padding: 0.6rem 1rem !important;
    border-radius: 1rem 1rem 1rem 0.25rem !important;
    font-size: 0.9rem !important;
    line-height: 1.6 !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
    display: inline-block !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}

/* ===== Input row (stretches to match chat log width) ===== */
.input-row {
    display: flex !important;
    gap: 0.5rem !important;
    align-items: center !important;
    width: 100% !important;
    box-sizing: border-box !important;
    flex-shrink: 0 !important;
}
#chat-input {
    flex: 1 !important;
    background: #1f2937 !important;
    border: 1px solid #374151 !important;
    border-radius: 0.5rem !important;
    padding: 0.65rem 1rem !important;
    color: #f3f4f6 !important;
    font-size: 0.9rem !important;
    font-family: inherit !important;
    outline: none !important;
    min-width: 0 !important;
    box-sizing: border-box !important;
    transition: border-color 0.2s !important;
}
#chat-input::placeholder { color: #6b7280 !important; }
#chat-input:focus { border-color: #60a5fa !important; }

/* ===== Send button ===== */
.send-btn,
.send-btn.q-btn {
    background: #60a5fa !important;
    color: #111827 !important;
    border-radius: 0.5rem !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    white-space: nowrap !important;
    box-shadow: none !important;
    flex-shrink: 0 !important;
    padding: 0.6rem 1.25rem !important;
    min-height: unset !important;
    text-transform: none !important;
}
.send-btn:hover,
.send-btn.q-btn:hover { background: #93c5fd !important; }
.send-btn .q-btn__content { color: #111827 !important; }

/* ===== Thinking (loading) bubble ===== */
.bubble-thinking {
    background: #374151 !important;
    color: #9ca3af !important;
    padding: 0.6rem 1rem !important;
    border-radius: 1rem 1rem 1rem 0.25rem !important;
    font-size: 0.9rem !important;
    line-height: 1.6 !important;
    display: inline-block !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    animation: pulse 1.2s ease-in-out infinite !important;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
}

/* ===== Planner thought collapsible ===== */
.thought-details {
    width: 100% !important;
    margin-bottom: 0.25rem !important;
}
.thought-details summary {
    cursor: pointer !important;
    color: #6b7280 !important;
    font-size: 0.75rem !important;
    padding: 0.25rem 0.5rem !important;
    user-select: none !important;
    list-style: none !important;
}
.thought-details summary::-webkit-details-marker { display: none; }
.thought-details summary::before { content: "▶ "; font-size: 0.65rem; }
.thought-details[open] summary::before { content: "▼ "; }
.thought-details .thought-body {
    background: #1f2937 !important;
    border: 1px solid #374151 !important;
    border-radius: 0.375rem !important;
    padding: 0.5rem 0.75rem !important;
    margin-top: 0.25rem !important;
    color: #9ca3af !important;
    font-size: 0.8rem !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
}

/* ===== Interrupted (system) bubble ===== */
.bubble-system {
    background: #78350f !important;
    color: #fde68a !important;
    padding: 0.6rem 1rem !important;
    border-radius: 1rem 1rem 1rem 0.25rem !important;
    font-size: 0.9rem !important;
    line-height: 1.6 !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
    overflow-wrap: break-word !important;
    display: inline-block !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
}
</style>
<script>
document.addEventListener("DOMContentLoaded", function () {
    document.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && document.activeElement.id === "chat-input") {
            var btn = document.querySelector(".send-btn");
            if (btn) btn.click();
        }
    });
});
</script>
""", shared=True)


# ── 每個連線各自擁有獨立的頁面狀態（chat_log / is_reply 等） ──────────────────
@ui.page("/")
async def index():

    # ── Layout ────────────────────────────────────────────────────────────────
    with ui.element("div").classes("app-wrapper"):
        with ui.element("div").classes("app-container"):

            # ── Navbar ──────────────────────────────────────────────────────
            with ui.element("header").classes("nav-bar"):
                nav_items = [
                    "Home", "Cases", "Advocacy",
                    "Resources", "Report", "Anti-Fraud AI Assistant",
                ]
                for i, item in enumerate(nav_items):
                    ui.html(f'<span class="nav-link">{item}</span>', sanitize=False)
                    if i < len(nav_items) - 1:
                        ui.html('<span class="nav-sep">|</span>', sanitize=False)

            # ── Body ────────────────────────────────────────────────────────
            with ui.element("div").classes("body-layout"):

                # ── Left sidebar ─────────────────────────────────────────
                with ui.element("aside").classes("sidebar"):
                    ui.html('<h2 class="sidebar-title">常用提示詞</h2>', sanitize=False)
                    with ui.element("div").classes("prompt-list"):
                        prompts = [
                            "這是詐騙嗎？",
                            "幫我分析話術",
                            "如何立即處理？",
                            "我該怎麼蒐證？",
                            "有哪些常見案例？",
                        ]
                        for p in prompts:
                            async def fill_prompt(_, text=p):
                                await ui.run_javascript(
                                    f"var el = document.getElementById('chat-input');"
                                    f"if (el) {{ el.value = {json.dumps(text)}; el.focus(); }}"
                                )
                            ui.button(p, on_click=fill_prompt) \
                              .classes("prompt-btn") \
                              .props("unelevated no-caps")

                # ── Right chat panel ─────────────────────────────────────
                with ui.element("main").classes("chat-panel"):

                    chat_log = ui.element("div").classes("chat-log")

                    async def handle_send():
                        text = await ui.run_javascript(
                            'return document.getElementById("chat-input")?.value ?? ""'
                        )
                        text = str(text).strip()
                        if not text:
                            return

                        safe = _html.escape(text)

                        # ── 1. 顯示使用者訊息 ──────────────────────────────
                        with chat_log:
                            ui.html(f'''
<div class="msg-row-user">
  <div class="bubble-col-user">
    <span class="bubble-label">使用者</span>
    <div class="bubble-user">{safe}</div>
  </div>
</div>''', sanitize=False)

                        # ── 2. 顯示 thinking 泡泡（佔位） ─────────────────
                        with chat_log:
                            thinking_el = ui.html('''
<div class="msg-row-ai">
  <div class="bubble-col-ai">
    <span class="bubble-label">AI 助理</span>
    <div class="bubble-thinking">分析中…</div>
  </div>
</div>''', sanitize=False)

                        # ── 3. 清空輸入框並捲動 ────────────────────────────
                        await ui.run_javascript(
                            'document.getElementById("chat-input").value = "";'
                            'var log = document.querySelector(".chat-log");'
                            'if (log) log.scrollTop = log.scrollHeight;'
                        )

                        # ── 4. 無 Agent 時的容錯顯示 ──────────────────────
                        if rag_agent_instance is None:
                            thinking_el.delete()
                            with chat_log:
                                ui.html('''
<div class="msg-row-ai">
  <div class="bubble-col-ai">
    <span class="bubble-label">AI 助理</span>
    <div class="bubble-ai">⚠️ Agent 尚未載入，請確認 AllInOneProject 環境設定。</div>
  </div>
</div>''', sanitize=False)
                            await ui.run_javascript(
                                'var log = document.querySelector(".chat-log");'
                                'if (log) log.scrollTop = log.scrollHeight;'
                            )
                            return

                        # ── 5. 呼叫 Agent ──────────────────────────────────
                        try:
                            user_id  = app.storage.user.get('session_id', 'web_user')
                            is_reply = app.storage.user.get('is_reply', False)

                            response = await rag_agent_instance.ask(
                                user_id=user_id,
                                text=text,
                                is_reply=is_reply,
                            )

                            # ── 6. 移除 thinking 泡泡 ──────────────────────
                            thinking_el.delete()

                            # ── 7. 顯示 Planner 思考過程（可展開） ─────────
                            if response.planner_thought:
                                safe_thought = _html.escape(response.planner_thought)
                                with chat_log:
                                    ui.html(f'''
<div class="msg-row-ai">
  <div class="bubble-col-ai" style="max-width:72%">
    <details class="thought-details">
      <summary>查看規劃思路</summary>
      <div class="thought-body">{safe_thought}</div>
    </details>
  </div>
</div>''', sanitize=False)

                            # ── 8. 顯示 AI 回應 ────────────────────────────
                            safe_resp      = _html.escape(response.response_text)
                            is_interrupted = (response.status == 'interrupted')
                            bubble_cls     = 'bubble-system' if is_interrupted else 'bubble-ai'
                            label_text     = 'System' if is_interrupted else 'AI 助理'

                            # 圖表為工具自行產生的 base64 data URI（非 LLM 自由生成文字），可安全插入 <img src>
                            charts_html = ''.join(
                                f'<img src="{b64}" style="max-width:100%;border-radius:8px;margin-top:8px;display:block;">'
                                for b64 in (response.chart_images or [])
                            )

                            with chat_log:
                                ui.html(f'''
<div class="msg-row-ai">
  <div class="bubble-col-ai">
    <span class="bubble-label">{label_text}</span>
    <div class="{bubble_cls}">{safe_resp}{charts_html}</div>
  </div>
</div>''', sanitize=False)

                            # ── 9. 更新 is_reply 狀態 ──────────────────────
                            app.storage.user['is_reply'] = is_interrupted

                        except Exception as _err:
                            thinking_el.delete()
                            err_safe = _html.escape(str(_err))
                            with chat_log:
                                ui.html(f'''
<div class="msg-row-ai">
  <div class="bubble-col-ai">
    <span class="bubble-label">AI 助理</span>
    <div class="bubble-ai">❌ 系統錯誤：{err_safe}</div>
  </div>
</div>''', sanitize=False)

                        # ── 10. 捲動到底 ───────────────────────────────────
                        await ui.run_javascript(
                            'var log = document.querySelector(".chat-log");'
                            'if (log) log.scrollTop = log.scrollHeight;'
                        )

                    with ui.element("div").classes("input-row"):
                        ui.html(
                            '<input id="chat-input" type="text" '
                            'placeholder="請輸入訊息..." autocomplete="off">',
                            sanitize=False,
                        )
                        ui.button("送出", on_click=handle_send) \
                          .classes("send-btn") \
                          .props("unelevated no-caps")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="Anti-Fraud AI Assistant", port=8080, reload=False, storage_secret="anti_fraud_secret")
