"""
案件通報頁面
路由: /report
公開存取（不需登入），已登入者自動綁定 user_id
風格: PaperFlow Glass 分段式表單
"""
from nicegui import ui, app
from Model import report_db
from View.components import render_navbar
from Controller.auth_middleware import get_current_user

# ── CSS ──────────────────────────────────────────────────────────────────────
REPORT_CSS = """
<style>
.report-main {
  width: 100%; margin: 0; padding: 32px;
  display: flex; flex-direction: column; gap: 24px;
  box-sizing: border-box; max-width: 960px; margin: 0 auto;
}
.report-header {
  text-align: center; padding: 24px 0 8px;
}
.report-header h1 {
  font-size: 28px; font-weight: 700; color: #292524;
  letter-spacing: -0.02em; margin-bottom: 8px;
}
.report-header p {
  font-size: 15px; color: #78716C; line-height: 1.6;
}
.form-section-shell {
  padding: 4px; border-radius: 20px;
  background: linear-gradient(135deg, rgb(253,251,247) 0%, rgb(247,244,235) 100%);
  box-shadow: rgba(230,92,0,0.06) 0px 4px 24px 0px;
}
.form-section {
  background: rgba(255,255,255,0.45);
  backdrop-filter: blur(64px); -webkit-backdrop-filter: blur(64px);
  border: 1px solid rgba(255,255,255,0.9);
  border-radius: 16px;
  box-shadow: rgba(255,255,255,0.8) 0px 1px 0px 0px inset,
              rgba(0,0,0,0.02) 0px 4px 20px 0px;
  padding: 32px;
  display: flex; flex-direction: column; gap: 20px;
}
.form-section-title {
  font-size: 17px; font-weight: 700; color: #292524;
  display: flex; align-items: center; gap: 8px;
}
.form-section-title::before {
  content: ''; display: block; width: 4px; height: 18px;
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  border-radius: 4px;
}
.form-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
}
.form-row-3 {
  display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px;
}
.required-mark { color: #dc2626; font-weight: 700; }
.submit-area {
  display: flex; justify-content: center; padding: 8px 0;
}
.success-card {
  background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 17px;
  padding: 32px; text-align: center;
}
.success-card h2 { color: #16a34a; font-size: 22px; font-weight: 700; margin-bottom: 8px; }
.success-card p { color: #15803d; font-size: 15px; }
.success-card .report-id {
  font-size: 36px; font-weight: 700; color: #E65C00;
  margin: 16px 0;
}

/* ── 優化 Quasar input/select 元件內部間距 ── */
.report-main .q-field--outlined .q-field__control {
  padding: 0 16px;
  min-height: 54px;
}
.report-main .q-field--outlined .q-field__native,
.report-main .q-field--outlined .q-field__input {
  font-size: 15px;
  text-overflow: ellipsis;
}
.report-main .q-field--outlined .q-field__label {
  font-size: 14px;
}
/* 加高的欄位需要手動補上 label 預留空間，避免文字與浮動 label 重疊 */
.report-main .q-field--outlined.q-field--labeled .q-field__native,
.report-main .q-field--outlined.q-field--labeled .q-field__prefix,
.report-main .q-field--outlined.q-field--labeled .q-field__suffix {
  padding-top: 22px;
}
/* textarea 特別處理：讓文字不被 label 蓋住 */
.report-main .q-textarea .q-field__native {
  min-height: 140px;
  padding-top: 24px !important;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .form-row, .form-row-3 { grid-template-columns: 1fr; gap: 16px; }
  .report-main { padding: 16px; gap: 16px; }
  .form-section { padding: 20px; gap: 16px; }
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.form-section-shell {
  animation: fadeUp 500ms ease both;
}
.form-section-shell:nth-child(2) { animation-delay: 50ms; }
.form-section-shell:nth-child(3) { animation-delay: 100ms; }
.form-section-shell:nth-child(4) { animation-delay: 150ms; }
.form-section-shell:nth-child(5) { animation-delay: 200ms; }
</style>
"""


@ui.page("/report")
async def report_page():
    ui.add_head_html(REPORT_CSS, shared=False)
    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch')

    render_navbar(active='report')

    current_user = get_current_user()

    with ui.element("main").classes("report-main"):
        # ── Header ────────────────────────────────────────────────────────
        ui.html("""
            <div class="report-header">
                <h1>📋 案件通報</h1>
                <p>若您遭遇或發現疑似詐騙行為，請填寫以下資料進行通報。<br>
                   我們將盡速審核並協助處理。</p>
            </div>
        """, sanitize=False)

        form_container = ui.element("div").style("display:flex;flex-direction:column;gap:24px;")
        success_container = ui.element("div").style("display:none;")

        with form_container:
            # ── Section 1: 通報者基本資料 ──────────────────────────────────
            with ui.element("div").classes("form-section-shell"):
                with ui.element("div").classes("form-section"):
                    ui.html('<div class="form-section-title">一、通報者基本資料</div>', sanitize=False)

                    with ui.element("div").classes("form-row-3"):
                        reporter_name = ui.input(
                            label="姓名 *",
                            placeholder="您的姓名",
                            value=current_user.get("display_name", "") if current_user else "",
                        ).classes("w-full").props('outlined')

                        reporter_phone = ui.input(
                            label="聯絡電話 *",
                            placeholder="09xx-xxx-xxx",
                        ).classes("w-full").props('outlined')

                        reporter_email = ui.input(
                            label="電子信箱",
                            placeholder="example@mail.com",
                            value=current_user.get("email", "") if current_user else "",
                        ).classes("w-full").props('outlined')

            # ── Section 2: 案件資訊 ───────────────────────────────────────
            with ui.element("div").classes("form-section-shell"):
                with ui.element("div").classes("form-section"):
                    ui.html('<div class="form-section-title">二、案件資訊</div>', sanitize=False)

                    with ui.element("div").classes("form-row-3"):
                        is_victim = ui.select(
                            label="是否已受騙 *",
                            options=['尚未受騙', '已受騙（有實際財損）'],
                            value='尚未受騙',
                        ).classes("w-full").props('outlined stack-label')

                        fraud_channel = ui.input(
                            label="詐騙管道 *",
                            placeholder="例：電話、LINE、網頁",
                        ).classes("w-full").props('outlined stack-label')

                        fraud_type = ui.input(
                            label="詐騙類型 *",
                            placeholder="例：假交友、投資詐騙、網購詐騙…",
                        ).classes("w-full").props('outlined stack-label')

                    with ui.element("div").classes("form-row"):
                        city = ui.select(
                            label="事發地區 *",
                            options=report_db.CITIES,
                        ).classes("w-full").props('outlined stack-label')

                        loss_amount = ui.number(
                            label="財損金額（新台幣）",
                            placeholder="0",
                            min=0,
                        ).classes("w-full").props('outlined stack-label')

            # ── Section 3: 涉詐資料 ──────────────────────────────────────
            with ui.element("div").classes("form-section-shell"):
                with ui.element("div").classes("form-section"):
                    ui.html('<div class="form-section-title">三、涉詐資料</div>', sanitize=False)

                    with ui.element("div").classes("form-row"):
                        suspect_phone = ui.input(
                            label="涉詐電話號碼",
                            placeholder="對方使用的電話",
                        ).classes("w-full").props('outlined')

                        suspect_line_id = ui.input(
                            label="涉詐 LINE ID",
                            placeholder="對方的 LINE ID",
                        ).classes("w-full").props('outlined')

                    with ui.element("div").classes("form-row"):
                        suspect_url = ui.input(
                            label="涉詐網址",
                            placeholder="https://...",
                        ).classes("w-full").props('outlined')

                        bank_account = ui.input(
                            label="涉詐帳號",
                            placeholder="銀行帳號",
                        ).classes("w-full").props('outlined')

            # ── Section 4: 詳細說明 ──────────────────────────────────────
            with ui.element("div").classes("form-section-shell"):
                with ui.element("div").classes("form-section"):
                    ui.html('<div class="form-section-title">四、詳細說明</div>', sanitize=False)

                    description = ui.textarea(
                        label="案件描述 *",
                        placeholder="請描述事件經過，包含時間、方式、金額等細節（500字以內）",
                    ).classes("w-full").props('outlined rows=6 maxlength=500 counter')

                    police_station = ui.input(
                        label="欲報案派出所（選填）",
                        placeholder="例如：中正一分局",
                    ).classes("w-full").props('outlined')

            # ── 送出按鈕 ─────────────────────────────────────────────────
            async def submit_report():
                # 驗證必填
                errors = []
                if not reporter_name.value or not reporter_name.value.strip():
                    errors.append("姓名")
                if not reporter_phone.value or not reporter_phone.value.strip():
                    errors.append("聯絡電話")
                if not fraud_channel.value or not fraud_channel.value.strip():
                    errors.append("詐騙管道")
                if not fraud_type.value or not fraud_type.value.strip():
                    errors.append("詐騙類型")
                if not city.value:
                    errors.append("事發地區")
                if not description.value or not description.value.strip():
                    errors.append("案件描述")

                if errors:
                    ui.notify(f"請填寫以下必填欄位：{', '.join(errors)}", type="negative", position="top")
                    return

                data = {
                    "reporter_name": reporter_name.value.strip(),
                    "reporter_phone": reporter_phone.value.strip(),
                    "reporter_email": reporter_email.value.strip() if reporter_email.value else "",
                    "is_victim": is_victim.value != '尚未受騙',
                    "fraud_channel": fraud_channel.value.strip(),
                    "fraud_type": fraud_type.value.strip(),
                    "suspect_phone": suspect_phone.value.strip() if suspect_phone.value else "",
                    "suspect_line_id": suspect_line_id.value.strip() if suspect_line_id.value else "",
                    "suspect_url": suspect_url.value.strip() if suspect_url.value else "",
                    "bank_account": bank_account.value.strip() if bank_account.value else "",
                    "loss_amount": loss_amount.value or 0,
                    "description": description.value.strip(),
                    "city": city.value,
                    "police_station": police_station.value.strip() if police_station.value else "",
                }

                user_id = current_user["id"] if current_user else None
                rid = report_db.create_report(user_id, data)

                # 隱藏表單，顯示成功
                form_container.style("display:none;")
                success_container.style("display:block;")
                with success_container:
                    with ui.element("div").classes("form-section-shell"):
                        ui.html(f"""
                            <div class="success-card">
                                <h2>✅ 通報成功</h2>
                                <p>您的通報已送出，系統將盡速審核</p>
                                <div class="report-id">#{rid:06d}</div>
                                <p>請記下此通報編號以便後續查詢</p>
                            </div>
                        """, sanitize=False)
                    with ui.element("div").style("display:flex;justify-content:center;gap:16px;margin-top:16px;"):
                        ui.button("返回首頁", on_click=lambda: ui.navigate.to("/dashboard"), color=None).classes(
                            "rounded-full font-bold text-base"
                        ).style(
                            "background:#f1f5f9;color:#475569;padding:12px 32px;"
                        ).props("unelevated no-caps")
                        ui.button("繼續通報", on_click=lambda: ui.navigate.to("/report"), color=None).classes(
                            "rounded-full font-bold text-white text-base"
                        ).style(
                            "background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);"
                            "padding:12px 32px;"
                        ).props("unelevated no-caps")

            with ui.element("div").classes("submit-area"):
                ui.button("送出通報", on_click=submit_report, color=None).classes(
                    "rounded-full font-bold text-white text-lg"
                ).style(
                    "background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);"
                    "box-shadow: rgba(234,88,12,0.3) 0px 4px 16px 0px;"
                    "transition: transform 0.2s, box-shadow 0.2s;"
                    "padding:16px 48px;"
                ).props("unelevated no-caps")

        # ── Footer ────────────────────────────────────────────────────────
        ui.html("""
        <footer style="text-align:center;font-size:13px;color:#78716C;padding:24px;
                       border-top:1px solid rgba(0,0,0,0.05);margin-top:16px;">
          <p>© 2026 內政部警政署 165 全民防騙網 · 通報資料僅供防詐案件處理使用</p>
        </footer>
        """, sanitize=False)
