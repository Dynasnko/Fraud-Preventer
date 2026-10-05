"""
我的通報（一般使用者，唯讀）
路由: /my-reports
只顯示登入者自己帳號送出的通報記錄（report_db.get_user_reports），不含他人資料。
"""
from nicegui import ui
from Model import report_db
from View.components import render_navbar
from Controller.auth_middleware import require_login, get_current_user

MY_REPORTS_CSS = """
<style>
.my-reports-main {
  width: 100% !important; padding: 40px 48px 110px 48px; box-sizing: border-box;
  display: flex; flex-direction: column; gap: 32px;
  max-width: 1600px !important;
  margin: 0 auto 60px auto;
}
.my-reports-title {
  font-size: 32px; font-weight: 700; color: #292524;
  display: flex; align-items: center; gap: 12px;
}
.my-reports-main .stat-row { display: flex; gap: 20px; flex-wrap: wrap; }
.my-reports-main .stat-chip {
  background: rgba(255,255,255,0.6); backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.8); border-radius: 14px;
  padding: 18px 28px; font-size: 16px; font-weight: 600; color: #292524;
  box-shadow: 0 2px 8px rgba(0,0,0,0.03);
}
.my-reports-main .stat-chip .num { font-size: 28px; font-weight: 700; color: #E65C00; margin-right: 8px; }

.status-badge {
  padding: 5px 14px; border-radius: 9999px; font-size: 14px; font-weight: 600;
  display: inline-block;
}
.badge-pending   { background: #FFF5E6; color: #E65C00; }
.badge-reviewing { background: #DBEAFE; color: #2563EB; }
.badge-resolved  { background: #DCFCE7; color: #16A34A; }
.badge-closed    { background: #F1F5F9; color: #64748B; }

.my-reports-main .q-table,
.my-reports-main .q-table__container,
.my-reports-main .q-table__middle {
  width: 100% !important; max-width: 100% !important;
}
.my-reports-main table.q-table { width: 100% !important; table-layout: auto; }
.my-reports-main .q-table th,
.my-reports-main .q-table td {
  white-space: nowrap; padding: 16px 26px !important; font-size: 15px;
}
.my-reports-main .q-table th { font-size: 15.5px; font-weight: 700; color: #292524; }
.my-reports-main .q-table .q-btn {
  font-size: 15px !important; padding: 10px 20px !important; min-height: 40px;
}
.my-reports-main .q-table .q-btn .q-icon { font-size: 20px !important; }

.mr-detail-label {
  font-size: 13px; font-weight: 600; color: #E65C00; margin-bottom: 4px;
}
.mr-detail-value {
  font-size: 16px; color: #292524; margin-bottom: 18px; white-space: pre-wrap; word-break: break-word;
}
.mr-empty-state {
  padding: 60px 20px; text-align: center; color: #94a3b8; font-size: 16px;
  display: flex; flex-direction: column; align-items: center; gap: 16px;
}
</style>
"""


@ui.page("/my-reports")
@require_login
async def my_reports_page():
    ui.add_head_html(MY_REPORTS_CSS, shared=False)
    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch')
    render_navbar(active='my_reports')

    current_user = get_current_user()
    all_reports = report_db.get_user_reports(current_user["id"])

    state = {"search": ""}

    with ui.element("main").classes("my-reports-main"):
        ui.html('<div class="my-reports-title">📋 我的通報</div>', sanitize=False)

        container = ui.element("div").style("width:100%")

        def show_detail(report_id):
            rpt = report_db.get_report(report_id)
            if not rpt:
                ui.notify("找不到該通報", type="warning")
                return
            badge_map = {"pending": "badge-pending", "reviewing": "badge-reviewing",
                         "resolved": "badge-resolved", "closed": "badge-closed"}
            status = rpt.get("status", "pending")
            status_label = report_db.STATUS_LABELS.get(status, status)
            with ui.dialog() as dlg, ui.card().style(
                "width: 1100px; max-width: 96vw; max-height: 90vh; overflow-y: auto; padding: 48px;"
            ).classes("rounded-[18px] shadow-2xl bg-white"):
                with ui.row().classes("w-full items-center justify-between mb-8 border-b pb-4"):
                    ui.label(f"📋 通報詳細 (#{report_id})").classes("text-[28px] font-bold text-[#292524]")
                    ui.html(f'<span class="status-badge {badge_map.get(status,"badge-pending")}">{status_label}</span>', sanitize=False)

                with ui.element("div").classes("flex flex-col lg:flex-row gap-10 w-full mb-4 items-start"):
                    with ui.element("div").classes("w-full lg:flex-1"):
                        ui.label("👤 通報者資訊").classes("font-bold text-[#E65C00] text-[18px] mb-3")
                        for label, key in [("姓名", "reporter_name"), ("電話", "reporter_phone"), ("Email", "reporter_email")]:
                            ui.html(f'<div class="mr-detail-label">{label}</div>', sanitize=False)
                            ui.html(f'<div class="mr-detail-value">{rpt.get(key,"") or "—"}</div>', sanitize=False)

                        ui.label("⚠️ 涉詐資料").classes("font-bold text-[#E65C00] text-[18px] mb-3 mt-4")
                        for label, key in [("涉詐電話", "suspect_phone"), ("涉詐LINE", "suspect_line_id"),
                                           ("涉詐網址", "suspect_url"), ("涉詐帳號", "bank_account")]:
                            ui.html(f'<div class="mr-detail-label">{label}</div>', sanitize=False)
                            ui.html(f'<div class="mr-detail-value">{rpt.get(key,"") or "—"}</div>', sanitize=False)

                    with ui.element("div").classes("w-full lg:flex-1"):
                        ui.label("📄 案件資訊").classes("font-bold text-[#E65C00] text-[18px] mb-3")
                        is_victim_val = "已受騙（有實際財損）" if rpt.get("is_victim") else "尚未受騙"
                        for label, val in [
                            ("是否已受騙", is_victim_val),
                            ("詐騙管道", rpt.get("fraud_channel", "")),
                            ("詐騙類型", rpt.get("fraud_type", "")),
                            ("事發地區", rpt.get("city", "")),
                            ("財損金額", f"${rpt.get('loss_amount',0):,.0f}"),
                        ]:
                            ui.html(f'<div class="mr-detail-label">{label}</div>', sanitize=False)
                            ui.html(f'<div class="mr-detail-value">{val or "—"}</div>', sanitize=False)

                        ui.label("📝 詳細說明").classes("font-bold text-[#E65C00] text-[18px] mb-3 mt-4")
                        ui.html(f'<div class="mr-detail-value">{rpt.get("description","") or "—"}</div>', sanitize=False)

                with ui.row().classes("w-full items-center justify-between border-t pt-6"):
                    ui.label(f"通報時間: {(rpt.get('created_at','') or '')[:16]}").classes("text-[15px] text-slate-400")
                    ui.button("關閉", on_click=dlg.close).props("unelevated no-caps").classes(
                        "rounded-full px-8 text-base font-bold"
                    ).style("background: linear-gradient(135deg, #f97316 0%, #ea580c 100%) !important; color: #fff !important;")
            dlg.open()

        def refresh():
            container.clear()
            with container:
                if not all_reports:
                    with ui.element("div").classes("mr-empty-state"):
                        ui.label("📭 尚未提交任何通報")
                        ui.link("點此提交通報", "/report").classes("text-base").style(
                            "color:#E65C00;font-weight:600;text-decoration:underline;"
                        )
                    return

                keyword = state["search"].strip()
                if keyword:
                    filtered = [
                        r for r in all_reports
                        if keyword in (r.get("fraud_type") or "") or keyword in (r.get("description") or "")
                    ]
                else:
                    filtered = all_reports

                ui.html(
                    f'<div class="stat-row" style="margin-bottom:20px;"><div class="stat-chip"><span class="num">{len(all_reports)}</span>筆通報</div></div>',
                    sanitize=False,
                )

                with ui.row().classes("items-center gap-4 mb-6"):
                    search_input = ui.input(placeholder="搜尋詐騙類型/描述...", value=state["search"]).props("outlined").classes("w-72 text-base")

                    def do_filter():
                        state["search"] = search_input.value or ""
                        refresh()

                    ui.button("篩選", on_click=do_filter).props("unelevated no-caps").classes("text-base").style(
                        "background:#E65C00 !important;color:#fff !important;border-radius:9999px;padding:10px 22px;"
                    )

                if not filtered:
                    ui.html('<div style="padding:40px;text-align:center;color:#94a3b8;font-size:16px;">找不到符合條件的通報</div>', sanitize=False)
                    return

                badge_map = {"pending": "badge-pending", "reviewing": "badge-reviewing",
                             "resolved": "badge-resolved", "closed": "badge-closed"}
                columns = [
                    {"name": "created_at", "label": "通報時間", "field": "created_at", "align": "left"},
                    {"name": "fraud_type", "label": "詐騙類型", "field": "fraud_type", "align": "left"},
                    {"name": "status", "label": "狀態", "field": "status", "align": "center"},
                    {"name": "loss_amount", "label": "財損", "field": "loss_amount", "align": "right"},
                    {"name": "actions", "label": "操作", "field": "actions", "align": "center"},
                ]
                tbl_rows = []
                for r in filtered:
                    tbl_rows.append({
                        "id": r["id"],
                        "created_at": (r.get("created_at", "") or "")[:16],
                        "fraud_type": r.get("fraud_type", ""),
                        "status": r.get("status", "pending"),
                        "status_label": report_db.STATUS_LABELS.get(r.get("status", "pending"), r.get("status", "pending")),
                        "loss_amount": f"${r.get('loss_amount', 0):,.0f}",
                        "actions": r["id"],
                    })
                table = ui.table(columns=columns, rows=tbl_rows, row_key="id").classes("w-full").props('flat bordered').style("width:100%")
                table.add_slot('body-cell-status', '''
                    <q-td :props="props">
                        <q-badge :class="'status-badge badge-' + props.value" :label="props.row.status_label" />
                    </q-td>
                ''')
                table.add_slot('body-cell-actions', '''
                    <q-td :props="props">
                        <q-btn outline rounded icon="visibility" label="查看" color="primary"
                               @click="$parent.$emit('view_report', props.row)" title="查看詳細"/>
                    </q-td>
                ''')

                def on_view(e):
                    show_detail(e.args.get("id"))

                table.on("view_report", on_view)

        refresh()
