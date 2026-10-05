import sys
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from nicegui import ui
from Model import auth_db, report_db
from View import dashboard, assistant, auth_pages, report_page, admin_page, my_reports, case_query

# 啟動時初始化資料庫
auth_db.init_db()
report_db.init_db()

@ui.page("/")
async def root():
    from Controller.auth_middleware import is_logged_in
    if is_logged_in():
        ui.navigate.to("/dashboard")
    else:
        ui.navigate.to("/login")

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="165 反詐騙數據儀表板",
        port=8081,
        reload=False,
        storage_secret="fraud_dash_secret_2026",
    )
