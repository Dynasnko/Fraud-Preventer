"""
案例查詢（一般使用者，唯讀）
路由: /cases
資料來源與管理後台「案件資料」分頁相同（scam_cases），透過 scam_db.py 唯讀存取。
"""
from nicegui import ui
from Model import report_db
from Model import scam_db
from View.components import render_navbar
from Controller.auth_middleware import require_login

CASE_QUERY_CSS = """
<style>
.case-query-main {
  width: 100% !important; padding: 40px 48px 110px 48px; box-sizing: border-box;
  display: flex; flex-direction: column; gap: 32px;
  max-width: 1600px !important;
  margin: 0 auto 60px auto;
}
.case-query-title {
  font-size: 32px; font-weight: 700; color: #292524;
  display: flex; align-items: center; gap: 12px;
}
.case-query-main .stat-row { display: flex; gap: 20px; flex-wrap: wrap; }
.case-query-main .stat-chip {
  background: rgba(255,255,255,0.6); backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.8); border-radius: 14px;
  padding: 18px 28px; font-size: 16px; font-weight: 600; color: #292524;
  box-shadow: 0 2px 8px rgba(0,0,0,0.03);
}
.case-query-main .stat-chip .num { font-size: 28px; font-weight: 700; color: #E65C00; margin-right: 8px; }

.case-query-main .q-table,
.case-query-main .q-table__container,
.case-query-main .q-table__middle {
  width: 100% !important; max-width: 100% !important;
}
.case-query-main table.q-table { width: 100% !important; table-layout: auto; }
.case-query-main .q-table th,
.case-query-main .q-table td {
  white-space: nowrap; padding: 16px 26px !important; font-size: 15px;
}
.case-query-main .q-table th { font-size: 15.5px; font-weight: 700; color: #292524; }
.case-query-main .q-table .q-btn {
  font-size: 15px !important; padding: 10px 20px !important; min-height: 40px;
}
.case-query-main .q-table .q-btn .q-icon { font-size: 20px !important; }

.q-dialog .q-field--outlined .q-field__control {
  padding-top: 10px; min-height: 88px !important;
}
.q-dialog .q-field--outlined.q-field--labeled .q-field__native,
.q-dialog .q-field--outlined.q-field--labeled textarea.q-field__native {
  padding-top: 30px !important;
}
.q-dialog .q-field__native, .q-dialog textarea.q-field__native { font-size: 19px !important; }
.q-dialog textarea.q-field__native { min-height: 210px !important; }
.q-dialog .q-field { margin-bottom: 10px; }

.cq-detail-label {
  font-size: 13px; font-weight: 600; color: #E65C00; margin-bottom: 4px;
}
.cq-detail-value {
  font-size: 16px; color: #292524; margin-bottom: 18px; white-space: pre-wrap; word-break: break-word;
}

/* 城市篩選下拉選單：label 跟已選值會因 Tailwind preflight 疊在一起，補回 padding-top。 */
.filter-select.q-field--outlined .q-field__control {
  padding-top: 6px;
}
.filter-select.q-field--outlined.q-field--labeled .q-field__native {
  padding-top: 16px !important;
}
</style>
"""


@ui.page("/cases")
@require_login
async def case_query_page():
    ui.add_head_html(CASE_QUERY_CSS, shared=False)
    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch')
    render_navbar(active='cases')

    scam_db.ensure_indexes()

    state = {"page": 1, "search": "", "city": ""}

    with ui.element("main").classes("case-query-main"):
        ui.html('<div class="case-query-title">🔍 案例查詢</div>', sanitize=False)

        container = ui.element("div").style("width:100%")

        def show_detail(case_id):
            case = scam_db.get_scam_case(case_id)
            if not case:
                ui.notify("找不到該案件", type="warning")
                return
            with ui.dialog() as dlg, ui.card().style(
                "width: 900px; max-width: 96vw; max-height: 90vh; overflow-y: auto; padding: 48px;"
            ).classes("rounded-[18px] shadow-2xl bg-white"):
                ui.label(f"📄 案件詳情 (ID: {case_id})").classes("text-[28px] font-bold mb-8 text-[#292524] border-b pb-4")

                with ui.element("div").classes("flex flex-col lg:flex-row gap-10 w-full mb-4 items-start"):
                    with ui.element("div").classes("w-full lg:flex-1"):
                        ui.html('<div class="cq-detail-label">案件 ID</div>', sanitize=False)
                        ui.html(f'<div class="cq-detail-value">{case.get("case_id","") or "—"}</div>', sanitize=False)
                        ui.html('<div class="cq-detail-label">日期</div>', sanitize=False)
                        ui.html(f'<div class="cq-detail-value">{case.get("date","") or "—"}</div>', sanitize=False)
                        ui.html('<div class="cq-detail-label">城市</div>', sanitize=False)
                        ui.html(f'<div class="cq-detail-value">{case.get("city","") or "—"}</div>', sanitize=False)
                    with ui.element("div").classes("w-full lg:flex-1"):
                        ui.html('<div class="cq-detail-label">財損金額</div>', sanitize=False)
                        ui.html(f'<div class="cq-detail-value">${case.get("loss_amount",0):,.0f}</div>', sanitize=False)
                        ui.html('<div class="cq-detail-label">涉案電話</div>', sanitize=False)
                        ui.html(f'<div class="cq-detail-value">{case.get("phone_numbers","") or "—"}</div>', sanitize=False)

                ui.html('<div class="cq-detail-label">案件標題</div>', sanitize=False)
                ui.html(f'<div class="cq-detail-value">{case.get("title","") or "—"}</div>', sanitize=False)
                ui.html('<div class="cq-detail-label">詳細描述</div>', sanitize=False)
                ui.html(f'<div class="cq-detail-value">{case.get("summary","") or "—"}</div>', sanitize=False)

                with ui.row().classes("w-full justify-end pt-6 border-t"):
                    ui.button("關閉", on_click=dlg.close).props("unelevated no-caps").classes(
                        "rounded-full px-8 text-base font-bold"
                    ).style("background: linear-gradient(135deg, #f97316 0%, #ea580c 100%) !important; color: #fff !important;")
            dlg.open()

        def refresh():
            container.clear()
            rows_data, total = scam_db.list_scam_cases(
                search=state["search"], city=state["city"], page=state["page"]
            )
            with container:
                ui.html(
                    f'<div class="stat-row" style="margin-bottom:20px;"><div class="stat-chip"><span class="num">{total:,}</span>筆案件</div></div>',
                    sanitize=False,
                )

                with ui.row().classes("items-center gap-4 mb-6"):
                    search_input = ui.input(placeholder="搜尋標題/城市...", value=state["search"]).props("outlined").classes("w-60 text-base")
                    city_options = {"": "全部城市", **{c: c for c in report_db.CITIES}}
                    city_select = ui.select(options=city_options, value=state["city"], label="城市").props("outlined stack-label").classes("w-48 text-base filter-select")

                    def do_filter():
                        state["search"] = search_input.value or ""
                        state["city"] = city_select.value or ""
                        state["page"] = 1
                        refresh()

                    ui.button("篩選", on_click=do_filter).props("unelevated no-caps").classes("text-base").style(
                        "background:#E65C00 !important;color:#fff !important;border-radius:9999px;padding:10px 22px;"
                    )

                if total == 0:
                    ui.html('<div style="padding:40px;text-align:center;color:#94a3b8;font-size:16px;">找不到符合條件的案例</div>', sanitize=False)
                    return

                columns = [
                    {"name": "case_id", "label": "案件ID", "field": "case_id", "align": "left"},
                    {"name": "title", "label": "標題", "field": "title", "align": "left", "style": "max-width:300px;overflow:hidden;text-overflow:ellipsis;"},
                    {"name": "city", "label": "城市", "field": "city", "align": "left"},
                    {"name": "date", "label": "日期", "field": "date", "align": "left"},
                    {"name": "loss_amount", "label": "財損", "field": "loss_amount", "align": "right"},
                    {"name": "actions", "label": "操作", "field": "actions", "align": "center"},
                ]
                tbl_rows = []
                for r in rows_data:
                    tbl_rows.append({
                        "case_id": r.get("case_id", ""),
                        "title": (r.get("title", "") or "")[:60],
                        "city": r.get("city", ""),
                        "date": r.get("date", ""),
                        "loss_amount": f"${r.get('loss_amount', 0):,.0f}",
                        "actions": r.get("case_id", ""),
                    })
                table = ui.table(columns=columns, rows=tbl_rows, row_key="case_id").classes("w-full").props('flat bordered').style("width:100%")
                table.add_slot('body-cell-actions', '''
                    <q-td :props="props">
                        <q-btn outline rounded icon="visibility" label="查看" color="primary"
                               @click="$parent.$emit('view_case', props.row)" title="查看詳細"/>
                    </q-td>
                ''')

                def on_view(e):
                    show_detail(e.args.get("case_id"))

                table.on("view_case", on_view)

                total_pages = max(1, (total + 49) // 50)
                with ui.row().classes("items-center justify-center gap-3 mt-6"):
                    def prev_page():
                        if state["page"] > 1:
                            state["page"] -= 1; refresh()

                    def next_page():
                        if state["page"] < total_pages:
                            state["page"] += 1; refresh()

                    ui.button("◀", on_click=prev_page).props("flat").classes("text-lg").style("padding:8px 16px;")
                    ui.label(f"第 {state['page']} / {total_pages} 頁（共 {total:,} 筆）").classes("text-base text-slate-500")
                    ui.button("▶", on_click=next_page).props("flat").classes("text-lg").style("padding:8px 16px;")

        refresh()
