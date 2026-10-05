"""
管理者後台
路由: /admin (僅 admin 角色)
三個 Tab: 使用者管理 / 通報管理 / 案件資料(scam_records CRUD)
"""
from nicegui import ui
import sqlite3, os
from Model import auth_db, report_db
from View.components import render_navbar
from Controller.auth_middleware import require_admin

_SCAM_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "AllInOneProject", "chroma_dbs", "scam_records.sqlite3",
)

ADMIN_CSS = """
<style>
.admin-main {
  width: 100% !important; padding: 40px 48px 110px 48px; box-sizing: border-box;
  display: flex; flex-direction: column; gap: 32px;
  max-width: 1600px !important;
  margin: 0 auto 60px auto;
}
.admin-title {
  font-size: 32px; font-weight: 700; color: #292524;
  display: flex; align-items: center; gap: 12px;
}
.stat-row { display: flex; gap: 20px; flex-wrap: wrap; }
.stat-chip {
  background: rgba(255,255,255,0.6); backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.8); border-radius: 14px;
  padding: 18px 28px; font-size: 16px; font-weight: 600; color: #292524;
  box-shadow: 0 2px 8px rgba(0,0,0,0.03);
}
.stat-chip .num { font-size: 28px; font-weight: 700; color: #E65C00; margin-right: 8px; }
.status-badge {
  padding: 5px 14px; border-radius: 9999px; font-size: 14px; font-weight: 600;
  display: inline-block;
}
.badge-pending   { background: #FFF5E6; color: #E65C00; }
.badge-reviewing { background: #DBEAFE; color: #2563EB; }
.badge-resolved  { background: #DCFCE7; color: #16A34A; }
.badge-closed    { background: #F1F5F9; color: #64748B; }

/* 可點選的圓角 chip 按鈕群組（通報狀態） */
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

/* ── 強制全寬佈局 ── */
.admin-main .q-tabs,
.admin-main .q-tab-panels,
.admin-main .q-tab-panel,
.admin-main .q-markup-table,
.admin-main .q-table,
.admin-main .q-table__container,
.admin-main .q-table__middle {
  width: 100% !important;
  max-width: 100% !important;
}
.admin-main .q-tab-panel {
  padding: 30px 20px !important;
}
.admin-main .q-tab {
  min-height: 56px;
  padding: 14px 8px;
}
.admin-main .q-table th,
.admin-main .q-table td {
  white-space: nowrap;
  padding: 16px 26px !important;
  font-size: 15px;
}
.admin-main .q-table th {
  font-size: 15.5px;
  font-weight: 700;
  color: #292524;
}
.admin-main .q-table .q-btn {
  font-size: 15px !important;
  padding: 10px 20px !important;
  min-height: 40px;
}
.admin-main .q-table .q-btn .q-icon {
  font-size: 20px !important;
}
/* table 撐滿 */
.admin-main table.q-table {
  width: 100% !important;
  table-layout: auto;
}

/* 下拉選單彈出選項（q-menu 掛載於頁面根層級，不受 .admin-main/.q-dialog 範圍限制） */
.q-menu .q-item__label {
  font-size: 15px !important;
}
.q-menu .q-item {
  min-height: 44px;
}

/* ── 對話框表單欄位：修正 outlined + stack-label 的標籤與輸入值互相重疊的問題 ──
   Tailwind 的 preflight 會把 <input>/<textarea> 的 padding 歸零，導致 Quasar
   原本用來替浮動標籤留出空間的 padding-top 失效，標籤跟輸入值疊在一起。 */
.q-dialog .q-field--outlined .q-field__control {
  padding-top: 10px;
  min-height: 68px !important;
}
.q-dialog .q-field--outlined.q-field--labeled .q-field__native,
.q-dialog .q-field--outlined.q-field--labeled textarea.q-field__native {
  padding-top: 27px !important;
  padding-bottom: 12px !important;
}
.q-dialog .q-field__native,
.q-dialog textarea.q-field__native {
  font-size: 18px !important;
}
.q-dialog textarea.q-field__native {
  min-height: 210px !important;
}
.q-dialog .q-field--float .q-field__label {
  top: 10px !important;
  font-size: 15px !important;
  font-weight: 700 !important;
  color: #E65C00 !important;
  letter-spacing: 0.02em;
  /* textarea 內容捲動時，文字會跑到 label 原本的位置底下；補一層不透明底色蓋住，
     避免捲動內容跟 label 疊在一起、糊成一片。 */
  background: #fff;
  padding: 0 2px;
  z-index: 2;
}
.q-dialog .q-field {
  margin-bottom: 10px;
}
/* 對話框底部操作列：狀態選單與按鈕分開，避免擠壓導致按鈕被裁切 */
.dialog-footer-row {
  flex-wrap: wrap;
  gap: 16px !important;
}
.dialog-footer-row .q-btn {
  white-space: nowrap;
}

/* 篩選列的下拉選單（狀態篩選／城市）：跟對話框欄位一樣受 Tailwind preflight
   影響，label 與已選取的值會疊在一起，這裡補回較小尺寸版本的 padding-top。 */
.filter-select.q-field--outlined .q-field__control {
  padding-top: 6px;
}
.filter-select.q-field--outlined.q-field--labeled .q-field__native {
  padding-top: 16px !important;
}
</style>
"""

# ── scam_records helpers ─────────────────────────────────────────────────────

def _scam_conn():
    if not os.path.exists(_SCAM_DB):
        return None
    conn = sqlite3.connect(_SCAM_DB)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_scam_indexes():
    conn = _scam_conn()
    if not conn: return
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_city ON scam_cases(city)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_date ON scam_cases(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_title ON scam_cases(title)")
        conn.commit()
    except: pass
    finally: conn.close()

def list_scam_cases(search="", city="", page=1, page_size=50):
    conn = _scam_conn()
    if not conn: return [], 0
    w, p = [], []
    if search:
        w.append("(title LIKE ? OR city LIKE ?)")
        s = f"%{search}%"; p.extend([s, s])
    if city:
        w.append("city = ?"); p.append(city)
    ws = (" WHERE " + " AND ".join(w)) if w else ""
    total = conn.execute(f"SELECT COUNT(*) FROM scam_cases{ws}", p).fetchone()[0]
    off = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM scam_cases{ws} ORDER BY date DESC LIMIT ? OFFSET ?",
        p + [page_size, off]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total

def get_scam_case(case_id):
    conn = _scam_conn()
    if not conn: return None
    r = conn.execute("SELECT * FROM scam_cases WHERE case_id = ?", (case_id,)).fetchone()
    conn.close()
    return dict(r) if r else None

def update_scam_case(case_id, data):
    conn = _scam_conn()
    if not conn: return False
    allowed = {"title","city","date","loss_amount","phone_numbers","summary",
               "fuzzy_loss_text","platforms","websites","scam_accounts"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields: return False
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [case_id]
    conn.execute(f"UPDATE scam_cases SET {sets} WHERE case_id=?", vals)
    conn.commit(); conn.close()
    return True

def delete_scam_case(case_id):
    conn = _scam_conn()
    if not conn: return False
    conn.execute("DELETE FROM scam_cases WHERE case_id=?", (case_id,))
    conn.commit(); conn.close()
    return True

def create_scam_case(data):
    conn = _scam_conn()
    if not conn: return None
    try:
        cur = conn.execute(
            """INSERT INTO scam_cases
               (case_id,title,city,date,loss_amount,phone_numbers,summary,
                fuzzy_loss_text,platforms,websites,scam_accounts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get("case_id",""), data.get("title",""), data.get("city",""),
             data.get("date",""), float(data.get("loss_amount",0) or 0),
             data.get("phone_numbers",""), data.get("summary",""),
             data.get("fuzzy_loss_text",""), data.get("platforms",""),
             data.get("websites",""), data.get("scam_accounts",""))
        )
        conn.commit(); conn.close()
        return cur.lastrowid
    except Exception as e:
        conn.close(); return None


# ── 頁面 ─────────────────────────────────────────────────────────────────────

@ui.page("/admin")
@require_admin
async def admin_page():
    ui.add_head_html(ADMIN_CSS, shared=False)
    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch')
    render_navbar(active='admin')

    _ensure_scam_indexes()

    with ui.element("main").classes("admin-main"):
        ui.html('<div class="admin-title">⚙️ 管理後台</div>', sanitize=False)

        with ui.tabs().classes("w-full justify-evenly gap-8").style("width:100%") as tabs:
            tab_users = ui.tab("👥 使用者管理").classes("text-xl font-bold px-8")
            tab_reports = ui.tab("📋 通報管理").classes("text-xl font-bold px-8")
            tab_cases = ui.tab("📊 案件資料").classes("text-xl font-bold px-8")

        with ui.tab_panels(tabs, value=tab_users).classes("w-full").style("width:100%"):
            # ═══════════════ Tab 1: 使用者管理 ═══════════════
            with ui.tab_panel(tab_users).style("width:100%"):
                users_container = ui.element("div").style("width:100%")

                def refresh_users():
                    users_container.clear()
                    users = auth_db.list_users()
                    with users_container:
                        columns = [
                            {"name": "id", "label": "ID", "field": "id", "align": "left"},
                            {"name": "username", "label": "帳號", "field": "username", "align": "left"},
                            {"name": "display_name", "label": "名稱", "field": "display_name", "align": "left"},
                            {"name": "email", "label": "Email", "field": "email", "align": "left"},
                            {"name": "role", "label": "角色", "field": "role", "align": "center"},
                            {"name": "is_active", "label": "狀態", "field": "is_active", "align": "center"},
                            {"name": "actions", "label": "操作", "field": "actions", "align": "center"},
                        ]
                        rows = []
                        for u in users:
                            rows.append({
                                "id": u["id"], "username": u["username"],
                                "display_name": u.get("display_name",""),
                                "email": u.get("email",""),
                                "role": u["role"],
                                "is_active": "✅ 啟用" if u["is_active"] else "❌ 停用",
                                "actions": u["id"],
                            })
                        table = ui.table(columns=columns, rows=rows, row_key="id").classes("w-full").props('flat bordered').style("width:100%")
                        table.add_slot('body-cell-actions', '''
                            <q-td :props="props">
                                <div class="flex gap-3 justify-center">
                                    <q-btn outline rounded icon="swap_horiz" label="切換狀態" color="orange"
                                           @click="$parent.$emit('toggle', props.row)" title="切換啟用"/>
                                    <q-btn outline rounded icon="admin_panel_settings" label="切換角色" color="blue"
                                           @click="$parent.$emit('role', props.row)" title="切換角色"/>
                                </div>
                            </q-td>
                        ''')
                        def on_toggle(e):
                            auth_db.toggle_active(e.args["id"])
                            refresh_users()
                            ui.notify("已更新", type="positive")
                        def on_role(e):
                            uid = e.args["id"]
                            u = auth_db.get_user(uid)
                            if u:
                                new_role = "admin" if u["role"] == "user" else "user"
                                auth_db.update_user(uid, role=new_role)
                                refresh_users()
                                ui.notify(f"角色已變更為 {new_role}", type="positive")
                        table.on("toggle", on_toggle)
                        table.on("role", on_role)

                refresh_users()

            # ═══════════════ Tab 2: 通報管理 ═══════════════
            with ui.tab_panel(tab_reports).style("width:100%"):
                rpt_page_state = {"page": 1, "status": "", "search": ""}
                reports_container = ui.element("div").style("width:100%")

                def refresh_reports():
                    reports_container.clear()
                    rows_data, total = report_db.list_reports(
                        status=rpt_page_state["status"],
                        search=rpt_page_state["search"],
                        page=rpt_page_state["page"],
                    )
                    stats = report_db.get_report_stats()
                    badge_map = {"pending":"badge-pending","reviewing":"badge-reviewing",
                                 "resolved":"badge-resolved","closed":"badge-closed"}
                    with reports_container:
                        # 統計
                        ui.html(f'''
                            <div class="stat-row" style="margin-bottom:20px;">
                                <div class="stat-chip"><span class="num">{stats["total"]}</span>總通報</div>
                                <div class="stat-chip"><span class="num">{stats["pending"]}</span>待處理</div>
                                <div class="stat-chip"><span class="num">{stats["reviewing"]}</span>審核中</div>
                                <div class="stat-chip"><span class="num">{stats["resolved"]}</span>已結案</div>
                            </div>
                        ''', sanitize=False)
                        # 篩選（左邊留白對齊表格儲存格內距，避免搜尋框比表格內容更靠左）
                        with ui.row().classes("items-center gap-4 mb-10").style("padding-left: 14px;"):
                            s_input = ui.input(placeholder="搜尋...", value=rpt_page_state["search"]).props("outlined").classes("w-60 text-base")
                            status_options = {"": "全部狀態", **report_db.STATUS_LABELS}
                            s_status = ui.select(options=status_options,
                                                 value=rpt_page_state["status"],
                                                 label="狀態篩選").props("outlined stack-label").classes("w-48 text-base filter-select")
                            def do_filter():
                                rpt_page_state["search"] = s_input.value or ""
                                rpt_page_state["status"] = s_status.value or ""
                                rpt_page_state["page"] = 1
                                refresh_reports()
                            ui.button("篩選", on_click=do_filter).props("unelevated no-caps").classes("text-base").style(
                                "background:#E65C00 !important;color:#fff !important;border-radius:9999px;padding:10px 22px;")

                        # 表格
                        columns = [
                            {"name":"id","label":"編號","field":"id","align":"left"},
                            {"name":"reporter_name","label":"通報者","field":"reporter_name","align":"left"},
                            {"name":"fraud_type","label":"詐騙類型","field":"fraud_type","align":"left"},
                            {"name":"city","label":"地區","field":"city","align":"left"},
                            {"name":"loss_amount","label":"財損","field":"loss_amount","align":"right"},
                            {"name":"status","label":"狀態","field":"status","align":"center"},
                            {"name":"created_at","label":"通報時間","field":"created_at","align":"left"},
                            {"name":"actions","label":"操作","field":"actions","align":"center"},
                        ]
                        tbl_rows = []
                        for r in rows_data:
                            status_val = r.get("status","pending")
                            tbl_rows.append({
                                "id": r["id"],
                                "reporter_name": r.get("reporter_name",""),
                                "fraud_type": r.get("fraud_type",""),
                                "city": r.get("city",""),
                                "loss_amount": f"${r.get('loss_amount',0):,.0f}",
                                "status": status_val,
                                "status_label": report_db.STATUS_LABELS.get(status_val, status_val),
                                "created_at": (r.get("created_at","") or "")[:16].replace("T", " "),
                                "actions": r["id"],
                            })
                        table = ui.table(columns=columns, rows=tbl_rows, row_key="id").classes("w-full").props('flat bordered').style("width:100%")
                        table.add_slot('body-cell-status', '''
                            <q-td :props="props">
                                <q-badge :class="'status-badge badge-' + props.row.status"
                                         :label="props.row.status_label" />
                            </q-td>
                        ''')
                        table.add_slot('body-cell-actions', '''
                            <q-td :props="props">
                                <q-btn outline rounded icon="visibility" label="查看 / 審核" color="primary"
                                       @click="$parent.$emit('view_report', props.row)" title="查看詳細/審核" />
                            </q-td>
                        ''')
                        
                        def show_report_dialog(report_id):
                            rpt = report_db.get_report(report_id)
                            if not rpt: return
                            with ui.dialog() as dlg, ui.card().style(
                                "width: 1300px; max-width: 96vw; max-height: 90vh; overflow-y: auto; padding: 48px;"
                            ).classes("rounded-[18px] shadow-2xl bg-white"):
                                ui.label(f"📋 通報詳細 (#{report_id})").classes("text-[32px] font-bold mb-10 text-[#292524] border-b pb-4")

                                with ui.element("div").classes("flex flex-col lg:flex-row gap-10 w-full mb-10 items-start"):
                                    # 左欄：通報者資訊 + 涉詐資料
                                    with ui.element("div").classes("flex flex-col gap-10 w-full lg:flex-1"):
                                        with ui.card().classes("bg-slate-50 flat bordered w-full rounded-xl flex flex-col gap-7 shadow-sm").style("padding: 32px;"):
                                            ui.label("👤 通報者資訊").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                                            f_rname = ui.input(label="姓名", value=rpt.get('reporter_name','')).classes("w-full").props("outlined bg-white stack-label")
                                            f_rphone = ui.input(label="電話", value=rpt.get('reporter_phone','')).classes("w-full").props("outlined bg-white stack-label")
                                            f_remail = ui.input(label="Email", value=rpt.get('reporter_email','')).classes("w-full").props("outlined bg-white stack-label")
                                        with ui.card().classes("bg-slate-50 flat bordered w-full rounded-xl flex flex-col gap-7 shadow-sm").style("padding: 32px;"):
                                            ui.label("⚠️ 涉詐資料").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                                            f_sphone = ui.input(label="涉詐電話", value=rpt.get('suspect_phone','')).classes("w-full").props("outlined bg-white stack-label")
                                            f_sline = ui.input(label="涉詐LINE", value=rpt.get('suspect_line_id','')).classes("w-full").props("outlined bg-white stack-label")
                                            f_surl = ui.input(label="涉詐網址", value=rpt.get('suspect_url','')).classes("w-full").props("outlined bg-white stack-label")
                                            f_sbank = ui.input(label="涉詐帳號", value=rpt.get('bank_account','')).classes("w-full").props("outlined bg-white stack-label")
                                    # 右欄：案件資訊 + 詳細說明
                                    with ui.element("div").classes("flex flex-col gap-10 w-full lg:flex-1"):
                                        with ui.card().classes("bg-slate-50 flat bordered w-full rounded-xl flex flex-col gap-7 shadow-sm").style("padding: 32px;"):
                                            ui.label("📄 案件資訊").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                                            is_victim_val = "已受騙（有實際財損）" if rpt.get('is_victim') else "尚未受騙"
                                            f_victim = ui.select(options=["尚未受騙", "已受騙（有實際財損）"], label="是否已受騙", value=is_victim_val).classes("w-full").props("outlined bg-white stack-label")
                                            f_channel = ui.input(label="詐騙管道", value=rpt.get('fraud_channel','')).classes("w-full").props("outlined bg-white stack-label")
                                            f_type = ui.input(label="詐騙類型", value=rpt.get('fraud_type','')).classes("w-full").props("outlined bg-white stack-label")
                                            f_city = ui.select(options=report_db.CITIES, label="事發地區", value=rpt.get('city') or None).classes("w-full").props("outlined bg-white stack-label")
                                            f_loss = ui.number(label="財損金額", value=rpt.get('loss_amount',0)).classes("w-full").props("outlined bg-white stack-label")
                                        with ui.card().classes("bg-slate-50 flat bordered w-full rounded-xl flex flex-col gap-7 shadow-sm").style("padding: 32px;"):
                                            ui.label("📝 詳細說明").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                                            # 多行文字框不用 Quasar 內建的浮動 label：內容捲動時會跟 label 疊在一起，
                                            # 改用一般文字放在框外上方，徹底避開這個問題。
                                            ui.label("案件描述").classes("font-bold text-[#E65C00] text-[15px] mb-1")
                                            f_desc = ui.textarea(value=rpt.get('description','')).classes("w-full").props("outlined bg-white rows=7")

                                # 狀態更新與操作
                                with ui.row().classes("dialog-footer-row w-full items-center justify-between border-t pt-6"):
                                    with ui.row().classes("items-center gap-4"):
                                        ui.label("通報狀態:").classes("font-semibold text-[17px] text-slate-700")
                                        status_state = {"value": rpt.get('status', 'pending')}

                                        @ui.refreshable
                                        def status_chips():
                                            with ui.element('div').classes('option-chip-row'):
                                                for key in report_db.REPORT_STATUSES:
                                                    label = report_db.STATUS_LABELS.get(key, key)
                                                    cls = 'option-chip selected' if key == status_state["value"] else 'option-chip'
                                                    def _select(_, k=key):
                                                        status_state["value"] = k
                                                        status_chips.refresh()
                                                    ui.html(f'<button class="{cls}" type="button" onclick="void(0)">{label}</button>', sanitize=False).on('click', _select)

                                        status_chips()
                                    with ui.row().classes("items-center gap-4"):
                                        ui.button("取消", on_click=dlg.close).props("flat no-caps rounded-full").classes("text-slate-500 text-base px-6")
                                        def update_rpt_all():
                                            d = {
                                                "reporter_name": f_rname.value, "reporter_phone": f_rphone.value, "reporter_email": f_remail.value,
                                                "is_victim": 1 if f_victim.value == "已受騙（有實際財損）" else 0,
                                                "fraud_channel": f_channel.value, "fraud_type": f_type.value, "city": f_city.value or "", "loss_amount": f_loss.value,
                                                "suspect_phone": f_sphone.value, "suspect_line_id": f_sline.value, "suspect_url": f_surl.value, "bank_account": f_sbank.value,
                                                "description": f_desc.value, "status": status_state["value"]
                                            }
                                            report_db.update_report(report_id, d)
                                            refresh_reports()
                                            ui.notify("已儲存變更", type="positive")
                                            dlg.close()
                                        ui.button("儲存變更", on_click=update_rpt_all).props("unelevated no-caps").classes("rounded-full px-8 text-base font-bold").style("background: linear-gradient(135deg, #f97316 0%, #ea580c 100%) !important; color: #fff !important;")
                            dlg.open()

                        def on_view_report(e):
                            show_report_dialog(e.args.get("id"))

                        table.on("view_report", on_view_report)

                        # 分頁
                        total_pages = max(1, (total + 49) // 50)
                        with ui.row().classes("items-center justify-center gap-3 mt-6"):
                            def prev_page():
                                if rpt_page_state["page"] > 1:
                                    rpt_page_state["page"] -= 1
                                    refresh_reports()
                            def next_page():
                                if rpt_page_state["page"] < total_pages:
                                    rpt_page_state["page"] += 1
                                    refresh_reports()
                            ui.button("◀", on_click=prev_page).props("flat").classes("text-lg").style("padding:8px 16px;")
                            ui.label(f"第 {rpt_page_state['page']} / {total_pages} 頁（共 {total} 筆）").classes("text-base text-slate-500")
                            ui.button("▶", on_click=next_page).props("flat").classes("text-lg").style("padding:8px 16px;")

                refresh_reports()

            # ═══════════════ Tab 3: 案件資料 (scam_records CRUD) ═══════════════
            with ui.tab_panel(tab_cases).style("width:100%"):
                sc_state = {"page": 1, "search": "", "city": ""}
                cases_container = ui.element("div").style("width:100%")

                def refresh_cases():
                    cases_container.clear()
                    rows_data, total = list_scam_cases(
                        search=sc_state["search"], city=sc_state["city"],
                        page=sc_state["page"]
                    )
                    with cases_container:
                        ui.html(f'<div class="stat-row" style="margin-bottom:20px;"><div class="stat-chip"><span class="num">{total:,}</span>筆案件</div></div>', sanitize=False)

                        # 篩選（左邊留白對齊表格儲存格內距，避免搜尋框比表格內容更靠左）
                        with ui.row().classes("items-center gap-4 mb-10").style("padding-left: 14px;"):
                            sc_search = ui.input(placeholder="搜尋標題/城市...", value=sc_state["search"]).props("outlined").classes("w-60 text-base")
                            city_options = {"": "全部城市", **{c: c for c in report_db.CITIES}}
                            sc_city = ui.select(options=city_options, value=sc_state["city"], label="城市").props("outlined stack-label").classes("w-48 text-base filter-select")
                            def do_sc_filter():
                                sc_state["search"] = sc_search.value or ""
                                sc_state["city"] = sc_city.value or ""
                                sc_state["page"] = 1
                                refresh_cases()
                            ui.button("篩選", on_click=do_sc_filter).props("unelevated no-caps").classes("text-base").style(
                                "background:#E65C00 !important;color:#fff !important;border-radius:9999px;padding:10px 22px;")
                            ui.button("＋ 新增案件", on_click=lambda: show_case_dialog(None)).props("unelevated no-caps").classes("text-base").style(
                                "background:#16a34a !important;color:#fff !important;border-radius:9999px;padding:10px 22px;")

                        columns = [
                            {"name":"case_id","label":"案件ID","field":"case_id","align":"left"},
                            {"name":"title","label":"標題","field":"title","align":"left", "style":"max-width:300px;overflow:hidden;text-overflow:ellipsis;"},
                            {"name":"city","label":"城市","field":"city","align":"left"},
                            {"name":"date","label":"日期","field":"date","align":"left"},
                            {"name":"loss_amount","label":"財損","field":"loss_amount","align":"right"},
                            {"name":"actions","label":"操作","field":"actions","align":"center"},
                        ]
                        tbl_rows = []
                        for r in rows_data:
                            tbl_rows.append({
                                "case_id": r.get("case_id",""),
                                "title": (r.get("title","") or "")[:60],
                                "city": r.get("city",""),
                                "date": r.get("date",""),
                                "loss_amount": f"${r.get('loss_amount',0):,.0f}",
                                "actions": r.get("case_id",""),
                            })
                        table = ui.table(columns=columns, rows=tbl_rows, row_key="case_id").classes("w-full").props('flat bordered').style("width:100%")
                        table.add_slot('body-cell-actions', '''
                            <q-td :props="props">
                                <div class="flex gap-3 justify-center">
                                    <q-btn outline rounded icon="edit" label="查看 / 編輯" color="primary"
                                           @click="$parent.$emit('edit_case', props.row)" title="查看詳細/編輯"/>
                                    <q-btn outline rounded icon="delete" label="刪除" color="red"
                                           @click="$parent.$emit('del_case', props.row)" title="刪除"/>
                                </div>
                            </q-td>
                        ''')
                        def on_edit(e):
                            show_case_dialog(e.args.get("case_id"))
                        def on_del(e):
                            cid = e.args.get("case_id")
                            with ui.dialog() as confirm_dlg, ui.card().classes("p-8 rounded-2xl"):
                                ui.label(f"確定要刪除案件「{cid}」嗎？此操作無法復原。").classes("text-[17px] text-slate-700 mb-6")
                                with ui.row().classes("justify-end gap-3 w-full"):
                                    ui.button("取消", on_click=confirm_dlg.close).props("flat no-caps rounded-full").classes("text-slate-500")
                                    def confirm_delete():
                                        delete_scam_case(cid)
                                        confirm_dlg.close()
                                        refresh_cases()
                                        ui.notify(f"案件 {cid} 已刪除", type="warning")
                                    ui.button("確定刪除", on_click=confirm_delete).props("unelevated no-caps rounded-full").style(
                                        "background:#dc2626 !important;color:#fff !important;")
                            confirm_dlg.open()
                        table.on("edit_case", on_edit)
                        table.on("del_case", on_del)

                        total_pages = max(1, (total + 49) // 50)
                        with ui.row().classes("items-center justify-center gap-3 mt-6"):
                            def sc_prev():
                                if sc_state["page"] > 1:
                                    sc_state["page"] -= 1; refresh_cases()
                            def sc_next():
                                if sc_state["page"] < total_pages:
                                    sc_state["page"] += 1; refresh_cases()
                            ui.button("◀", on_click=sc_prev).props("flat").classes("text-lg").style("padding:8px 16px;")
                            ui.label(f"第 {sc_state['page']} / {total_pages} 頁（共 {total:,} 筆）").classes("text-base text-slate-500")
                            ui.button("▶", on_click=sc_next).props("flat").classes("text-lg").style("padding:8px 16px;")

                def show_case_dialog(case_id):
                    existing = get_scam_case(case_id) if case_id else None
                    is_new = existing is None
                    with ui.dialog() as dlg, ui.card().style(
                        "width: 1200px; max-width: 96vw; max-height: 90vh; overflow-y: auto; padding: 48px;"
                    ).classes("rounded-[18px] shadow-2xl bg-white"):
                        ui.label("✨ 新增案件" if is_new else f"📝 案件編輯 (ID: {case_id})").classes("text-[32px] font-bold mb-10 text-[#292524] border-b pb-4")

                        with ui.element("div").classes("flex flex-col lg:flex-row gap-10 w-full mb-10 items-start"):
                            with ui.card().classes("bg-slate-50 flat bordered w-full lg:flex-1 rounded-xl flex flex-col gap-7 shadow-sm").style("padding: 32px;"):
                                ui.label("📌 基本資訊").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                                cid_props = "outlined bg-white stack-label"
                                if not is_new:
                                    cid_props += ' disable hint="案件 ID 為唯一識別碼，建立後無法修改"'
                                f_cid = ui.input(label="案件 ID *", value="" if is_new else str(existing.get("case_id",""))).classes("w-full").props(cid_props)
                                f_date = ui.input(label="日期 (YYYY/MM/DD)", value="" if is_new else existing.get("date","")).classes("w-full").props("outlined bg-white stack-label")
                                f_city = ui.select(options=report_db.CITIES, label="事發城市", value=None if is_new else (existing.get("city") or None)).classes("w-full").props("outlined bg-white stack-label")

                            with ui.card().classes("bg-slate-50 flat bordered w-full lg:flex-1 rounded-xl flex flex-col gap-7 shadow-sm").style("padding: 32px;"):
                                ui.label("💰 案件內容").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                                f_loss = ui.number(label="財損金額", value=0 if is_new else existing.get("loss_amount",0)).classes("w-full").props("outlined bg-white stack-label")
                                f_phone = ui.input(label="涉案電話", value="" if is_new else existing.get("phone_numbers","")).classes("w-full").props("outlined bg-white stack-label")
                                f_fuzzy = ui.input(label="模糊損失描述（無法換算精確金額時填寫）", value="" if is_new else (existing.get("fuzzy_loss_text") or "")).classes("w-full").props("outlined bg-white stack-label")

                        with ui.card().classes("bg-slate-50 flat bordered w-full rounded-xl flex flex-col gap-7 mb-10 shadow-sm").style("padding: 32px;"):
                            ui.label("🔍 進階資訊（與爬蟲/AI 萃取欄位對齊，逗號分隔多筆）").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                            with ui.element("div").classes("flex flex-col lg:flex-row gap-7 w-full"):
                                f_platforms = ui.input(label="涉及平台", placeholder="例：LINE, 超級發財APP",
                                                        value="" if is_new else (existing.get("platforms") or "")).classes("w-full").props("outlined bg-white stack-label")
                                f_websites = ui.input(label="假網站/網址", placeholder="例：www.fake-post.com",
                                                       value="" if is_new else (existing.get("websites") or "")).classes("w-full").props("outlined bg-white stack-label")
                                f_accounts = ui.input(label="詐騙帳號/化名", placeholder="例：陳經理, 台新銀行帳戶",
                                                       value="" if is_new else (existing.get("scam_accounts") or "")).classes("w-full").props("outlined bg-white stack-label")

                        with ui.card().classes("bg-slate-50 flat bordered w-full rounded-xl flex flex-col gap-7 mb-10 shadow-sm").style("padding: 32px;"):
                            ui.label("📝 詳細描述").classes("font-bold text-[#E65C00] text-[18px] mb-1")
                            f_title = ui.input(label="案件標題 *", value="" if is_new else existing.get("title","")).classes("w-full").props("outlined bg-white stack-label")
                            # 多行文字框不用 Quasar 內建的浮動 label：內容捲動時會跟 label 疊在一起，
                            # 這裡上方已有同名的區塊標題「詳細描述」，直接省略欄位自己的 label。
                            f_desc = ui.textarea(value="" if is_new else existing.get("summary","")).classes("w-full").props("outlined bg-white rows=6")

                        with ui.row().classes("dialog-footer-row w-full justify-between items-center pt-6 border-t"):
                            if not is_new:
                                ui.label(f"建立時間: {existing.get('date','')}").classes("text-[17px] text-slate-400")
                            else:
                                ui.element("div")
                            with ui.row().classes("items-center gap-4"):
                                ui.button("取消", on_click=dlg.close).props("flat no-caps rounded-full").classes("text-slate-500 text-base px-6")
                                def save():
                                    if not (f_cid.value or "").strip() or not (f_title.value or "").strip():
                                        ui.notify("請輸入案件 ID 與標題", type="warning")
                                        return
                                    d = {"case_id": f_cid.value, "title": f_title.value,
                                         "city": f_city.value or "", "date": f_date.value,
                                         "loss_amount": f_loss.value or 0,
                                         "phone_numbers": f_phone.value, "summary": f_desc.value,
                                         "fuzzy_loss_text": f_fuzzy.value or "",
                                         "platforms": f_platforms.value or "",
                                         "websites": f_websites.value or "",
                                         "scam_accounts": f_accounts.value or ""}
                                    if is_new:
                                        new_id = create_scam_case(d)
                                        if new_id is None:
                                            ui.notify("新增失敗，案件 ID 可能已存在", type="negative")
                                            return
                                        ui.notify("已新增", type="positive")
                                    else:
                                        ok = update_scam_case(case_id, d)
                                        if not ok:
                                            ui.notify("更新失敗", type="negative")
                                            return
                                        ui.notify("已更新", type="positive")
                                    dlg.close()
                                    refresh_cases()
                                ui.button("儲存變更", on_click=save).props("unelevated no-caps").classes("rounded-full px-8 text-base font-bold").style("background: linear-gradient(135deg, #f97316 0%, #ea580c 100%) !important; color: #fff !important;")
                    dlg.open()

                refresh_cases()
