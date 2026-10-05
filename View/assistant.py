from nicegui import ui
import html as _html
import json
import io
import time
from collections import deque
import pandas as pd
from nicegui import ui, app, context
from View.components import render_navbar
from AllInOneProject.Agent.tools.data_analysis_tools import parse_tabular_data
from Controller.auth_middleware import require_login
from datetime import datetime

try:
    import sys, os
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    from AllInOneProject.Controller.bridge import agent as rag_agent_instance
except Exception as e:
    import traceback
    traceback.print_exc()
    rag_agent_instance = None


class ChipToggle:
    """二選一切換元件，樣式跟管理後台通報狀態選單同一套藥丸按鈕。
    不用 Quasar 的 ui.switch/ui.toggle：這個環境下它們內部圓形滑塊的定位會跑掉，
    看起來完全不像個開關；改用純按鈕實作，外觀跟其他頁面一致也比較好看。
    對外仍提供 .value 屬性讀寫，讀寫方式跟原本的 ui.switch 相同，呼叫端不用改。
    """
    def __init__(self, options=('否', '是'), default=None, on_change=None, classes=''):
        self.options = options
        self._value = default if default is not None else options[0]
        self._on_change = on_change
        self._wrap_classes = classes
        self._draw = self._build()
        self._draw()

    def _build(self):
        @ui.refreshable
        def _draw():
            with ui.element('div').classes(f'option-chip-row {self._wrap_classes}'):
                for opt in self.options:
                    cls = 'option-chip selected' if opt == self._value else 'option-chip'
                    def _select(_, o=opt):
                        self._value = o
                        self._draw.refresh()
                        if self._on_change:
                            self._on_change(o)
                    ui.html(f'<button class="{cls}" type="button" onclick="void(0)">{opt}</button>', sanitize=False).on('click', _select)
        return _draw

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v
        self._draw.refresh()

ASSISTANT_CSS = """
<style>
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}

/* ChipToggle：取代 Quasar switch/toggle 的二選一藥丸按鈕（跟管理後台同一套樣式） */
.option-chip-row { display: flex; flex-wrap: wrap; gap: 8px; }
.option-chip {
  background: #fff; border: 1px solid #e2e8f0; color: #475569;
  padding: 6px 14px; border-radius: 999px; font-size: 13.5px; font-weight: 600;
  cursor: pointer; transition: all 0.15s ease; line-height: 1.4;
}
.option-chip:hover { border-color: #f97316; color: #f97316; }
.option-chip.selected {
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  color: #fff; border-color: transparent; box-shadow: 0 2px 8px rgba(234,88,12,0.25);
}
.asst-wrap {
  min-height: 100vh;
  /* 活潑但不失專業的 Mesh Gradient 背景 */
  background: 
    radial-gradient(at 0% 0%, hsla(28, 100%, 94%, 1) 0, transparent 50%), 
    radial-gradient(at 50% 0%, hsla(210, 100%, 96%, 1) 0, transparent 50%), 
    radial-gradient(at 100% 0%, hsla(33, 100%, 92%, 1) 0, transparent 50%);
  background-color: #f8fafc;
  display: flex; flex-direction: column;
  font-family: Inter, sans-serif;
}
.asst-body {
  flex: 1; display: grid;
  /* 整體佈局再放大: 左(360px) | 中(自適應) | 右(300px) */
  grid-template-columns: 360px minmax(0, 1fr) 300px;
  gap: 32px;
  padding: 32px;
  max-height: calc(100vh - 65px);
}

/* 兩側選單的懸浮卡片樣式 */
.sidebar-panel {
  background: rgba(255,255,255,0.6);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.8);
  border-radius: 20px;
  padding: 24px; /* 加大 padding 以避免邊界被吃掉 */
  display: flex; flex-direction: column; gap: 16px;
  box-shadow: 0 4px 24px -4px rgba(0,0,0,0.03);
  overflow-y: auto;
}
.sidebar-title {
  font-size: 18px; font-weight: 700;
  color: #1e293b; letter-spacing: 0.05em;
  display: flex; align-items: center; gap: 8px;
}
.sidebar-title::before {
  content: ''; display: block; width: 4px; height: 16px;
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  border-radius: 4px;
}

/* 中央對話區塊，與輸入框同寬且包覆 */
.chat-container {
  display: flex; flex-direction: column; gap: 16px;
  background: rgba(255,255,255,0.8);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.9);
  border-radius: 24px;
  padding: 20px;
  box-shadow: 0 8px 32px -8px rgba(0,0,0,0.05);
  overflow: hidden;
}
.chat-log {
  flex: 1; overflow-y: auto;
  display: flex; flex-direction: column; gap: 16px;
  padding-right: 8px;
}

/* 滾動條美化 */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 6px; }

/* 訊息氣泡 (字體稍微放大) */
.msg-row-user { display: flex; justify-content: flex-end; width: 100%; }
.msg-row-ai   { display: flex; justify-content: flex-start; width: 100%; }
.bubble-col-user { display: flex; flex-direction: column; align-items: flex-end; max-width: 80%; }
.bubble-col-ai   { display: flex; flex-direction: column; align-items: flex-start; max-width: 80%; }
.bubble-label { font-size: 12px; color: #64748b; margin-bottom: 4px; padding: 0 4px; font-weight: 500; }

.bubble-user {
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  color: #fff;
  padding: 16px 20px; border-radius: 20px 20px 4px 20px;
  font-size: 16.5px; line-height: 1.6;
  box-shadow: 0 4px 12px rgba(234,88,12,0.2);
  word-break: break-word;
}
.bubble-ai {
  background: var(--surface-bg);
  color: var(--txt-pri);
  padding: 12.75px 17px;
  border-radius: 17px 17px 17px 4.25px;
  font-size: 15px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  display: inline-block;
  box-shadow: 0 2px 8px rgba(0,0,0,0.02);
  border: 1px solid var(--border);
}
.bubble-system {
  background: #78350f;
  color: #fde68a;
  padding: 12.75px 17px;
  border-radius: 17px 17px 17px 4.25px;
  font-size: 15px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  display: inline-block;
  box-shadow: 0 2px 8px rgba(0,0,0,0.02);
}
.bubble-thinking {
  background: #f8fafc; color: #f97316;
  border: 1px solid #e2e8f0;
  padding: 16px 20px; border-radius: 20px 20px 20px 4px;
  font-size: 16px; font-weight: 500;
  animation: pulse 1.2s ease-in-out infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

/* ── LLM Markdown 排版氣泡 ─────────────────────────────── */
.md-bubble { white-space: normal; }
.md-bubble .nicegui-markdown > *:first-child { margin-top: 0; }
.md-bubble .nicegui-markdown > *:last-child  { margin-bottom: 0; }
.md-bubble .nicegui-markdown p  { margin: 0 0 8px; }
.md-bubble .nicegui-markdown ul,
.md-bubble .nicegui-markdown ol { margin: 0 0 8px; padding-left: 1.4em; }
.md-bubble .nicegui-markdown li { margin: 2px 0; }
.md-bubble .nicegui-markdown h1,
.md-bubble .nicegui-markdown h2,
.md-bubble .nicegui-markdown h3 { margin: 12px 0 6px; font-weight: 700; line-height: 1.3; }
.md-bubble .nicegui-markdown h1 { font-size: 1.30em; }
.md-bubble .nicegui-markdown h2 { font-size: 1.18em; }
.md-bubble .nicegui-markdown h3 { font-size: 1.06em; }
.md-bubble .nicegui-markdown code {
  background: rgba(148,163,184,0.18); padding: 1px 5px; border-radius: 4px; font-size: 0.88em;
}
.md-bubble .nicegui-markdown pre {
  background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
  overflow-x: auto; margin: 8px 0; font-size: 13px;
}
.md-bubble .nicegui-markdown pre code { background: none; padding: 0; }
.md-bubble .nicegui-markdown table { border-collapse: collapse; margin: 8px 0; font-size: 13.5px; }
.md-bubble .nicegui-markdown th,
.md-bubble .nicegui-markdown td { border: 1px solid var(--border); padding: 6px 10px; }
.md-bubble .nicegui-markdown a { color: #ea580c; text-decoration: underline; }
.md-bubble .nicegui-markdown blockquote {
  margin: 8px 0; padding-left: 12px; border-left: 3px solid #f97316; color: #475569;
}

/* 輸入區塊 (按鈕靠右) */
.input-area {
  display: flex; gap: 12px;
  background: #fff;
  border-radius: 99px;
  padding: 8px 8px 8px 24px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.04);
  border: 1px solid #cbd5e1;
  align-items: center;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-area:focus-within {
  border-color: #f97316;
  box-shadow: 0 0 0 3px rgba(249,115,22,0.15);
}
#asst-input {
  flex: 1; border: none; outline: none;
  background: transparent;
  font-size: 17px; color: #1e293b;
  width: 100%;
}
#asst-input::placeholder { color: #94a3b8; }

.send-btn {
  /* 背景/文字色改由 SUBMIT_BTN_BG 內嵌 style 提供，見 assistant.py 的按鈕呼叫處 */
  border: none;
  border-radius: 99px; padding: 12px 28px;
  font-weight: 600; font-size: 15px;
  cursor: pointer; transition: transform 0.2s, box-shadow 0.2s;
  box-shadow: 0 4px 12px rgba(234,88,12,0.3);
}
.send-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(234,88,12,0.4);
}

/* 進階問答表單樣式 */
.custom-expansion { margin-top: 4px; }
.custom-expansion .q-item {
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  font-weight: 600; color: #1e293b;
  box-shadow: 0 2px 8px rgba(0,0,0,0.02);
  font-size: 16.5px;
}
.custom-expansion .q-expansion-item__content { padding: 24px 16px 20px 16px; }

/* 快速提示樣式 */
.prompt-chip {
  background: #fff;
  border: 1px solid #e2e8f0;
  color: #475569;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 15.5px; font-weight: 500;
  cursor: pointer; text-align: left;
  transition: all 0.2s ease;
  box-shadow: 0 2px 8px rgba(0,0,0,0.01);
  width: 100%;
  white-space: normal;
  word-break: break-word;
  margin-bottom: 6px;
}
.prompt-chip:hover {
  border-color: #f97316; color: #f97316;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(249,115,22,0.1);
}

/* 可多選的小圓角按鈕群組（圖表類型 / 統計項目） */
.option-chip-row {
  display: flex; flex-wrap: wrap; gap: 8px;
}
.option-chip {
  background: #fff;
  border: 1px solid #e2e8f0;
  color: #475569;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  line-height: 1.4;
}
.option-chip:hover {
  border-color: #f97316;
  color: #f97316;
}
.option-chip.selected {
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 2px 8px rgba(234,88,12,0.25);
}

/* 檔案上傳區塊 */
.upload-status {
  font-size: 12.5px; color: #64748b; margin-top: 6px; min-height: 18px;
}

/* 側欄主要按鈕（傳送 / 新增 Worker 等）統一比例，避免各區塊各自調整導致大小不一。
   背景/文字色改由 SUBMIT_BTN_BG 內嵌 style 提供 —— Quasar 的 q-btn 有自己的內建
   背景樣式（非一般外部 stylesheet，連 !important 的 class 規則都蓋不掉），
   只有元素自身的 inline style 能保證蓋過去。 */
.sidebar-submit-btn {
  align-self: flex-start;
  border-radius: 12px !important;
  font-weight: 700;
  padding: 10px 22px !important;
  font-size: 14.5px !important;
  box-shadow: 0 4px 12px rgba(234,88,12,0.25);
}
.sidebar-submit-btn.full-width { align-self: stretch; width: 100%; }

/* Thinking Log 時間軸：每個問題一組，舊的自動收合；長內容以 <details> 收合 */
.tl-panel { display: flex; flex-direction: column; gap: 10px; flex: 1; min-height: 150px; overflow-y: auto; overflow-x: hidden; padding: 2px; }
.tl-empty { color: #94a3b8; font-size: 13.5px; padding: 8px 4px; }
.tl-run { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; flex-shrink: 0; }
.tl-run > summary {
  list-style: none; cursor: pointer; display: flex; align-items: center; gap: 8px;
  padding: 9px 12px; background: #f8fafc; border-bottom: 1px solid #f1f5f9;
}
.tl-run > summary::-webkit-details-marker { display: none; }
.tl-run-head { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; }
.tl-items { display: flex; flex-direction: column; gap: 2px; }
.tl-run:not([open]) > summary { border-bottom: none; }
.tl-run-q { flex: 1; min-width: 0; font-size: 13.5px; font-weight: 600; color: #334155; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl-run-time { font-size: 11.5px; color: #94a3b8; flex-shrink: 0; }
.tl-chip { font-size: 11px; font-weight: 700; border-radius: 999px; padding: 2px 8px; flex-shrink: 0; white-space: nowrap; }
.tl-chip.running { background: #ffedd5; color: #c2410c; }
.tl-chip.done { background: #dcfce7; color: #15803d; }
.tl-chip.interrupted { background: #fef9c3; color: #a16207; }
.tl-chip.error { background: #fee2e2; color: #b91c1c; }
.tl-body { display: flex; flex-direction: column; padding: 8px 10px 10px; gap: 2px; }
.tl-item { border-radius: 8px; }
.tl-item > summary, .tl-item > .tl-line {
  list-style: none; display: flex; align-items: flex-start; gap: 8px; padding: 4px 4px; border-radius: 8px;
}
.tl-item > summary { cursor: pointer; }
.tl-item > summary::-webkit-details-marker { display: none; }
.tl-item > summary:hover { background: #f8fafc; }
.tl-item.sub { margin-left: 22px; }
.tl-icon { font-size: 17px !important; flex-shrink: 0; margin-top: 1px; }
.tl-title { flex: 1; min-width: 0; font-size: 13px; color: #334155; line-height: 1.5; word-break: break-word; }
.tl-item.sub .tl-title { color: #475569; font-size: 12.5px; }
.tl-caret { font-size: 16px !important; color: #cbd5e1; flex-shrink: 0; transition: transform .15s ease; margin-top: 1px; }
.tl-item[open] > summary .tl-caret { transform: rotate(90deg); }
.tl-at { font-size: 11px; color: #94a3b8; flex-shrink: 0; margin-top: 2px; font-variant-numeric: tabular-nums; }
.tl-detail {
  margin: 2px 4px 6px 29px; padding: 8px 10px; background: #f8fafc; border-left: 3px solid #e2e8f0;
  border-radius: 6px; font-size: 12px; color: #475569; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6;
}
.tl-detail.rich { white-space: normal; display: flex; flex-direction: column; gap: 6px; }
.tl-note { font-size: 12px; color: #475569; overflow-wrap: anywhere; }
.tl-note.muted { color: #94a3b8; }
.tl-sub-label { font-size: 11px; font-weight: 700; color: #94a3b8; letter-spacing: .3px; margin-top: 2px; }
.tl-level {
  display: inline-block; margin-left: 6px; font-size: 11px; font-weight: 700; border-radius: 999px;
  padding: 1px 7px; vertical-align: 1px;
}
.tl-level.grounded { background: #dcfce7; color: #15803d; }
.tl-level.partial { background: #fef3c7; color: #b45309; }
.tl-level.ungrounded { background: #fee2e2; color: #b91c1c; }
.tl-cite {
  display: inline-block; flex-shrink: 0; font-size: 10.5px; font-weight: 800; border-radius: 5px;
  padding: 0 5px; line-height: 17px; font-family: ui-monospace, monospace;
}
.tl-cite.local { background: #d1fae5; color: #047857; }
.tl-cite.tool { background: #ccfbf1; color: #0f766e; }
.tl-cite.web { background: #e0f2fe; color: #0369a1; }
.tl-cite.verify { background: #ede9fe; color: #6d28d9; }
.tl-cite.invalid { background: #fee2e2; color: #b91c1c; text-decoration: line-through; }
.tl-cite.none { background: #f1f5f9; color: #94a3b8; font-family: inherit; font-weight: 600; }
.tl-claims { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
.tl-claim { display: flex; flex-direction: column; gap: 3px; padding: 5px 8px; background: #fff; border-radius: 6px; border-left: 3px solid #cbd5e1; }
.tl-claim.local { border-left-color: #10b981; }
.tl-claim.web { border-left-color: #38bdf8; }
.tl-claim.none { border-left-color: #f87171; }
.tl-claim-text { font-size: 12px; color: #334155; line-height: 1.55; }
.tl-cites { display: flex; flex-wrap: wrap; gap: 4px; }
.tl-doc { display: flex; align-items: flex-start; gap: 6px; padding: 5px 6px; background: #fff; border-radius: 6px; }
.tl-rel { flex-shrink: 0; font-size: 11px; font-weight: 700; color: #059669; font-variant-numeric: tabular-nums; line-height: 17px; }
.tl-doc-text { display: flex; flex-direction: column; min-width: 0; }
.tl-doc-name { font-size: 12px; font-weight: 600; color: #334155; overflow-wrap: anywhere; }
.tl-doc-dir { font-size: 11px; color: #94a3b8; overflow-wrap: anywhere; }
.tl-web {
  display: flex; align-items: flex-start; gap: 6px; padding: 6px 8px; background: #fff; border-radius: 6px;
  border: 1px solid #e2e8f0; text-decoration: none; transition: border-color .15s ease;
}
a.tl-web:hover { border-color: #7dd3fc; }
.tl-web-text { display: flex; flex-direction: column; min-width: 0; }
.tl-web-title {
  font-size: 12px; font-weight: 600; color: #334155; line-height: 1.45;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.tl-web-host { font-size: 11px; color: #0284c7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tl-code {
  margin: 0; padding: 6px 8px; background: #fff; border: 1px solid #e2e8f0; border-radius: 6px;
  font-size: 11.5px; color: #334155; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow-y: auto;
}
.tl-title .tl-cite { margin-right: 2px; }
.tl-head-row { display: flex; align-items: center; justify-content: space-between; }
@media (min-width: 1201px) {
  .asst-body.tl-wide { grid-template-columns: 360px minmax(0, 1fr) 560px; }
}
.tl-status { display: flex; align-items: center; gap: 8px; margin-top: 6px; padding: 6px 8px; border-radius: 8px; background: #fff7ed; color: #c2410c; font-size: 12.5px; font-weight: 600; }
.tl-status.done { background: #f0fdf4; color: #15803d; }
.tl-status.interrupted { background: #fefce8; color: #a16207; }
.tl-status.error { background: #fef2f2; color: #b91c1c; }
.tl-spin { width: 12px; height: 12px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: tl-rot .8s linear infinite; flex-shrink: 0; }
@keyframes tl-rot { to { transform: rotate(360deg); } }

/* 新增 / 編輯 Worker 對話框：左欄名稱 + 描述、右欄知識文件；窄螢幕改為上下排列 */
.wk-dialog-body {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px; width: 100%; align-items: stretch;
}
.wk-col { display: flex; flex-direction: column; min-width: 0; }
.wk-label { font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 4px; }
@media (max-width: 760px) {
  .wk-dialog-body { grid-template-columns: minmax(0, 1fr); }
}

/* Worker 知識文件清單（新增 / 編輯 Worker 對話框共用） */
.kf-panel {
  display: flex; flex-direction: column; gap: 10px;
  width: 100%; flex: 1; min-height: 260px;
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 14px;
  padding: 12px;
}
.kf-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.kf-title { font-size: 13px; font-weight: 600; color: #475569; }
.kf-count {
  font-size: 12px; font-weight: 600; color: #64748b;
  background: #fff; border: 1px solid #e2e8f0; border-radius: 999px; padding: 2px 10px;
}
.kf-list { display: flex; flex-direction: column; gap: 6px; flex: 1; max-height: 320px; overflow-y: auto; }
.kf-row {
  display: flex; align-items: center; gap: 10px;
  background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 6px 6px 6px 8px; transition: border-color .15s ease, box-shadow .15s ease;
}
.kf-row:hover { border-color: #fdba74; box-shadow: 0 1px 6px rgba(234,88,12,0.08); }
.kf-row.adding { border-color: #fed7aa; background: #fffbf5; }
.kf-row.removing { background: #f8fafc; }
.kf-row.removing .kf-name { color: #94a3b8; text-decoration: line-through; }
.kf-row.removing .kf-icon { background: #f1f5f9; color: #94a3b8; }
.kf-icon {
  flex-shrink: 0; width: 34px; height: 34px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  background: #fff7ed; color: #ea580c; font-size: 10.5px; font-weight: 800; letter-spacing: .3px;
}
.kf-name {
  flex: 1; min-width: 0; font-size: 14px; color: #334155;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.kf-tag { flex-shrink: 0; font-size: 11.5px; font-weight: 700; border-radius: 999px; padding: 2px 8px; }
.kf-tag.add { background: #ffedd5; color: #c2410c; }
.kf-tag.remove { background: #fee2e2; color: #b91c1c; }
.kf-action { flex-shrink: 0; margin: 0 !important; color: #94a3b8 !important; }
.kf-action.danger:hover { color: #ef4444 !important; }
.kf-hint { font-size: 11.5px; color: #94a3b8; line-height: 1.5; margin-top: -2px; }
.kf-empty {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  border: 1.5px dashed #cbd5e1; border-radius: 10px; padding: 16px 12px;
  color: #94a3b8; font-size: 13px; text-align: center; background: #fff;
}


/* RWD 響應式 */
@media(max-width: 1200px) {
  .asst-body { grid-template-columns: 300px minmax(0, 1fr); }
  .sidebar-right { display: none; }
}
@media(max-width: 768px) {
  .asst-body { grid-template-columns: 1fr; }
  .sidebar-left { display: none; }
}
</style>
<script>
document.addEventListener('DOMContentLoaded',function(){
  document.addEventListener('keydown',function(e){
    if(e.key==='Enter'&&document.activeElement.id==='asst-input'){
      var b=document.querySelector('.send-btn'); if(b) b.click();
    }
  });
});
</script>
"""

# Quasar 的 q-btn 元件內建背景樣式連 CSS class 的 !important 都蓋不掉，
# 只有元素自身的 inline style 才蓋得過去，所以所有橘色按鈕都額外套用這段 inline style。
SUBMIT_BTN_BG = 'background: linear-gradient(135deg, #f97316 0%, #ea580c 100%) !important; color: #fff !important;'
# 新增 / 編輯 Worker 對話框：左右兩欄需要較寬的版面；Quasar dialog 預設 max-width 560px，
# 只有卡片自身的 inline style 蓋得過
WORKER_DIALOG_STYLE = (
    'width:880px; max-width:95vw; max-height:90vh; overflow-y:auto; '
    'padding:28px 28px 20px; display:flex; flex-direction:column; gap:0;'
)

PROMPTS = [
    "這是詐騙嗎？",
    "幫我分析話術",
    "如何立即處理？",
    "我該怎麼蒐證？",
    "有哪些常見案例？",
]

# Thinking Log 各事件的圖示（Material Icons）、顏色與是否為專家底下的子項
_TL_STYLE = {
    "system":           ("play_circle",              "#64748b", False),
    "requirement":      ("fact_check",               "#2563eb", False),
    "interrupt":        ("help",                     "#ca8a04", False),
    "planner":          ("account_tree",             "#7c3aed", False),
    "planner_dispatch": ("groups",                   "#7c3aed", False),
    "planner_task":     ("subdirectory_arrow_right", "#8b5cf6", True),
    "worker_done":      ("engineering",              "#ea580c", False),
    "worker_tool":      ("build",                    "#0d9488", True),
    "worker_rag":       ("menu_book",                "#059669", True),
    "worker_web":       ("travel_explore",           "#0284c7", True),
    "worker_thought":   ("psychology",               "#64748b", True),
    "worker_sources":   ("link",                     "#64748b", True),
    "worker_chart":     ("insert_chart",             "#0d9488", True),
    "composer":         ("rule",                     "#4f46e5", False),
    "synthesizer":      ("auto_awesome",             "#db2777", False),
    "done":             ("check_circle",             "#16a34a", False),
    "error":            ("error",                    "#dc2626", False),
}


_E = _html.escape
_GROUNDING_UI = {  # 依據等級 → (文字, 圖示, 顏色)
    "grounded":   ("有依據",   "verified",       "#16a34a"),
    "partial":    ("部分依據", "rule",           "#d97706"),
    "ungrounded": ("無依據",   "report",         "#dc2626"),
}
_CITE_KIND = {"S": "local", "T": "tool", "W": "web", "V": "verify"}


def _cite_chip(cid: str, valid: bool = True) -> str:
    kind = _CITE_KIND.get(cid[:1], "web") if valid else "invalid"
    tip = "引用的編號不在參考資料中" if not valid else ""
    return f'<span class="tl-cite {kind}" title="{tip}">{_E(cid)}</span>'


def _render_worker_done(d):
    g = d.get("grounding") or {}
    label, icon, color = _GROUNDING_UI.get(g.get("level"), ("依據未知", "help", "#94a3b8"))
    took = f'・{d["elapsed"]:.1f} 秒' if d.get("elapsed") is not None else ''
    title = (f'{_E(d.get("name", ""))} 完成'
             f'<span class="tl-level {g.get("level", "")}">{label}</span>{took}')
    parts = [f'<div class="tl-note">{_E(g.get("reason", ""))}</div>',
             f'<div class="tl-note muted">模型自評 {d.get("llm_score", 0):.0%}（僅供參考）</div>']
    claims = g.get("claims") or []
    if claims:
        rows = []
        for c in claims:
            valid = set(c.get("valid_ids", []))
            chips = ''.join(_cite_chip(i, i in valid) for i in c.get("source_ids", [])) \
                or '<span class="tl-cite none">無引用</span>'
            dot = 'local' if c.get("local") else ('web' if valid else 'none')
            rows.append(f'<li class="tl-claim {dot}"><span class="tl-claim-text">{_E(c.get("text", ""))}</span>'
                        f'<span class="tl-cites">{chips}</span></li>')
        parts.append(f'<div class="tl-sub-label">回答重點與引用</div><ul class="tl-claims">{"".join(rows)}</ul>')
    return title, ''.join(parts), (icon, color)


def _render_worker_rag(d):
    used = d.get("used") or []
    title = (f'知識庫檢索：採用 {len(used)}/{d.get("candidates", 0)} 筆'
             f'・最佳關聯度 {d.get("best", 0):.2f}')
    if not used:
        return title, '<div class="tl-note">沒有片段通過相關度門檻，改用網路搜尋。</div>', None
    rows = []
    if d.get("mode") == "local+web":
        rows.append('<div class="tl-note">本地依據偏弱，另外搜尋網路補充。</div>')
    for doc in used:
        src = doc.get("source", "")
        folder, _, name = src.rpartition('/')
        rows.append(
            f'<div class="tl-doc" title="{_E(src)}">{_cite_chip(doc.get("id", "S?"))}'
            f'<span class="tl-rel">{doc.get("relevance", 0):.2f}</span>'
            f'<div class="tl-doc-text"><span class="tl-doc-name">{_E(name or src)}</span>'
            f'<span class="tl-doc-dir">{_E(folder)}</span></div></div>'
        )
    return title, ''.join(rows), None


def _render_worker_web(d):
    kind = "法條驗證搜尋" if d.get("kind") == "verify" else "網路搜尋"
    results = d.get("results") or []
    title = f'{kind}：{len(results)} 筆・{d.get("sec", 0):.1f} 秒'
    parts = [f'<div class="tl-note">查詢：{_E(d.get("query", ""))}</div>']
    for it in results:
        url = it.get("url", "")
        host = url.split('//', 1)[-1].split('/', 1)[0] if url else ''
        inner = (f'{_cite_chip(it.get("id", "W?"))}<div class="tl-web-text">'
                 f'<span class="tl-web-title">{_E(it.get("title", "") or url)}</span>'
                 f'<span class="tl-web-host">{_E(host)}</span></div>')
        if url.startswith(("http://", "https://")):
            parts.append(f'<a class="tl-web" href="{_E(url)}" title="{_E(url)}" target="_blank" '
                         f'rel="noopener noreferrer">{inner}</a>')
        else:
            parts.append(f'<div class="tl-web">{inner}</div>')
    return title, ''.join(parts), None


def _render_worker_tool(d):
    fail = '' if d.get("ok") else '<span class="tl-level ungrounded">失敗</span>'
    title = (f'{_cite_chip(d.get("id", "T?"))} 工具 {_E(d.get("name", ""))}'
             f'・{d.get("sec", 0):.1f} 秒{fail}')
    args = json.dumps(d.get("args", {}), ensure_ascii=False, indent=1)
    body = (f'<div class="tl-sub-label">參數</div><pre class="tl-code">{_E(args)}</pre>'
            f'<div class="tl-sub-label">結果</div><pre class="tl-code">{_E(d.get("result", ""))}</pre>')
    return title, body, None


_TL_RENDERERS = {
    "worker_done": _render_worker_done,
    "worker_rag": _render_worker_rag,
    "worker_web": _render_worker_web,
    "worker_tool": _render_worker_tool,
}


class ThinkingLog:
    """右側 Thinking Log：每個問題一組時間軸，舊的自動收合。

    Agent 在背景執行緒透過 on_step 回報事件，這裡只把事件放進佇列（thread-safe），
    由頁面上的 ui.timer 在主事件迴圈中取出繪製，避免跨執行緒直接操作 UI 元素。
    事件 detail 慣例：第一行為標題，其餘行為可展開內容（見 agent_system._emit）。
    """
    MAX_RUNS = 20

    def __init__(self):
        self._queue: deque = deque()
        self._runs: list = []
        self._run = None
        self.panel = ui.element('div').classes('tl-panel')
        with self.panel:
            self._empty = ui.label('提問後，這裡會即時顯示 Agent 的分析過程。').classes('tl-empty')
        ui.timer(0.25, self.drain)

    # ── 背景執行緒呼叫 ──
    def on_step(self, step_type: str, detail: str, data=None) -> None:
        self._queue.append((time.time(), step_type, detail, data))

    # ── 以下皆在主事件迴圈執行 ──
    def start_run(self, question: str) -> None:
        self.drain()
        if self._empty is not None:
            self._empty.delete()
            self._empty = None
        for old in self._runs:
            old["el"].props(remove='open')  # 舊問題收合，需要時可點開
        q = question.strip().replace('\n', ' ')
        with self.panel:
            # <summary> 必須是 <details> 的直接子元素，原生收合才會生效（ui.html 外層會多包一個 div）
            el = ui.element('details').classes('tl-run').props('open')
            with el:
                with ui.element('summary'):
                    head = ui.html('', sanitize=False).classes('tl-run-head')
                with ui.element('div').classes('tl-body'):
                    items = ui.element('div').classes('tl-items')
                    status = ui.html('', sanitize=False)  # 狀態列固定在所有事件之後
        self._run = {
            "el": el, "head": head, "items": items, "status": status,
            "q": q, "t0": time.time(), "clock": datetime.now().strftime('%H:%M:%S'),
            "n_workers": None, "n_done": 0,
        }
        self._runs.append(self._run)
        while len(self._runs) > self.MAX_RUNS:
            self._runs.pop(0)["el"].delete()
        self._set_state('running', '分析需求中⋯')
        self._scroll()

    def finish_run(self, status: str) -> None:
        self.drain()
        run = self._run
        if run is None:
            return
        took = time.time() - run["t0"]
        if status == 'completed':
            self._set_state('done', f'完成・總耗時 {took:.1f} 秒')
        elif status == 'interrupted':
            self._set_state('interrupted', f'需要補充資訊・{took:.1f} 秒')
        else:
            self._set_state('error', f'發生錯誤・{took:.1f} 秒')
        self._run = None

    def drain(self) -> None:
        while self._queue:
            ts, step_type, detail, data = self._queue.popleft()
            if self._run is not None:
                self._add_item(ts, step_type, detail, data)

    def _add_item(self, ts: float, step_type: str, detail: str, data=None) -> None:
        run = self._run
        icon, color, sub = _TL_STYLE.get(step_type, ("circle", "#94a3b8", False))
        title, _, rest = (detail or '').strip().partition('\n')
        at = f'+{ts - run["t0"]:.1f}s'
        cls = 'tl-item sub' if sub else 'tl-item'
        t = _html.escape(title)
        body = _html.escape(rest.strip())
        # 有結構化資料的事件改用專屬排版（標題 / 內容皆已處理 HTML 跳脫）
        renderer = _TL_RENDERERS.get(step_type) if data else None
        if renderer:
            t, body, icon_override = renderer(data)
            if icon_override:
                icon, color = icon_override
            body_html = f'<div class="tl-detail rich">{body}</div>' if body else ''
        else:
            body_html = f'<div class="tl-detail">{body}</div>' if body else ''
        icon_html = f'<i class="q-icon notranslate material-icons tl-icon" style="color:{color}">{icon}</i>'
        if body_html:
            html_ = (f'<details class="{cls}"><summary>{icon_html}<span class="tl-title">{t}</span>'
                     f'<span class="tl-at">{at}</span>'
                     f'<i class="q-icon notranslate material-icons tl-caret">chevron_right</i></summary>'
                     f'{body_html}</details>')
        else:
            html_ = (f'<div class="{cls}"><div class="tl-line">{icon_html}<span class="tl-title">{t}</span>'
                     f'<span class="tl-at">{at}</span></div></div>')
        with run["items"]:
            ui.html(html_, sanitize=False)
        self._update_progress(step_type, detail)
        self._scroll()

    def _update_progress(self, step_type: str, detail: str) -> None:
        run = self._run
        if step_type == 'requirement':
            self._set_state('running', '規劃任務中⋯')
        elif step_type == 'planner_dispatch':
            try:
                run["n_workers"] = int(detail.split('分派 ', 1)[1].split(' ', 1)[0])
            except (IndexError, ValueError):
                run["n_workers"] = None
            run["n_done"] = 0
            self._set_state('running', self._worker_progress())
        elif step_type == 'worker_done':
            run["n_done"] += 1
            if run["n_workers"] and run["n_done"] >= run["n_workers"]:
                self._set_state('running', '品質評估中⋯')
            else:
                self._set_state('running', self._worker_progress())
        elif step_type == 'composer':
            if detail.startswith('品質不足'):
                run["n_workers"], run["n_done"] = None, 0
                self._set_state('running', '重新執行專家中⋯')
            else:
                self._set_state('running', '整合回答中⋯')
        elif step_type == 'synthesizer':
            self._set_state('running', '整合回答中⋯')

    def _worker_progress(self) -> str:
        run = self._run
        n = run["n_workers"]
        return f'專家執行中⋯（{run["n_done"]}/{n}）' if n else f'專家執行中⋯（已完成 {run["n_done"]}）'

    def _set_state(self, state: str, text: str) -> None:
        run = self._run
        chip = {'running': '進行中', 'done': '完成', 'interrupted': '待補充', 'error': '錯誤'}[state]
        run["head"].set_content(
            f'<span class="tl-run-q" title="{_html.escape(run["q"])}">{_html.escape(run["q"])}</span>'
            f'<span class="tl-run-time">{run["clock"]}</span><span class="tl-chip {state}">{chip}</span>'
        )
        spin = '<span class="tl-spin"></span>' if state == 'running' else ''
        run["status"].set_content(f'<div class="tl-status {"" if state == "running" else state}">{spin}{_html.escape(text)}</div>')

    def _scroll(self) -> None:
        ui.run_javascript(f'var p=getHtmlElement({self.panel.id});if(p)p.scrollTop=p.scrollHeight;')


@ui.page("/assistant")
@require_login
async def assistant_page():
    from nicegui import app
    # 讓 Quasar 元件（switch、checkbox 等未特別指定顏色的元件）預設就採用品牌橘色，
    # 而不是 Quasar 內建的預設藍色（#5898d4）。
    ui.colors(primary='#f97316')
    ui.add_head_html(ASSISTANT_CSS, shared=False)
    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch !h-screen')
    ui.query('.q-page').classes('min-h-screen')

    def _style_upload_as_button(upload_element):
        """
        ui.upload() 預設渲染成 Quasar QUploader：標題文字、位元組/百分比副標與實際可點的
        小圖示按鈕各自散落，還會保留一個空的檔案清單區塊，長得完全不像其他按鈕。
        這裡直接對掛載後的子元素套用 inline style（唯一蓋得過 Quasar 內建樣式的方式），
        把整個標題列改造成跟其他橘色按鈕一致的外觀，並讓隱藏的原生 file input 覆蓋滿版
        以保持可點擊範圍不變。用 requestAnimationFrame 重試是因為 Quasar 元件掛載是非同步的。
        """
        ui.run_javascript(f'''
        (function retryStyle(tries) {{
            const root = getHtmlElement({upload_element.id});
            const header = root && root.querySelector('.q-uploader__header');
            if (!header) {{
                if (tries > 0) requestAnimationFrame(() => retryStyle(tries - 1));
                return;
            }}
            const subtitle = root.querySelector('.q-uploader__subtitle');
            const list = root.querySelector('.q-uploader__list');
            const btn = root.querySelector('.q-uploader__header .q-btn');
            const title = root.querySelector('.q-uploader__title');

            root.style.setProperty('border', 'none', 'important');
            root.style.setProperty('box-shadow', 'none', 'important');
            root.style.setProperty('background', 'transparent', 'important');

            header.style.setProperty('background', 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)', 'important');
            header.style.setProperty('border-radius', '10px', 'important');
            header.style.setProperty('position', 'relative', 'important');
            header.style.setProperty('min-height', '40px', 'important');
            header.style.setProperty('display', 'flex', 'important');
            header.style.setProperty('align-items', 'center', 'important');
            header.style.setProperty('justify-content', 'center', 'important');
            header.style.setProperty('cursor', 'pointer', 'important');

            if (subtitle) subtitle.style.setProperty('display', 'none', 'important');
            if (list) list.style.setProperty('display', 'none', 'important');
            if (title) {{
                title.style.setProperty('color', '#fff', 'important');
                title.style.setProperty('font-weight', '700', 'important');
                title.style.setProperty('font-size', '14px', 'important');
            }}
            if (btn) {{
                btn.style.setProperty('position', 'absolute', 'important');
                btn.style.setProperty('inset', '0', 'important');
                btn.style.setProperty('width', '100%', 'important');
                btn.style.setProperty('height', '100%', 'important');
                btn.style.setProperty('opacity', '0', 'important');
                btn.style.setProperty('cursor', 'pointer', 'important');
            }}
        }})(60);
        ''')

    class KnowledgeFileList:
        """新增 / 編輯 Worker 對話框共用的知識文件清單。

        既有檔案可標記「將移除」（可復原），新選的檔案逐一列出並可個別取消。
        只記錄變更，實際寫入由呼叫端在按下新增 / 儲存時交給 bridge 一次處理。
        """

        def __init__(self, existing, on_error):
            self.existing = list(existing)
            self.to_remove: set = set()
            self.to_add: list = []  # [(檔名, bytes)]
            self._on_error = on_error
            with ui.element('div').classes('kf-panel'):
                with ui.element('div').classes('kf-header'):
                    ui.label('知識文件').classes('kf-title')
                    self._count = ui.label('').classes('kf-count')
                self._list = ui.element('div').classes('kf-list')
                # batch 模式：一次選取的檔案在 on_multi_upload 一起送達，處理完再 reset，
                # 否則 QUploader 會記住已選過的檔案，取消後再選同一個檔案會被靜默忽略
                self._upload = ui.upload(
                    multiple=True,
                    on_multi_upload=self._handle_upload,
                    on_rejected=lambda: on_error('❌ 檔案不符合條件（僅支援 .txt / .md）'),
                    auto_upload=True,
                    label='＋ 選擇檔案（.txt / .md，可多選）',
                ).classes('w-full').props('accept=".txt,.md" flat bordered')
                _style_upload_as_button(self._upload)
                ui.label('※ 同名檔案無法直接覆蓋：請先移除舊檔並儲存，再上傳新版本').classes('kf-hint')
            self.render()

        async def _handle_upload(self, e):
            # 同名檔案覆寫不會觸發重新 embedding（增量更新以路徑判斷），一律擋下
            taken = {n.lower() for n in self.existing} | {n.lower() for n, _ in self.to_add}
            skipped = []
            for f in e.files:
                if f.name.lower() in taken:
                    skipped.append(f.name)
                    continue
                self.to_add.append((f.name, await f.read()))
                taken.add(f.name.lower())
            self._upload.reset()
            self._on_error(
                f'❌ 已略過同名檔案：{"、".join(skipped)}（既有檔案請先移除並儲存後再上傳）' if skipped else ''
            )
            self.render()

        def _toggle_remove(self, name: str):
            self.to_remove.symmetric_difference_update({name})
            self.render()

        def _cancel_add(self, name: str):
            self.to_add = [f for f in self.to_add if f[0] != name]
            self.render()

        def _row(self, name: str, state: str, on_click):
            ext = name.rsplit('.', 1)[-1].upper() if '.' in name else 'FILE'
            icon, tip, extra = {
                '':         ('delete_outline', '移除', ' danger'),
                'removing': ('undo', '復原', ''),
                'adding':   ('close', '取消新增', ' danger'),
            }[state]
            with ui.element('div').classes(f'kf-row {state}'):
                ui.label(ext[:4]).classes('kf-icon')
                ui.label(name).classes('kf-name').tooltip(name)
                if state == 'adding':
                    ui.label('新增').classes('kf-tag add')
                elif state == 'removing':
                    ui.label('將移除').classes('kf-tag remove')
                ui.button(icon=icon, on_click=on_click).props('flat round dense size=sm') \
                    .classes('kf-action' + extra).tooltip(tip)

        def render(self):
            kept = len(self.existing) - len(self.to_remove)
            total = kept + len(self.to_add)
            changes = []
            if self.to_add:
                changes.append(f'+{len(self.to_add)}')
            if self.to_remove:
                changes.append(f'−{len(self.to_remove)}')
            self._count.set_text(f'{total} 個檔案' + (f'（{" ".join(changes)}）' if changes else ''))

            self._list.clear()
            with self._list:
                if not self.existing and not self.to_add:
                    with ui.element('div').classes('kf-empty'):
                        ui.icon('upload_file', size='26px')
                        ui.label('尚無知識文件，點下方按鈕上傳')
                    return
                for name in self.existing:
                    if name in self.to_remove:
                        self._row(name, 'removing', lambda _, n=name: self._toggle_remove(n))
                    else:
                        self._row(name, '', lambda _, n=name: self._toggle_remove(n))
                for name, _ in self.to_add:
                    self._row(name, 'adding', lambda _, n=name: self._cancel_add(n))

    with ui.element("div").classes("asst-wrap w-full"):
        render_navbar(active='assistant')

        with ui.element("div").classes("asst-body"):
            
            # ── 左側：進階問答 ──────────────────────────────────────────────
            with ui.element("aside").classes("sidebar-panel sidebar-left"):
                ui.html('<div class="sidebar-title">進階問答</div>', sanitize=False)
                
                with ui.expansion('🚨 是否面臨詐騙？').classes('w-full custom-expansion'):
                    ui.label('情境').classes('font-bold text-slate-700 text-[14px] mb-1 mt-1')
                    scenario = ui.textarea(placeholder='請簡短描述事件來龍去脈，例如：對方自稱是老同學，要我投資一個海外平台…').classes('w-full mb-3 text-[15px]').props('outlined rows=3')
                    ui.label('事件發生日期').classes('font-bold text-slate-700 text-[14px] mb-1')
                    event_date = ui.input(placeholder='例如: 2026/04/29').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('聯絡手段').classes('font-bold text-slate-700 text-[14px] mb-1')
                    contact_method = ui.input(placeholder='例如: Line/簡訊/電話').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('相關金額 (新台幣)').classes('font-bold text-slate-700 text-[14px] mb-1')
                    amount = ui.number(placeholder='例如: 50000').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('對象的稱呼').classes('font-bold text-slate-700 text-[14px] mb-1')
                    target_name = ui.input(placeholder='例如: 投資老師/客服').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('匯款方式').classes('font-bold text-slate-700 text-[14px] mb-1')
                    transfer_method = ui.input(placeholder='例如: ATM/網銀/面交').classes('w-full mb-6 text-[16px]').props('outlined')

                    async def submit_advanced():
                        scenario_text = (scenario.value or '').strip()
                        prompt = (
                            f"你是專業的反詐騙 AI 助手。請根據使用者提供的【人時地物金額】進行分析：\n\n"
                            f"【案件資訊】\n"
                            + (f"情境描述：{scenario_text}\n" if scenario_text else "")
                            + f"事件日期：{event_date.value or '未提供'}\n"
                            f"聯絡手段：{contact_method.value or '未提供'}\n"
                            f"涉及金額：{f'{int(amount.value):,} 元' if amount.value else '未提供'}\n"
                            f"對象稱呼：{target_name.value or '未提供'}\n"
                            f"匯款方式：{transfer_method.value or '未提供'}\n\n"
                            f"請依照以下架構回應：\n"
                            f"1. 辨識詐騙類型：判斷是否符合「假投資」、「假檢警」或「猜猜我是誰」等常見手法。\n"
                            f"2. 風險評估：分析對方話術中的矛盾點與危險信號。\n"
                            f"3. 行動指引：\n"
                            f"   - 若涉及金錢，優先提示撥打 165 或前往報案。\n"
                            f"   - 告知如何留存證據（截圖、對話紀錄、匯款單）。\n"
                            f"4. 法律提醒：給予初步的法律常識建議，但需註明不代表法律訴訟之最終依據。"
                            f"5. 實際相似案例提供：從資料庫中尋找與使用者情境相似的實際詐騙案例，提供對方使用的詐騙手法以及造成的損失，以警示使用者。"
                        )
                        display = (
                            f"【疑似詐騙通報】\n"
                            + (f"情境：{scenario_text}\n" if scenario_text else "")
                            + f"日期：{event_date.value or '未提供'}\n"
                            f"手段：{contact_method.value or '未提供'}\n"
                            f"金額：{f'{int(amount.value):,} 元' if amount.value else '未提供'}\n"
                            f"對象：{target_name.value or '未提供'}\n"
                            f"匯款：{transfer_method.value or '未提供'}"
                        )
                        await send_to_chat(prompt, display=display)
                        scenario.value = ''
                        event_date.value = ''
                        contact_method.value = ''
                        amount.value = None
                        target_name.value = ''
                        transfer_method.value = ''

                    ui.button('傳送評估', on_click=submit_advanced).classes('sidebar-submit-btn').style(SUBMIT_BTN_BG).props('unelevated no-caps')

                # ── 法律求助諮詢 ──────────────────────────────────────────
                with ui.expansion('⚖️ 法律求助諮詢').classes('w-full custom-expansion'):
                    ui.label('情境').classes('font-bold text-slate-700 text-[14px] mb-1 mt-1')
                    legal_scenario = ui.textarea(placeholder='請簡短描述事件來龍去脈，例如：我在網路上認識一位「投資老師」，他推薦我加入一個海外交易平台，出金時被要求先繳保證金…').classes('w-full mb-3 text-[15px]').props('outlined rows=3')
                    ui.label('詐騙類型').classes('font-bold text-slate-700 text-[14px] mb-1')
                    legal_type = ui.select(['假投資', '假檢警', '網購詐騙', '愛情詐騙', '其他'], value='假投資').classes('w-full mb-3 text-[15px]').props('outlined')
                    ui.label('損失金額（新台幣）').classes('font-bold text-slate-700 text-[14px] mb-1')
                    legal_amount = ui.number(placeholder='例如: 150000').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('對方留下的聯絡資訊').classes('font-bold text-slate-700 text-[14px] mb-1')
                    legal_contact = ui.input(placeholder='例如: 帳號、電話、LINE ID').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('手邊已有的證據').classes('font-bold text-slate-700 text-[14px] mb-1')
                    legal_evidence = ui.input(placeholder='例如: 有對話截圖、有轉帳紀錄、無任何證據').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('是否已向警方報案').classes('font-bold text-slate-700 text-[14px] mb-1')
                    legal_reported = ChipToggle(default='否', classes='mb-3')
                    ui.label('希望達成的目標').classes('font-bold text-slate-700 text-[14px] mb-1')
                    legal_goal = ui.select(['追回款項', '刑事追訴', '了解法律權益'], value='了解法律權益').classes('w-full mb-6 text-[15px]').props('outlined')

                    async def submit_legal():
                        legal_scenario_text = (legal_scenario.value or '').strip()
                        prompt = (
                            f"你是專業的反詐騙 AI 助手，同時具備初步法律常識。請依據以下資訊提供法律求助建議：\n\n"
                            f"【案件資訊】\n"
                            + (f"情境描述：{legal_scenario_text}\n" if legal_scenario_text else "")
                            + f"詐騙類型：{legal_type.value or '未提供'}\n"
                            f"損失金額：{f'{int(legal_amount.value):,} 元' if legal_amount.value else '未提供'}\n"
                            f"對方聯絡資訊：{legal_contact.value or '未提供'}\n"
                            f"現有證據：{legal_evidence.value or '未提供'}\n"
                            f"是否已報案：{legal_reported.value}\n"
                            f"希望達成的目標：{legal_goal.value or '未提供'}\n\n"
                            f"請先掌握整體情境脈絡，再依照以下架構回應：\n"
                            f"1. 報案流程與管轄單位：說明應前往派出所、撥打 165 或向調查局申訴的時機與步驟。\n"
                            f"2. 蒐證指引：列出哪些證據對立案最有幫助（對話截圖、轉帳記錄、帳號資料等）。\n"
                            f"3. 民事求償可能性：評估提起民事訴訟追回損失的可行性。\n"
                            f"4. 法律條文提示：簡要說明刑法 §339 詐欺罪的構成要件，並提醒此為初步參考，非正式法律意見。\n"
                            f"5. 實際相似案例：從資料庫尋找類似案例，說明其最終處理方式與結果。"
                        )
                        display = (
                            f"【法律求助諮詢】\n"
                            + (f"情境：{legal_scenario_text}\n" if legal_scenario_text else "")
                            + f"詐騙類型：{legal_type.value or '未提供'}\n"
                            f"損失金額：{f'{int(legal_amount.value):,} 元' if legal_amount.value else '未提供'}\n"
                            f"是否已報案：{legal_reported.value}\n"
                            f"希望達成的目標：{legal_goal.value or '未提供'}"
                        )
                        await send_to_chat(prompt, display=display)
                        legal_scenario.value = ''
                        legal_type.value = '假投資'
                        legal_amount.value = None
                        legal_contact.value = ''
                        legal_evidence.value = ''
                        legal_reported.value = '否'
                        legal_goal.value = '了解法律權益'

                    ui.button('傳送諮詢', on_click=submit_legal).classes('sidebar-submit-btn').style(SUBMIT_BTN_BG).props('unelevated no-caps')

                # ── 可疑訊息 / 話術分析 ──────────────────────────────────
                with ui.expansion('🔍 可疑訊息 / 話術分析').classes('w-full custom-expansion'):
                    ui.label('情境').classes('font-bold text-slate-700 text-[14px] mb-1 mt-1')
                    msg_scenario = ui.textarea(placeholder='請簡短描述整體情境，例如：最近在交友軟體認識一個人，聊沒多久他就開始提到投資機會…').classes('w-full mb-3 text-[15px]').props('outlined rows=3')
                    ui.label('可疑訊息內容').classes('font-bold text-slate-700 text-[14px] mb-1')
                    msg_content = ui.textarea(placeholder='請將對方傳來的訊息文字貼在此處…').classes('w-full mb-3 text-[15px]').props('outlined rows=4')
                    ui.label('發送者自稱身份').classes('font-bold text-slate-700 text-[14px] mb-1')
                    msg_sender = ui.input(placeholder='例如: 銀行客服、老朋友、投資老師').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('聯絡管道').classes('font-bold text-slate-700 text-[14px] mb-1')
                    msg_channel = ui.input(placeholder='例如: LINE / Facebook / 簡訊 / 電話').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('對方有無提供帳號或連結').classes('font-bold text-slate-700 text-[14px] mb-1')
                    msg_link = ui.input(placeholder='例如: 要我點連結登入 / 提供匯款帳號').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('是否已有金錢往來').classes('font-bold text-slate-700 text-[14px] mb-1')
                    msg_paid = ChipToggle(default='否', classes='mb-6')

                    async def submit_msg():
                        msg_scenario_text = (msg_scenario.value or '').strip()
                        content_text = (msg_content.value or '').strip()
                        prompt = (
                            f"你是專業的反詐騙 AI 助手。請針對以下可疑訊息進行話術分析：\n\n"
                            f"【訊息資訊】\n"
                            + (f"情境描述：{msg_scenario_text}\n" if msg_scenario_text else "")
                            + (f"訊息內容：\n{content_text}\n\n" if content_text else "")
                            + f"發送者自稱：{msg_sender.value or '未提供'}\n"
                            f"聯絡管道：{msg_channel.value or '未提供'}\n"
                            f"帳號或連結：{msg_link.value or '未提供'}\n"
                            f"是否已有金錢往來：{msg_paid.value}\n\n"
                            f"請先掌握整體情境脈絡，再依照以下架構回應：\n"
                            f"1. 話術特徵辨識：指出訊息中使用的緊迫感製造、情緒操控、誘導話術等具體手法。\n"
                            f"2. 詐騙類型判定：根據特徵判斷最可能的詐騙類別（假冒官員、假投資、釣魚連結等）。\n"
                            f"3. 標準詐騙劇本對照：說明此類詐騙的完整操作流程，讓使用者了解後續可能的走向。\n"
                            f"4. 建議行動：明確說明應立即中止互動的方式，以及若已有金錢往來的緊急處置步驟。"
                        )
                        display = (
                            f"【可疑訊息話術分析】\n"
                            + (f"情境：{msg_scenario_text}\n" if msg_scenario_text else "")
                            + (f"訊息摘要：{content_text[:50]}{'…' if len(content_text) > 50 else ''}\n" if content_text else "")
                            + f"發送者：{msg_sender.value or '未提供'}\n"
                            f"管道：{msg_channel.value or '未提供'}\n"
                            f"已有金錢往來：{msg_paid.value}"
                        )
                        await send_to_chat(prompt, display=display)
                        msg_scenario.value = ''
                        msg_content.value = ''
                        msg_sender.value = ''
                        msg_channel.value = ''
                        msg_link.value = ''
                        msg_paid.value = '否'

                    ui.button('傳送分析', on_click=submit_msg).classes('sidebar-submit-btn').style(SUBMIT_BTN_BG).props('unelevated no-caps')

                # ── 投資平台安全查詢 ──────────────────────────────────────
                with ui.expansion('💰 投資平台安全查詢').classes('w-full custom-expansion'):
                    ui.label('情境').classes('font-bold text-slate-700 text-[14px] mb-1 mt-1')
                    invest_scenario = ui.textarea(placeholder='請簡短描述整體情境，例如：朋友在群組分享一個投資機會，說每天都能穩定獲利，邀我一起加入…').classes('w-full mb-3 text-[15px]').props('outlined rows=3')
                    ui.label('平台名稱 / 網址').classes('font-bold text-slate-700 text-[14px] mb-1')
                    invest_name = ui.input(placeholder='例如: XXX 交易所').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('宣稱的獲利方式').classes('font-bold text-slate-700 text-[14px] mb-1')
                    invest_profit = ui.input(placeholder='例如: 每月保證 30% 報酬').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('推薦人（如何認識）').classes('font-bold text-slate-700 text-[14px] mb-1')
                    invest_referral = ui.input(placeholder='例如: 陌生人 Instagram 私訊').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('是否被要求先匯款').classes('font-bold text-slate-700 text-[14px] mb-1')
                    invest_prepay = ChipToggle(default='否', classes='mb-3')
                    ui.label('已投入金額（新台幣，未投入填 0）').classes('font-bold text-slate-700 text-[14px] mb-1')
                    invest_amount = ui.number(placeholder='例如: 50000', value=0).classes('w-full mb-6 text-[16px]').props('outlined')

                    async def submit_invest():
                        invest_scenario_text = (invest_scenario.value or '').strip()
                        prompt = (
                            f"你是專業的反詐騙 AI 助手。請針對以下投資平台資訊進行安全評估：\n\n"
                            f"【平台資訊】\n"
                            + (f"情境描述：{invest_scenario_text}\n" if invest_scenario_text else "")
                            + f"平台名稱/網址：{invest_name.value or '未提供'}\n"
                            f"宣稱獲利方式：{invest_profit.value or '未提供'}\n"
                            f"推薦人來源：{invest_referral.value or '未提供'}\n"
                            f"是否被要求先匯款：{invest_prepay.value}\n"
                            f"已投入金額：{f'{int(invest_amount.value):,} 元' if invest_amount.value else '0 元'}\n\n"
                            f"請先掌握整體情境脈絡，再依照以下架構回應：\n"
                            f"1. 詐騙特徵對照：與假投資詐騙的標準特徵（保證獲利、陌生人推薦、先行匯款）進行對照分析。\n"
                            f"2. 合法平台查詢：說明如何透過金管會、投信投顧公會查詢合法投資平台。\n"
                            f"3. 風險評估結論：明確指出此平台的風險程度（高風險 / 中風險 / 低風險）及判斷依據。\n"
                            f"4. 緊急處置：若已匯款，立即說明應採取的停損步驟（凍結帳戶、報警、聯繫銀行）。"
                        )
                        display = (
                            f"【投資平台安全查詢】\n"
                            + (f"情境：{invest_scenario_text}\n" if invest_scenario_text else "")
                            + f"平台：{invest_name.value or '未提供'}\n"
                            f"宣稱獲利：{invest_profit.value or '未提供'}\n"
                            f"已投入：{f'{int(invest_amount.value):,} 元' if invest_amount.value else '0 元'}"
                        )
                        await send_to_chat(prompt, display=display)
                        invest_scenario.value = ''
                        invest_name.value = ''
                        invest_profit.value = ''
                        invest_referral.value = ''
                        invest_prepay.value = '否'
                        invest_amount.value = 0

                    ui.button('傳送查詢', on_click=submit_invest).classes('sidebar-submit-btn').style(SUBMIT_BTN_BG).props('unelevated no-caps')

                # ── 個資外洩 / 身份盜用 ──────────────────────────────────
                with ui.expansion('📋 個資外洩 / 身份盜用').classes('w-full custom-expansion'):
                    ui.label('情境').classes('font-bold text-slate-700 text-[14px] mb-1 mt-1')
                    privacy_scenario = ui.textarea(placeholder='請簡短描述整體情境，例如：最近陸續接到陌生來電，對方能準確講出我的姓名與住址…').classes('w-full mb-3 text-[15px]').props('outlined rows=3')
                    ui.label('外洩的個資種類').classes('font-bold text-slate-700 text-[14px] mb-1')
                    privacy_types = ui.input(placeholder='例如: 身分證字號、信用卡號、手機號碼').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('如何得知外洩').classes('font-bold text-slate-700 text-[14px] mb-1')
                    privacy_how = ui.textarea(placeholder='例如: 收到陌生人用我名字辦的貸款通知…').classes('w-full mb-3 text-[15px]').props('outlined rows=3')
                    ui.label('外洩來源推測').classes('font-bold text-slate-700 text-[14px] mb-1')
                    privacy_source = ui.input(placeholder='例如: 某網購平台 / 醫院系統 / 不明').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('是否已有異常帳務或損失').classes('font-bold text-slate-700 text-[14px] mb-1')
                    privacy_loss = ChipToggle(default='否', classes='mb-3')
                    ui.label('是否已更換密碼或掛失').classes('font-bold text-slate-700 text-[14px] mb-1')
                    privacy_changed = ChipToggle(default='否', classes='mb-6')

                    async def submit_privacy():
                        privacy_scenario_text = (privacy_scenario.value or '').strip()
                        how_text = (privacy_how.value or '').strip()
                        prompt = (
                            f"你是專業的資安與法律 AI 助手。請針對以下個資外洩情況提供建議：\n\n"
                            f"【個資外洩資訊】\n"
                            + (f"情境描述：{privacy_scenario_text}\n" if privacy_scenario_text else "")
                            + f"外洩的個資種類：{privacy_types.value or '未提供'}\n"
                            + (f"得知外洩的方式：{how_text}\n" if how_text else "")
                            + f"外洩來源推測：{privacy_source.value or '不明'}\n"
                            f"是否已有異常帳務或損失：{privacy_loss.value}\n"
                            f"是否已更換密碼或掛失：{privacy_changed.value}\n\n"
                            f"請先掌握整體情境脈絡，再依照以下架構回應：\n"
                            f"1. 立即保護措施：列出應優先執行的動作（掛失、信用凍結、密碼更換、聯繫銀行）。\n"
                            f"2. 個人資料保護法權益：簡述依個資法第 11、28、29 條，當事人可向洩露方主張的權利。\n"
                            f"3. 申訴與通報流程：說明向個資保護機構（調查局、個資保護委員會）申訴的步驟。\n"
                            f"4. 長期防護建議：提供防止後續身份盜用的具體措施（信用監控、二階段驗證等）。"
                        )
                        display = (
                            f"【個資外洩 / 身份盜用查詢】\n"
                            + (f"情境：{privacy_scenario_text}\n" if privacy_scenario_text else "")
                            + f"外洩個資：{privacy_types.value or '未提供'}\n"
                            f"外洩來源：{privacy_source.value or '不明'}\n"
                            f"是否有損失：{privacy_loss.value}"
                        )
                        await send_to_chat(prompt, display=display)
                        privacy_scenario.value = ''
                        privacy_types.value = ''
                        privacy_how.value = ''
                        privacy_source.value = ''
                        privacy_loss.value = '否'
                        privacy_changed.value = '否'

                    ui.button('傳送查詢', on_click=submit_privacy).classes('sidebar-submit-btn').style(SUBMIT_BTN_BG).props('unelevated no-caps')

                # ── 數據分析請求 ──────────────────────────────────────────
                with ui.expansion('📊 數據分析請求').classes('w-full custom-expansion'):
                    ui.label('資料內容').classes('font-bold text-slate-700 text-[14px] mb-1 mt-1')
                    data_manual_input = ui.textarea(placeholder='可直接貼上表格、CSV 或 JSON 資料，或改用下方上傳檔案…').classes('w-full mb-3 text-[15px]').props('outlined rows=4')

                    ui.label('或上傳檔案（.csv / .xlsx）').classes('font-bold text-slate-700 text-[14px] mb-1')
                    _uploaded_data = {'text': '', 'filename': ''}
                    data_upload_status = ui.label('').classes('upload-status')

                    async def _handle_data_upload(e):
                        try:
                            raw = await e.file.read()
                            name = e.file.name
                            lower = name.lower()
                            if lower.endswith('.csv'):
                                df = pd.read_csv(io.BytesIO(raw))
                            elif lower.endswith('.xlsx') or lower.endswith('.xls'):
                                df = pd.read_excel(io.BytesIO(raw))
                            else:
                                data_upload_status.set_text('❌ 僅支援 .csv 或 .xlsx 檔案')
                                return
                            truncated = False
                            if len(df) > 2000:
                                df = df.head(2000)
                                truncated = True
                            csv_text = df.to_csv(index=False)
                            if len(csv_text) > 20000:
                                csv_text = csv_text[:20000]
                                truncated = True
                            _uploaded_data['text'] = csv_text
                            _uploaded_data['filename'] = name
                            data_upload_status.set_text(
                                f'✅ 已上傳「{name}」（{len(df)} 列 x {len(df.columns)} 欄）' + ('，內容過大已截斷' if truncated else '')
                            )
                        except Exception as ex:
                            data_upload_status.set_text(f'❌ 檔案解析失敗：{ex}')

                    data_upload_el = ui.upload(
                        on_upload=_handle_data_upload,
                        on_rejected=lambda e: data_upload_status.set_text('❌ 檔案不符合條件（僅支援 .csv / .xlsx）'),
                        auto_upload=True,
                        label='選擇檔案',
                    ).classes('w-full mb-1').props('accept=".csv,.xlsx,.xls" flat bordered')
                    _style_upload_as_button(data_upload_el)

                    ui.label('目標欄位（數值欄位，圖表 Y 軸）').classes('font-bold text-slate-700 text-[14px] mb-1 mt-3')
                    data_target_col = ui.input(placeholder='例如: sales').classes('w-full mb-3 text-[16px]').props('outlined')
                    ui.label('分組欄位（依此分組，圖表 X 軸）').classes('font-bold text-slate-700 text-[14px] mb-1')
                    data_group_col = ui.input(placeholder='例如: city').classes('w-full mb-3 text-[16px]').props('outlined')

                    ui.label('統計項目（可多選）').classes('font-bold text-slate-700 text-[14px] mb-1')
                    selected_stats = set()

                    STAT_OPTIONS = [
                        ('describe', '描述性統計'), ('mean', '平均值'), ('median', '中位數'), ('std', '標準差'),
                        ('min', '最小值'), ('max', '最大值'), ('sum', '加總'), ('count', '筆數'),
                        ('correlation', '相關係數'), ('groupby_agg', '分組聚合'),
                    ]

                    @ui.refreshable
                    def stat_chips():
                        with ui.element('div').classes('option-chip-row mb-3'):
                            for key, label in STAT_OPTIONS:
                                cls = 'option-chip selected' if key in selected_stats else 'option-chip'
                                def _toggle(_, k=key):
                                    if k in selected_stats:
                                        selected_stats.discard(k)
                                    else:
                                        selected_stats.add(k)
                                    stat_chips.refresh()
                                ui.html(f'<button class="{cls}" type="button" onclick="void(0)">{label}</button>', sanitize=False).on('click', _toggle)

                    stat_chips()

                    ui.label('圖表類型（可多選）').classes('font-bold text-slate-700 text-[14px] mb-1')
                    selected_charts = set()

                    CHART_OPTIONS = [
                        ('bar', '長條圖'), ('line', '折線圖'), ('pie', '圓餅圖'), ('scatter', '散佈圖'),
                    ]

                    @ui.refreshable
                    def chart_chips():
                        with ui.element('div').classes('option-chip-row mb-6'):
                            for key, label in CHART_OPTIONS:
                                cls = 'option-chip selected' if key in selected_charts else 'option-chip'
                                def _toggle(_, k=key):
                                    if k in selected_charts:
                                        selected_charts.discard(k)
                                    else:
                                        selected_charts.add(k)
                                    chart_chips.refresh()
                                ui.html(f'<button class="{cls}" type="button" onclick="void(0)">{label}</button>', sanitize=False).on('click', _toggle)

                    chart_chips()

                    async def submit_data_analysis():
                        manual_text = (data_manual_input.value or '').strip()
                        uploaded_text = _uploaded_data.get('text', '')
                        final_data = uploaded_text or manual_text
                        if not final_data:
                            ui.notify('請先貼上資料，或上傳 CSV/XLSX 檔案', color='negative')
                            return

                        target_col = (data_target_col.value or '').strip()
                        group_col = (data_group_col.value or '').strip()
                        # 送出前先解析，欄位名稱打錯或格式不對時直接提示，不必等 Agent 跑完才發現
                        df, parse_err = parse_tabular_data(final_data)
                        if parse_err:
                            ui.notify(parse_err, color='negative', multi_line=True)
                            return
                        columns = [str(c) for c in df.columns]
                        missing_cols = [c for c in (target_col, group_col) if c and c not in columns]
                        if missing_cols:
                            ui.notify(f"找不到欄位 {'、'.join(missing_cols)}，可用欄位：{'、'.join(columns)}",
                                      color='negative', multi_line=True)
                            return
                        ops = [key for key, _ in STAT_OPTIONS if key in selected_stats] or ['describe']
                        charts = [key for key, _ in CHART_OPTIONS if key in selected_charts]
                        if (charts or any(op not in ('describe', 'correlation') for op in ops)) and not target_col:
                            ui.notify('所選的統計項目或圖表需要填寫目標欄位（圖表的 Y 軸）', color='negative')
                            return
                        if (charts or 'groupby_agg' in ops) and not group_col:
                            ui.notify('分組聚合與圖表需要填寫分組欄位（圖表的 X 軸）', color='negative')
                            return

                        stat_labels = [label for key, label in STAT_OPTIONS if key in ops]
                        chart_labels = [label for key, label in CHART_OPTIONS if key in charts]
                        # 資料與統計／圖表參數走結構化的 analysis_request，由數據分析專家直接照參數執行；
                        # 文字訊息只負責讓 Planner 路由，以及告訴 Worker 報告要怎麼寫
                        analysis_request = {
                            'data_text': final_data,
                            'operations': ops,
                            'charts': charts,
                            'target_column': target_col or None,
                            'group_by': group_col or None,
                        }
                        sections = ["資料概況：簡述資料的欄位、筆數與資料型態。",
                                    "統計結果：以清楚的文字呈現計算出的統計數字，並說明其代表的意義。"]
                        if charts:
                            sections.append("圖表說明：簡短說明每張產生的圖表呈現了什麼重點趨勢或分布，不需要重複描述圖片細節。")
                        sections.append("結論建議：根據分析結果，提出 1-2 點觀察或建議。")
                        prompt = (
                            f"請數據分析專家分析使用者提供的資料，並解讀統計與圖表結果。\n\n"
                            f"【資料】{len(df)} 列，欄位：{'、'.join(columns)}"
                            + (f"（檔案「{_uploaded_data['filename']}」）" if uploaded_text else "") + "\n"
                            + (f"目標欄位：{target_col}\n" if target_col else "")
                            + (f"分組欄位：{group_col}\n" if group_col else "")
                            + f"統計項目：{'、'.join(stat_labels)}\n"
                            + (f"圖表：{'、'.join(chart_labels)}\n" if chart_labels else "")
                            + "\n請依照以下架構回應：\n"
                            + "\n".join(f"{i}. {t}" for i, t in enumerate(sections, 1))
                        )
                        display = (
                            f"【數據分析請求】\n"
                            + (f"資料來源：已上傳「{_uploaded_data['filename']}」\n" if uploaded_text else f"資料摘要：{final_data[:60]}{'…' if len(final_data) > 60 else ''}\n")
                            + (f"目標欄位：{target_col}\n" if target_col else "")
                            + (f"分組欄位：{group_col}\n" if group_col else "")
                            + f"統計項目：{'、'.join(stat_labels)}\n"
                            + (f"圖表類型：{'、'.join(chart_labels)}" if chart_labels else "")
                        ).strip()

                        await send_to_chat(prompt, display=display, analysis_request=analysis_request)

                        data_manual_input.value = ''
                        data_target_col.value = ''
                        data_group_col.value = ''
                        _uploaded_data['text'] = ''
                        _uploaded_data['filename'] = ''
                        data_upload_status.set_text('')
                        selected_stats.clear()
                        selected_charts.clear()
                        stat_chips.refresh()
                        chart_chips.refresh()

                    ui.button('傳送分析請求', on_click=submit_data_analysis).classes('sidebar-submit-btn').style(SUBMIT_BTN_BG).props('unelevated no-caps')

                # ── Worker 管理區域 ──────────────────────────────────────
                ui.element("div").classes("h-px w-full bg-slate-200 my-2 shrink-0")
                ui.html('<div class="sidebar-title">Worker 管理</div>', sanitize=False)

                async def open_add_worker_dialog():
                    with ui.dialog() as dialog, ui.card().style(WORKER_DIALOG_STYLE):
                        ui.label('新增 Worker').style(
                            'font-size:20px; font-weight:700; color:#1e293b; margin-bottom:20px;'
                        )

                        with ui.element('div').classes('wk-dialog-body'):
                            with ui.element('div').classes('wk-col'):
                                ui.label('Worker 名稱').classes('wk-label')
                                worker_name_input = ui.input(placeholder='例如：旅遊專家').classes('w-full').props('outlined dense')
                                worker_name_input.style('margin-bottom:16px;')

                                ui.label('描述（供 Planner 路由使用）').classes('wk-label')
                                worker_desc_input = ui.textarea(placeholder='此 Worker 擅長解答關於…').classes('w-full').props('outlined rows=9')

                            with ui.element('div').classes('wk-col'):
                                files = KnowledgeFileList([], on_error=lambda msg: status_label.set_text(msg))

                        status_label = ui.label('').style(
                            'font-size:13px; color:#64748b; min-height:20px; margin-top:10px; margin-bottom:16px;'
                        )

                        ui.element('div').style('height:1px; background:#e2e8f0; margin-bottom:16px;')

                        async def confirm_add():
                            name = worker_name_input.value.strip()
                            desc = worker_desc_input.value.strip()
                            if not name:
                                status_label.set_text('❌ 請填寫 Worker 名稱')
                                return
                            if not desc:
                                status_label.set_text('❌ 請填寫描述')
                                return
                            client = context.client
                            confirm_btn.props('loading disable')
                            status_label.set_text('⏳ 建立中，正在重建 Agent 核心（約需數分鐘）…')
                            if rag_agent_instance is not None:
                                result = await rag_agent_instance.create_worker(name, desc, list(files.to_add))
                            else:
                                result = '❌ Agent 尚未載入'
                            # 重建期間使用者可能已關閉 dialog / 重新整理 / 斷線，此時元素已被銷毀
                            if not client.has_socket_connection or dialog.is_deleted:
                                return
                            try:
                                status_label.set_text(result)
                                confirm_btn.props(remove='loading disable')
                                if result.startswith('✅'):
                                    render_worker_list()
                                    dialog.close()
                            except RuntimeError:
                                pass

                        with ui.row().style('width:100%; justify-content:flex-end; align-items:center; gap:10px;'):
                            ui.button('取消', on_click=dialog.close).props('flat no-caps').style('color:#475569 !important; font-size:14px;')
                            confirm_btn = ui.button('新增', on_click=confirm_add).props('unelevated no-caps').style(
                                'background:linear-gradient(135deg,#f97316 0%,#ea580c 100%) !important; '
                                'color:#fff !important; font-weight:700; padding:8px 24px; border-radius:10px;'
                            )

                    dialog.open()

                ui.button('+ 新增 Worker', on_click=open_add_worker_dialog).classes('sidebar-submit-btn full-width').style(SUBMIT_BTN_BG).props('unelevated no-caps')

                worker_list_container = ui.element("div").classes("flex flex-col gap-2")

                async def open_edit_worker_dialog(name: str):
                    current_desc = rag_agent_instance.get_worker_description(name) if rag_agent_instance else ""

                    with ui.dialog() as dialog, ui.card().style(WORKER_DIALOG_STYLE):
                        ui.label('編輯 Worker').style('font-size:20px; font-weight:700; color:#1e293b; margin-bottom:20px;')

                        with ui.element('div').classes('wk-dialog-body'):
                            with ui.element('div').classes('wk-col'):
                                ui.label('Worker 名稱').classes('wk-label')
                                name_input = ui.input(placeholder='Worker 名稱').classes('w-full').props('outlined dense')
                                name_input.value = name
                                name_input.style('margin-bottom:16px;')

                                ui.label('描述（供 Planner 路由使用）').classes('wk-label')
                                desc_input = ui.textarea(placeholder='此 Worker 擅長解答關於…').classes('w-full').props('outlined rows=9')
                                desc_input.value = current_desc

                            # 知識文件：移除 / 新增皆先暫存，按「儲存」才一次套用並重建
                            with ui.element('div').classes('wk-col'):
                                files = KnowledgeFileList(
                                    rag_agent_instance.get_worker_files(name) if rag_agent_instance else [],
                                    on_error=lambda msg: status_label.set_text(msg),
                                )

                        status_label = ui.label('').style('font-size:13px; color:#64748b; min-height:20px; margin-top:10px; margin-bottom:16px;')

                        # 分隔線
                        ui.element('div').style('height:1px; background:#e2e8f0; margin-bottom:16px;')

                        async def confirm_save(_name=name):
                            new_name = name_input.value.strip()
                            new_desc = desc_input.value.strip()
                            if not new_name:
                                status_label.set_text('❌ Worker 名稱不可為空')
                                return
                            if not new_desc:
                                status_label.set_text('❌ 描述不可為空')
                                return
                            client = context.client
                            save_btn.props('loading disable')
                            status_label.set_text('⏳ 儲存中，正在重建 Agent…')
                            result = await rag_agent_instance.update_worker(
                                _name, new_desc, new_name,
                                add_files=list(files.to_add),
                                remove_files=list(files.to_remove),
                            )
                            # 重建期間使用者可能已關閉 dialog / 重新整理 / 斷線，此時元素已被銷毀
                            if not client.has_socket_connection or dialog.is_deleted:
                                return
                            try:
                                status_label.set_text(result)
                                save_btn.props(remove='loading disable')
                                if result.startswith('✅'):
                                    # dialog 建立在 Worker 清單列之內，先關閉再重繪清單，否則重繪時已被刪除
                                    dialog.close()
                                    render_worker_list()
                            except RuntimeError:
                                pass

                        async def confirm_delete(_name=name):
                            with ui.dialog() as confirm_dlg, ui.card().style(
                                'width:420px; max-width:95vw; padding:28px; display:flex; flex-direction:column; gap:0;'
                            ):
                                ui.label(f'確定要刪除 Worker「{_name}」？').style(
                                    'font-size:17px; font-weight:700; color:#1e293b; margin-bottom:10px;'
                                )
                                ui.label('此操作將移除所有知識文件，無法復原。').style(
                                    'font-size:13px; color:#64748b; margin-bottom:24px;'
                                )
                                ui.element('div').style('height:1px; background:#e2e8f0; margin-bottom:16px;')

                                async def do_delete(__name=_name):
                                    confirm_dlg.close()
                                    dialog.close()
                                    result = await rag_agent_instance.delete_worker(__name)
                                    ui.notify(result, color='positive' if result.startswith('✅') else 'negative')
                                    render_worker_list()

                                with ui.row().style('width:100%; justify-content:space-between; align-items:center;'):
                                    ui.button('取消', on_click=confirm_dlg.close).props('flat no-caps').style('color:#475569 !important; font-size:14px;')
                                    ui.button('確定刪除', on_click=do_delete).props('unelevated no-caps').style(
                                        'background:#ef4444 !important; color:#fff !important; font-weight:700; padding:8px 20px; border-radius:10px;'
                                    )
                            confirm_dlg.open()

                        with ui.row().style('width:100%; justify-content:space-between; align-items:center;'):
                            ui.button('刪除', on_click=confirm_delete).props('unelevated no-caps').style(
                                'background:#ef4444 !important; color:#fff !important; font-weight:700; padding:8px 20px; border-radius:10px;'
                            )
                            with ui.row().style('gap:10px; align-items:center;'):
                                ui.button('取消', on_click=dialog.close).props('flat no-caps').style('color:#475569 !important; font-size:14px;')
                                save_btn = ui.button('儲存', on_click=confirm_save).props('unelevated no-caps').style(
                                    'background:linear-gradient(135deg,#f97316 0%,#ea580c 100%) !important; color:#fff !important; font-weight:700; padding:8px 24px; border-radius:10px;'
                                )

                    dialog.open()

                def render_worker_list():
                    worker_list_container.clear()
                    if rag_agent_instance is None:
                        return
                    workers = rag_agent_instance.get_user_worker_status()
                    if not workers:
                        with worker_list_container:
                            ui.label('尚無自訂 Worker').classes('text-[13px] text-slate-400 text-center py-2')
                        return
                    with worker_list_container:
                        for w in workers:
                            wid = w["worker_id"]
                            wname = w["name"]
                            with ui.row().style(
                                'width:100%; align-items:center; justify-content:space-between; gap:8px; '
                                'background:#fff; border:1px solid #e2e8f0; border-radius:12px; '
                                'padding:10px 14px; box-shadow:0 1px 4px rgba(0,0,0,0.02);'
                            ):
                                ui.label(wname).style(
                                    'font-size:15px; font-weight:500; color:#334155; '
                                    'overflow:hidden; text-overflow:ellipsis; white-space:nowrap; '
                                    'flex:1; min-width:0;'
                                )
                                with ui.row().style('align-items:center; gap:4px; flex-shrink:0;'):
                                    ChipToggle(
                                        options=('停用', '啟用'),
                                        default='啟用' if w["enabled"] else '停用',
                                        on_change=lambda v, _wid=wid: rag_agent_instance.toggle_worker(_wid, v == '啟用'),
                                    )
                                    ui.button(icon='edit', on_click=lambda _, _n=wname: open_edit_worker_dialog(_n)).props('flat round dense').style('color:#94a3b8 !important; margin:0;')

                render_worker_list()

            # ── 中央：對話區塊與輸入框 ──────────────────────────────────────
            with ui.element("div").classes("chat-container"):
                chat_log = ui.element("div").classes("chat-log")
                
                async def send_to_chat(text, display=None, analysis_request=None):
                    text = str(text).strip()
                    if not text:
                        return
                    safe = _html.escape(display if display is not None else text)
                    
                    with chat_log:
                        ui.html(f'<div class="msg-row-user"><div class="bubble-col-user">'
                                f'<span class="bubble-label">使用者</span>'
                                f'<div class="bubble-user">{safe}</div></div></div>', sanitize=False)
                        thinking = ui.html('<div class="msg-row-ai"><div class="bubble-col-ai">'
                                          '<span class="bubble-label">AI 助理</span>'
                                          '<div class="bubble-thinking">分析中…</div></div></div>',
                                          sanitize=False)
                    
                    await ui.run_javascript(
                        'var el=document.getElementById("asst-input");if(el)el.value="";'
                        'var l=document.querySelector(".chat-log");if(l)l.scrollTop=l.scrollHeight;'
                    )
                    
                    if rag_agent_instance is None:
                        try: thinking.delete()
                        except Exception: pass
                        with chat_log:
                            ui.html('<div class="msg-row-ai"><div class="bubble-col-ai">'
                                    '<span class="bubble-label">AI 助理</span>'
                                    '<div class="bubble-ai">⚠️ Agent 尚未載入，目前處於純 UI 展示模式。</div>'
                                    '</div></div>', sanitize=False)
                    else:
                        try:
                            uid = app.storage.user.get('session_id', 'web_user')
                            is_reply = app.storage.user.get('is_reply', False)
                            
                            # on_step 由背景執行緒呼叫，ThinkingLog 只排入佇列，繪製交給頁面 timer
                            thinking_log.start_run(display if display is not None else text)
                            resp = await rag_agent_instance.ask(
                                user_id=uid, text=text, is_reply=is_reply,
                                on_step=thinking_log.on_step,
                                analysis_request=analysis_request,
                            )
                            thinking_log.finish_run(resp.status)
                            try: thinking.delete()
                            except Exception: pass
                            
                            is_interrupted = (resp.status == 'interrupted')
                            bubble_cls = 'bubble-system' if is_interrupted else 'bubble-ai'
                            label_text = 'System' if is_interrupted else 'AI 助理'

                            with chat_log:
                                with ui.element('div').classes('msg-row-ai'):
                                    with ui.element('div').classes('bubble-col-ai'):
                                        ui.html(f'<span class="bubble-label">{label_text}</span>', sanitize=False)
                                        with ui.element('div').classes(f'{bubble_cls} md-bubble'):
                                            # LLM 輸出的 Markdown → 安全排版（預設 DOMPurify 清洗）
                                            ui.markdown(resp.response_text)
                                            # 圖表為工具自行產生的 base64 data URI（非 LLM 自由文字）
                                            for b64 in (resp.chart_images or []):
                                                ui.html(
                                                    f'<img src="{b64}" style="max-width:100%;'
                                                    'border-radius:8px;margin-top:8px;display:block;">',
                                                    sanitize=False,
                                                )

                            app.storage.user['is_reply'] = is_interrupted
                        except Exception as err:
                            thinking_log.finish_run('error')
                            try: thinking.delete()
                            except Exception: pass
                            with chat_log:
                                ui.html(f'<div class="msg-row-ai"><div class="bubble-col-ai">'
                                        f'<span class="bubble-label">AI 助理</span>'
                                        f'<div class="bubble-ai text-red-500">❌ {_html.escape(str(err))}</div>'
                                        '</div></div>', sanitize=False)
                                        
                    try:
                        await ui.run_javascript('var l=document.querySelector(".chat-log");if(l)l.scrollTop=l.scrollHeight;')
                    except Exception:
                        pass

                async def handle_send():
                    text = await ui.run_javascript('return document.getElementById("asst-input")?.value??"";')
                    await send_to_chat(text)

                with ui.element("div").classes("input-area"):
                    ui.html('<input id="asst-input" type="text" placeholder="輸入你想問的問題..." autocomplete="off">', sanitize=False).classes('flex-1 w-full')
                    ui.button("傳送", on_click=handle_send).classes("send-btn").style(SUBMIT_BTN_BG).props("unelevated no-caps")

            # ── 右側：快速提示與 Thinking Log ──────────────────────────────────────────────
            with ui.element("aside").classes("sidebar-panel sidebar-right"):
                # 快速提示區塊
                ui.html('<div class="sidebar-title mb-4">快速提示</div>', sanitize=False)
                for p in PROMPTS:
                    async def fill(_, t=p):
                        await ui.run_javascript(f"var el=document.getElementById('asst-input');if(el){{el.value={json.dumps(t)};el.focus();}}")
                    ui.html(f'<button class="prompt-chip" onclick="void(0)">{_html.escape(p)}</button>', sanitize=False).on('click', fill)
                
                # 分隔線
                ui.element("div").classes("h-px w-full bg-slate-200 my-4 shrink-0")
                
                # Thinking Log 區塊 (就像普通的對話框)
                with ui.element('div').classes('tl-head-row mb-2'):
                    ui.html('<div class="sidebar-title">Thinking Log</div>', sanitize=False)
                    # 純前端切換右欄寬度，不經伺服器
                    ui.button(icon='open_in_full').props('flat round dense size=sm') \
                        .style('color:#94a3b8 !important;').tooltip('放寬 / 還原 Thinking Log') \
                        .on('click', js_handler="() => document.querySelector('.asst-body')?.classList.toggle('tl-wide')")
                thinking_log = ThinkingLog()
