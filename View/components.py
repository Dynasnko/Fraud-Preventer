"""
共用元件：Navbar（認證感知）
"""
from nicegui import ui
from Controller.auth_middleware import get_current_user, is_admin

NAV_CSS = """
<style>
.dash-navbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 28px; border-bottom: 1px solid #e2e8f0;
  background: rgba(253,251,247,0.95); backdrop-filter: blur(20px);
  position: sticky; top: 0; z-index: 100;
  flex-wrap: wrap; gap: 8px;
}
.nav-logo { display: flex; align-items: center; gap: 8px; }
.nav-logo-badge {
  background: #ea580c; color: #fff; font-size: 13px; font-weight: 700;
  padding: 4px 8px; border-radius: 9999px; letter-spacing: 0.05em;
}
.nav-logo-text { font-size: 18px; font-weight: 700; color: #1e293b; }
.nav-tabs { display: flex; gap: 4px; }
.nav-tab {
  padding: 8px 16px; border-radius: 9999px; font-size: 15px; font-weight: 600;
  color: #475569; cursor: pointer; border: none; background: transparent;
  transition: all 150ms ease; text-decoration: none; display: inline-block;
}
.nav-tab:hover { background: #fff0e6; color: #ea580c; }
.nav-tab.active {
  background: #ea580c; color: #fff;
  box-shadow: rgba(234,88,12,0.2) 0px 2px 10px 0px;
}
.nav-right { display: flex; align-items: center; gap: 8px; }
.nav-auth-btn {
  padding: 8px 18px; border-radius: 9999px; font-size: 14px; font-weight: 600;
  cursor: pointer; border: none; transition: all 150ms ease;
  text-decoration: none; display: inline-block;
}
.nav-login-btn {
  background: transparent; color: #475569; border: 1px solid #e2e8f0;
}
.nav-login-btn:hover { background: #fff0e6; color: #ea580c; border-color: #ea580c; }
.nav-register-btn {
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  color: #fff; box-shadow: rgba(234,88,12,0.25) 0px 2px 10px 0px;
}
.nav-register-btn:hover { transform: translateY(-1px); box-shadow: rgba(234,88,12,0.35) 0px 4px 16px 0px; }
.nav-user-name {
  font-size: 14px; font-weight: 600; color: #292524;
  padding: 6px 14px; background: #FFF5E6; border-radius: 9999px;
}
.nav-logout-btn {
  padding: 6px 14px; border-radius: 9999px; font-size: 13px; font-weight: 600;
  color: #78716C; background: transparent; border: 1px solid #e2e8f0;
  cursor: pointer; text-decoration: none; transition: all 150ms ease;
}
.nav-logout-btn:hover { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
</style>
"""


def render_navbar(active: str = ""):
    """渲染導航列，active 可為 'dashboard','assistant','report','my_reports','cases','admin'"""
    user = get_current_user()
    admin = is_admin()

    def tab_cls(name):
        return "nav-tab active" if name == active else "nav-tab"

    # 自動偵測 active（如果沒指定）
    # 由各頁面傳入，或 fallback 空字串

    auth_html = ""
    if user:
        display = user.get("display_name") or user.get("username", "")
        auth_html = f'''
            <span class="nav-user-name">👤 {display}</span>
            <a href="/logout" class="nav-logout-btn">登出</a>
        '''
    else:
        auth_html = '''
            <a href="/login" class="nav-auth-btn nav-login-btn">登入</a>
            <a href="/register" class="nav-auth-btn nav-register-btn">註冊</a>
        '''

    user_tabs = ""
    if user:
        user_tabs = f'''
            <a href="/my-reports" class="{tab_cls('my_reports')}" style="text-decoration:none;">我的通報</a>
            <a href="/cases" class="{tab_cls('cases')}" style="text-decoration:none;">案例查詢</a>
        '''

    admin_tab = ""
    if admin:
        admin_tab = f'<a href="/admin" class="{tab_cls("admin")}" style="text-decoration:none;">管理後台</a>'

    ui.html(NAV_CSS + f"""
<nav class="dash-navbar" role="navigation" aria-label="主要導航">
  <div class="nav-logo">
    <span class="nav-logo-badge">165</span>
    <span class="nav-logo-text">反詐騙數據儀表板</span>
  </div>
  <div class="nav-tabs" role="tablist">
    <a href="/dashboard" class="{tab_cls('dashboard')}" style="text-decoration:none;">即時總覽</a>
    <a href="/assistant" class="{tab_cls('assistant')}" style="text-decoration:none;">智能助手</a>
    <a href="/report" class="{tab_cls('report')}" style="text-decoration:none;">案件通報</a>
    {user_tabs}
    {admin_tab}
  </div>
  <div class="nav-right">
    {auth_html}
  </div>
</nav>
""", sanitize=False).classes('w-full !p-0 !m-0')
