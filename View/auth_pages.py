"""
登入 / 註冊 / 登出 頁面
路由: /login, /register, /logout
風格: PaperFlow Glass 居中卡片
"""
from nicegui import ui, app
from Model import auth_db
from Controller.auth_middleware import login_user, logout_user, is_logged_in

# ── 共用 CSS ─────────────────────────────────────────────────────────────────
AUTH_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --primary:   #E65C00;
  --secondary: #FFB380;
  --tertiary:  #FFF5E6;
  --surface:   #FDFBF7;
  --neutral:   #78716C;
  --txt-pri:   #78716C;
  --txt-sec:   #292524;
  --border:    #E7E5E4;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  width: 100%; min-height: 100vh; margin: 0; padding: 0;
  background:
    radial-gradient(at 0% 0%, hsla(28, 100%, 94%, 1) 0, transparent 50%),
    radial-gradient(at 50% 0%, hsla(210, 100%, 96%, 1) 0, transparent 50%),
    radial-gradient(at 100% 0%, hsla(33, 100%, 92%, 1) 0, transparent 50%);
  background-color: #f8fafc;
  font-family: Inter, sans-serif;
  color: var(--txt-sec);
}
.q-layout, .q-page-container, .q-page, .nicegui-content {
  background: transparent !important;
  width: 100% !important; max-width: 100% !important;
  margin: 0 !important; padding: 0 !important;
  min-height: 100vh !important;
}
.auth-page {
  min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  padding: 34px;
}
.auth-shell {
  padding: 4.25px;
  border-radius: 21.25px;
  background: linear-gradient(135deg, rgb(253,251,247) 0%, rgb(247,244,235) 100%);
  box-shadow: rgba(230,92,0,0.06) 0px 4px 24px 0px;
  width: 100%; max-width: 440px;
}
.auth-card {
  background: rgba(255,255,255,0.45);
  backdrop-filter: blur(64px);
  -webkit-backdrop-filter: blur(64px);
  border: 1px solid rgba(255,255,255,0.9);
  border-radius: 17px;
  box-shadow: rgba(255,255,255,0.8) 0px 1px 0px 0px inset,
              rgba(0,0,0,0.02) 0px 4px 20px 0px;
  padding: 40px 36px;
  display: flex; flex-direction: column; gap: 20px;
}
.auth-logo {
  display: flex; align-items: center; gap: 10px;
  justify-content: center; margin-bottom: 8px;
}
.auth-logo-badge {
  background: #ea580c; color: #fff; font-size: 15px; font-weight: 700;
  padding: 5px 10px; border-radius: 9999px; letter-spacing: 0.05em;
}
.auth-logo-text { font-size: 22px; font-weight: 700; color: #1e293b; }
.auth-title {
  font-size: 26px; font-weight: 700; color: var(--txt-sec);
  text-align: center; letter-spacing: -0.02em;
}
.auth-subtitle {
  font-size: 14px; color: var(--txt-pri); text-align: center;
  margin-top: -8px;
}
.auth-link {
  font-size: 14px; color: var(--primary); text-align: center;
  cursor: pointer; text-decoration: none; font-weight: 600;
  transition: opacity 0.15s;
}
.auth-link:hover { opacity: 0.8; }
.auth-error {
  background: #fef2f2; border: 1px solid #fecaca; color: #dc2626;
  padding: 10px 14px; border-radius: 10px; font-size: 14px;
  text-align: center; font-weight: 500;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.auth-shell { animation: fadeUp 500ms ease both; }

/* 輸入框標籤：跟其他頁面一樣，stack-label 的標籤/值間距會被 Tailwind preflight
   歸零而疊在一起，這裡補回間距（比照 report_page.py 的欄位比例）。 */
.auth-card .q-field--outlined .q-field__control {
  padding: 0 14px;
  min-height: 52px;
}
.auth-card .q-field--outlined .q-field__native,
.auth-card .q-field--outlined .q-field__input {
  font-size: 15px;
}
.auth-card .q-field--outlined .q-field__label {
  font-size: 13px;
}
.auth-card .q-field--outlined.q-field--labeled .q-field__native,
.auth-card .q-field--outlined.q-field--labeled .q-field__prefix,
.auth-card .q-field--outlined.q-field--labeled .q-field__suffix {
  padding-top: 20px;
}
</style>
"""


@ui.page("/login")
async def login_page():
    if is_logged_in():
        ui.navigate.to("/dashboard")
        return

    ui.add_head_html(AUTH_CSS, shared=False)
    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch')

    with ui.element("div").classes("auth-page"):
        with ui.element("div").classes("auth-shell"):
            with ui.element("div").classes("auth-card"):
                # Logo
                ui.html("""
                    <div class="auth-logo">
                        <span class="auth-logo-badge">165</span>
                        <span class="auth-logo-text">反詐騙平台</span>
                    </div>
                """, sanitize=False)

                ui.html('<h1 class="auth-title">登入帳號</h1>', sanitize=False)
                ui.html('<p class="auth-subtitle">歡迎回來，請輸入您的帳號密碼</p>', sanitize=False)

                error_container = ui.element("div")

                username_input = ui.input(
                    label="帳號",
                    placeholder="請輸入帳號",
                ).classes("w-full").props('outlined stack-label')

                password_input = ui.input(
                    label="密碼",
                    placeholder="請輸入密碼",
                    password=True,
                    password_toggle_button=True,
                ).classes("w-full").props('outlined stack-label')

                async def do_login():
                    u = username_input.value.strip()
                    p = password_input.value.strip()
                    if not u or not p:
                        error_container.clear()
                        with error_container:
                            ui.html('<div class="auth-error">請填寫帳號與密碼</div>', sanitize=False)
                        return

                    user = auth_db.verify_user(u, p)
                    if user is None:
                        error_container.clear()
                        with error_container:
                            ui.html('<div class="auth-error">帳號或密碼錯誤</div>', sanitize=False)
                        return

                    login_user(user)
                    ui.navigate.to("/dashboard")

                password_input.on("keydown.enter", do_login)

                ui.button("登入", on_click=do_login).classes(
                    "w-full rounded-full font-bold text-white text-base py-3"
                ).style(
                    "background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);"
                    "box-shadow: rgba(234,88,12,0.25) 0px 2px 10px 0px;"
                ).props("unelevated no-caps")

                ui.html("""
                    <div style="text-align:center;">
                        <span style="font-size:14px;color:#78716C;">還沒有帳號？</span>
                        <a href="/register" class="auth-link">立即註冊</a>
                    </div>
                """, sanitize=False)


@ui.page("/register")
async def register_page():
    if is_logged_in():
        ui.navigate.to("/dashboard")
        return

    ui.add_head_html(AUTH_CSS, shared=False)
    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch')

    with ui.element("div").classes("auth-page"):
        with ui.element("div").classes("auth-shell"):
            with ui.element("div").classes("auth-card"):
                ui.html("""
                    <div class="auth-logo">
                        <span class="auth-logo-badge">165</span>
                        <span class="auth-logo-text">反詐騙平台</span>
                    </div>
                """, sanitize=False)

                ui.html('<h1 class="auth-title">註冊帳號</h1>', sanitize=False)
                ui.html('<p class="auth-subtitle">建立帳號以使用完整功能</p>', sanitize=False)

                error_container = ui.element("div")

                username_input = ui.input(label="帳號", placeholder="請輸入帳號").classes("w-full").props('outlined stack-label')
                display_name_input = ui.input(label="顯示名稱", placeholder="例如：王小明").classes("w-full").props('outlined stack-label')
                email_input = ui.input(label="電子信箱", placeholder="example@mail.com").classes("w-full").props('outlined stack-label')
                password_input = ui.input(label="密碼", placeholder="至少 6 個字元", password=True, password_toggle_button=True).classes("w-full").props('outlined stack-label')
                confirm_input = ui.input(label="確認密碼", placeholder="再次輸入密碼", password=True, password_toggle_button=True).classes("w-full").props('outlined stack-label')

                async def do_register():
                    u = username_input.value.strip()
                    dn = display_name_input.value.strip()
                    em = email_input.value.strip()
                    p = password_input.value
                    c = confirm_input.value

                    if not u or not p:
                        error_container.clear()
                        with error_container:
                            ui.html('<div class="auth-error">帳號與密碼為必填</div>', sanitize=False)
                        return
                    if len(p) < 6:
                        error_container.clear()
                        with error_container:
                            ui.html('<div class="auth-error">密碼至少需要 6 個字元</div>', sanitize=False)
                        return
                    if p != c:
                        error_container.clear()
                        with error_container:
                            ui.html('<div class="auth-error">兩次密碼不一致</div>', sanitize=False)
                        return

                    uid = auth_db.create_user(u, p, dn, em)
                    if uid is None:
                        error_container.clear()
                        with error_container:
                            ui.html('<div class="auth-error">帳號已被使用</div>', sanitize=False)
                        return

                    # 自動登入
                    user = auth_db.verify_user(u, p)
                    if user:
                        login_user(user)
                    ui.navigate.to("/dashboard")

                confirm_input.on("keydown.enter", do_register)

                ui.button("註冊", on_click=do_register).classes(
                    "w-full rounded-full font-bold text-white text-base py-3"
                ).style(
                    "background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);"
                    "box-shadow: rgba(234,88,12,0.25) 0px 2px 10px 0px;"
                ).props("unelevated no-caps")

                ui.html("""
                    <div style="text-align:center;">
                        <span style="font-size:14px;color:#78716C;">已有帳號？</span>
                        <a href="/login" class="auth-link">前往登入</a>
                    </div>
                """, sanitize=False)


@ui.page("/logout")
async def logout_page():
    logout_user()
    ui.navigate.to("/login")
