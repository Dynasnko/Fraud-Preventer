"""
165 Anti-Fraud Dashboard — NiceGUI implementation
Design: DESIGN.md spec (4.25px rhythm, #E65C00, glass surfaces)
Data: static placeholders (0000) — replace with DB sync later
"""
from nicegui import ui
from View.components import render_navbar
from Controller.auth_middleware import require_login
import sqlite3
import os
import pathlib

def fetch_dashboard_data():
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AllInOneProject", "chroma_dbs", "scam_records.sqlite3")
    
    kpi_cards = [
        {"icon": "☎️", "label": "總受理案件",    "value": "0", "unit": "件",  "delta": "即時"},
        {"icon": "💸", "label": "總財損金額",    "value": "0", "unit": "萬元","delta": "即時"},
        {"icon": "🚨", "label": "近期通報",      "value": "0", "unit": "件",  "delta": "即時"},
        {"icon": "📱", "label": "電話舉報總數",  "value": "0", "unit": "通",  "delta": "即時"},
    ]
    top_frauds = []
    monthly_trend = []
    region_table = []
    age_groups = [
        {"group": "18歲以下", "pct": 5},
        {"group": "19–30歲",  "pct": 25},
        {"group": "31–40歲",  "pct": 30},
        {"group": "41–50歲",  "pct": 20},
        {"group": "51–65歲",  "pct": 15},
        {"group": "65歲以上", "pct": 5},
    ] # Static fallback
    
    if not os.path.exists(db_path):
        return kpi_cards, top_frauds, monthly_trend, region_table, age_groups

    try:
        conn = sqlite3.connect(f"{pathlib.Path(db_path).as_uri()}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*), SUM(loss_amount) FROM scam_cases")
        row = cursor.fetchone()
        total_cases = row[0] or 0
        total_loss = row[1] or 0
        
        cursor.execute("SELECT COUNT(*) FROM scam_cases WHERE phone_numbers != ''")
        phone_reports = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM scam_cases WHERE date >= date('now', '-7 days')")
        recent_cases = cursor.fetchone()[0] or 0
        if recent_cases == 0:
            cursor.execute("SELECT MAX(date) FROM scam_cases")
            last_date = cursor.fetchone()[0]
            if last_date:
                cursor.execute("SELECT COUNT(*) FROM scam_cases WHERE date >= date(?, '-7 days')", (last_date,))
                recent_cases = cursor.fetchone()[0] or 0
        
        kpi_cards[0]["value"] = f"{total_cases:,}"
        kpi_cards[1]["value"] = f"{total_loss // 10000:,}"
        kpi_cards[2]["value"] = f"{recent_cases:,}"
        kpi_cards[3]["value"] = f"{phone_reports:,}"
        
        cursor.execute("SELECT city, COUNT(*) as c, SUM(loss_amount) FROM scam_cases GROUP BY city ORDER BY c DESC LIMIT 6")
        for r in cursor.fetchall():
            region_table.append({
                "region": r[0] if r[0] else "未知",
                "cases": f"{r[1]:,}",
                "loss": f"{(r[2] or 0) // 10000:,}"
            })
            
        cursor.execute("SELECT substr(date, 1, 7) as m, COUNT(*), SUM(loss_amount) FROM scam_cases GROUP BY m ORDER BY m DESC LIMIT 6")
        trend_rows = cursor.fetchall()
        for r in reversed(trend_rows):
            monthly_trend.append({
                "month": r[0],
                "cases": r[1],
                "loss": r[2] or 0
            })
            
        fraud_types = ["假投資", "解除分期", "假網購", "假交友", "猜猜我是誰"]
        for i, ft in enumerate(fraud_types, 1):
            cursor.execute("SELECT COUNT(*) FROM scam_cases WHERE title LIKE ?", (f"%{ft}%",))
            c = cursor.fetchone()[0]
            top_frauds.append({"rank": i, "type": ft, "count": c})
            
        top_frauds.sort(key=lambda x: x['count'], reverse=True)
        for i, ft in enumerate(top_frauds, 1):
            ft["rank"] = i
            ft["count"] = f"{ft['count']:,}"
            
        conn.close()
    except Exception as e:
        print("SQL Error:", e)
        
    return kpi_cards, top_frauds, monthly_trend, region_table, age_groups

# ── 設計 Token ──────────────────────────────────────────────────────────────
PRIMARY   = "#E65C00"
SECONDARY = "#FFB380"
TERTIARY  = "#FFF5E6"
SURFACE   = "#FDFBF7"
NEUTRAL   = "#78716C"
TEXT_PRI  = "#78716C"
TEXT_SEC  = "#292524"
BORDER    = "#E7E5E4"

# ── KPI 資料 (全部 0000，後續接 DB) ────────────────────────────────────────
KPI_CARDS = [
    {"icon": "☎️", "label": "今日受理案件",    "value": "0,000", "unit": "件",  "delta": "+0%"},
    {"icon": "💸", "label": "今日財損金額",    "value": "0,000", "unit": "萬元","delta": "+0%"},
    {"icon": "🚨", "label": "今日攔截金額",    "value": "0,000", "unit": "萬元","delta": "+0%"},
    {"icon": "📱", "label": "今日詐騙電話舉報", "value": "0,000", "unit": "通",  "delta": "+0%"},
]

TOP_FRAUD_TYPES = [
    {"rank": 1, "type": "網路購物詐騙", "count": "0,000", "pct": 0},
    {"rank": 2, "type": "假交友投資詐騙", "count": "0,000", "pct": 0},
    {"rank": 3, "type": "解除分期付款詐騙", "count": "0,000", "pct": 0},
    {"rank": 4, "type": "假冒政府機關詐騙", "count": "0,000", "pct": 0},
    {"rank": 5, "type": "猜猜我是誰詐騙", "count": "0,000", "pct": 0},
]

MONTHLY_TREND = [
    {"month": "1月", "cases": 0, "loss": 0},
    {"month": "2月", "cases": 0, "loss": 0},
    {"month": "3月", "cases": 0, "loss": 0},
    {"month": "4月", "cases": 0, "loss": 0},
    {"month": "5月", "cases": 0, "loss": 0},
    {"month": "6月", "cases": 0, "loss": 0},
]

AGE_GROUPS = [
    {"group": "18歲以下", "pct": 0},
    {"group": "19–30歲",  "pct": 0},
    {"group": "31–40歲",  "pct": 0},
    {"group": "41–50歲",  "pct": 0},
    {"group": "51–65歲",  "pct": 0},
    {"group": "65歲以上", "pct": 0},
]

REGION_TABLE = [
    {"region": "臺北市", "cases": "0,000", "loss": "0,000"},
    {"region": "新北市", "cases": "0,000", "loss": "0,000"},
    {"region": "桃園市", "cases": "0,000", "loss": "0,000"},
    {"region": "臺中市", "cases": "0,000", "loss": "0,000"},
    {"region": "臺南市", "cases": "0,000", "loss": "0,000"},
    {"region": "高雄市", "cases": "0,000", "loss": "0,000"},
]

# ── Global CSS ───────────────────────────────────────────────────────────────
ui.add_head_html("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
:root {
  --primary:   #E65C00;
  --secondary: #FFB380;
  --tertiary:  #FFF5E6;
  --surface:   #FDFBF7;
  --neutral:   #78716C;
  --txt-pri:   #78716C;
  --txt-sec:   #292524;
  --border:    #E7E5E4;
  --base:      4.25px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  width: 100%; min-height: 100vh;
  margin: 0; padding: 0;
  background: 
    radial-gradient(at 0% 0%, hsla(28, 100%, 94%, 1) 0, transparent 50%), 
    radial-gradient(at 50% 0%, hsla(210, 100%, 96%, 1) 0, transparent 50%), 
    radial-gradient(at 100% 0%, hsla(33, 100%, 92%, 1) 0, transparent 50%);
  background-color: #f8fafc;
  font-family: Inter, sans-serif;
  color: var(--txt-sec);
  overflow-x: hidden;
}
.q-layout, .q-page-container, .q-page, .nicegui-content {
  background: transparent !important;
  width: 100% !important;
  max-width: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
  min-height: 100vh !important;
  box-sizing: border-box !important;
}

/* ── Glass surface & Shell ── */
.grad-shell {
  padding: 4.25px;
  border-radius: 21.25px;
  background: linear-gradient(135deg, rgb(253, 251, 247) 0%, rgb(247, 244, 235) 100%);
  box-shadow: rgba(230,92,0,0.06) 0px 4px 24px 0px;
  transition: transform 200ms ease, box-shadow 200ms ease;
  height: 100%;
}
.grad-shell:hover {
  transform: translateY(-2px);
  box-shadow: rgba(230,92,0,0.12) 0px 8px 32px 0px;
}
.glass {
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(64px);
  -webkit-backdrop-filter: blur(64px);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 17px;
  box-shadow:
    rgba(255, 255, 255, 0.8) 0px 1px 0px 0px inset,
    rgba(0, 0, 0, 0.02) 0px 4px 20px 0px;
  height: 100%;
}

/* ── Page wrapper ── */
.dash-main {
  width: 100%;
  margin: 0;
  padding: 34px;
  display: flex;
  flex-direction: column;
  gap: 25.5px;
  box-sizing: border-box;
}

/* ── Section title ── */
.section-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--txt-sec);
  letter-spacing: 0.08em;
  margin-bottom: 8.5px;
  display: flex; align-items: center; gap: 8px;
}
.section-title::before {
  content: ''; display: block; width: 4px; height: 16px;
  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);
  border-radius: 4px;
}

/* ── KPI grid ── */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 25.5px;
}
.kpi-card {
  padding: 25.5px;
  display: flex;
  flex-direction: column;
  gap: 12.75px;
}
.kpi-icon { font-size: 26px; }
.kpi-label { font-size: 15px; color: var(--txt-pri); font-weight: 500; }
.kpi-value {
  font-size: 38px;
  font-weight: 700;
  color: var(--primary);
  line-height: 1;
  letter-spacing: -0.025em;
}
.kpi-unit { font-size: 15px; font-weight: 600; color: var(--txt-pri); }
.kpi-delta {
  font-size: 12px;
  background: var(--tertiary);
  color: var(--primary);
  padding: 4px 10px;
  border-radius: 9999px;
  width: fit-content;
  font-weight: 600;
}

/* ── Grid Layouts ── */
.row-chart-donut {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 25.5px;
  align-items: start;
}
.row-rank-table {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 25.5px;
}

/* ── Panel ── */
.panel {
  padding: 25.5px;
  display: flex;
  flex-direction: column;
  gap: 17px;
}
.panel-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--txt-sec);
  display: flex;
  align-items: center;
  gap: 8.5px;
  margin-bottom: 8.5px;
}
.panel-title::before {
  content: '';
  width: 4px; height: 16px;
  background: var(--primary);
  border-radius: 9999px;
}

/* ── Rank rows ── */
.rank-row {
  display: flex;
  align-items: center;
  gap: 12.75px;
  padding: 12.75px 8.5px;
  border-bottom: 1px solid var(--border);
  transition: background 150ms ease;
}
.rank-row:last-child { border-bottom: none; }
.rank-row:hover { background: rgba(230,92,0,0.03); border-radius: 12px; }
.rank-num {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: var(--tertiary);
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.rank-num.top { background: var(--primary); color: #fff; box-shadow: rgba(230,92,0,0.3) 0px 4px 12px; }
.rank-label { flex: 1; font-size: 15px; font-weight: 500; color: var(--txt-sec); }
.rank-count { font-size: 15px; font-weight: 700; color: var(--primary); }

/* ── Simulated bar chart ── */
.bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 12.75px;
  height: 195px;
  padding: 17px 8.5px 0 8.5px;
  flex: 1;
}
.bar-col { display: flex; flex-direction: column; align-items: center; gap: 6px; flex: 1; height: 100%; justify-content: flex-end; }
.bar-value { font-size: 12px; font-weight: 700; color: var(--primary); white-space: nowrap; }
.bar-fill {
  width: 100%;
  background: linear-gradient(180deg, var(--secondary) 0%, var(--primary) 100%);
  border-radius: 6px 6px 0 0;
  min-height: 4px;
  transition: height 500ms cubic-bezier(0.4,0,0.2,1);
  box-shadow: 0 4px 12px rgba(230,92,0,0.15);
}
.bar-fill:hover {
  filter: brightness(1.1);
}
.bar-x { font-size: 13px; font-weight: 500; color: var(--txt-pri); }

/* ── Age donut placeholder ── */
.donut-wrap {
  display: flex;
  flex-direction: column;
  gap: 17px;
  flex: 1;
  justify-content: center;
}
.age-row {
  display: flex;
  align-items: center;
  gap: 12.75px;
}
.age-label { font-size: 13px; font-weight: 500; color: var(--txt-pri); width: 80px; flex-shrink: 0; }
.age-bar-wrap { flex: 1; height: 8px; background: rgba(255,255,255,0.5); border: 1px solid var(--border); border-radius: 9999px; overflow: hidden; }
.age-bar { height: 100%; background: linear-gradient(90deg, var(--secondary), var(--primary)); border-radius: 9999px; }
.age-pct { font-size: 13px; color: var(--primary); font-weight: 700; width: 40px; text-align: right; flex-shrink: 0; }

/* ── Table ── */
.table-wrap {
  width: 100%;
  overflow-x: auto;
}
.data-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 14.5px; }
.data-table th {
  text-align: left;
  padding: 12.75px 17px;
  color: var(--txt-pri);
  font-weight: 600;
  border-bottom: 2px solid var(--border);
  font-size: 13px;
  letter-spacing: 0.05em;
}
.data-table td {
  padding: 17px;
  color: var(--txt-sec);
  border-bottom: 1px solid var(--border);
  transition: background 150ms;
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(230,92,0,0.04); }
.td-accent { color: var(--primary); font-weight: 700; font-size: 15.5px; }

/* ── Footer ── */
.dash-footer {
  text-align: center;
  font-size: 13px;
  color: var(--txt-pri);
  padding: 25.5px;
  border-top: 1px solid rgba(0,0,0,0.05);
  margin-top: 17px;
}

/* ── Responsive ── */
@media (max-width: 1024px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .row-chart-donut, .row-rank-table { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .kpi-grid { grid-template-columns: 1fr; }
  .dash-main { padding: 17px; }
  .bar-chart { height: 160px; }
}

/* ── Entrance animation ── */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.grad-shell { animation: fadeUp 500ms ease both; }
.grad-shell:nth-child(1) { animation-delay: 50ms; }
.grad-shell:nth-child(2) { animation-delay: 100ms; }
.grad-shell:nth-child(3) { animation-delay: 150ms; }
.grad-shell:nth-child(4) { animation-delay: 200ms; }
</style>
""", shared=True)

@ui.page("/dashboard")
@require_login
async def dashboard():
    kpi_cards, top_frauds, monthly_trend, region_table, age_groups = fetch_dashboard_data()

    ui.query('.nicegui-content').classes('!w-full !max-w-none !p-0 !m-0 !items-stretch')

    # ── Navbar ────────────────────────────────────────────────────────────────
    render_navbar(active='dashboard')

    # ── Main ─────────────────────────────────────────────────────────────────
    with ui.element("main").classes("dash-main w-full"):

        # ── Row 1: KPI Cards ──────────────────────────────────────────────
        ui.html('<p class="section-title">今日關鍵指標</p>', sanitize=False)
        kpi_html = '<div class="kpi-grid" role="list">'
        for card in kpi_cards:
            kpi_html += f"""
<article class="grad-shell" role="listitem" aria-label="{card['label']}">
  <div class="kpi-card glass">
    <span class="kpi-icon" aria-hidden="true">{card['icon']}</span>
    <span class="kpi-label">{card['label']}</span>
    <div style="display:flex;align-items:baseline;gap:6px;">
      <span class="kpi-value">{card['value']}</span>
      <span class="kpi-unit">{card['unit']}</span>
    </div>
    <span class="kpi-delta" aria-label="較昨日變化">{card['delta']} 較昨日</span>
  </div>
</article>"""
        kpi_html += "</div>"
        ui.html(kpi_html, sanitize=False)

        # ── Row 2: 長條圖 (2fr) + 年齡環狀圖 (1fr) ───────────────────────
        with ui.element("div").classes("row-chart-donut"):

            # 左：月趨勢 bar chart（長條高度依當前資料的最大值等比縮放，確保永遠塞得進容器；
            # 數值標籤另外算好高度，避免跟長條頂端重疊或被容器裁掉）
            max_cases = max((m['cases'] for m in monthly_trend), default=0) or 1
            MAX_BAR_HEIGHT = 110  # px，容器高度（195px）扣掉數值標籤、月份文字與間距後的可用高度
            bar_html = '<section class="grad-shell" aria-labelledby="trend-title"><div class="panel glass"><h2 class="panel-title" id="trend-title">月案件趨勢</h2>'
            bar_html += '<div class="bar-chart" role="img" aria-label="近六個月案件趨勢圖">'
            for m in monthly_trend:
                bar_px = max(int(m['cases'] / max_cases * MAX_BAR_HEIGHT), 4)
                bar_html += f"""
<div class="bar-col">
  <span class="bar-value">{m['cases']:,}</span>
  <div class="bar-fill" style="height:{bar_px}px" aria-label="{m['month']} {m['cases']}件"></div>
  <span class="bar-x">{m['month']}</span>
</div>"""
            bar_html += '</div></div></section>'
            ui.html(bar_html, sanitize=False)

            # 右：年齡分布
            age_html = '<section class="grad-shell" aria-labelledby="age-title"><div class="panel glass"><h2 class="panel-title" id="age-title">受害者年齡分布</h2><div class="donut-wrap">'
            for ag in age_groups:
                age_html += f"""
<div class="age-row">
  <span class="age-label">{ag['group']}</span>
  <div class="age-bar-wrap" role="progressbar" aria-valuenow="{ag['pct']}" aria-valuemin="0" aria-valuemax="100">
    <div class="age-bar" style="width:{ag['pct']}%"></div>
  </div>
  <span class="age-pct">{ag['pct']}%</span>
</div>"""
            age_html += "</div></div></section>"
            ui.html(age_html, sanitize=False)

        # ── Row 3: 詐騙類型排行 (1fr) + 地區表格 (2fr) ────────────────────
        with ui.element("div").classes("row-rank-table"):

            # 左：詐騙類型排行
            fraud_html = '<section class="grad-shell" aria-labelledby="fraud-title"><div class="panel glass"><h2 class="panel-title" id="fraud-title">詐騙類型 Top 5</h2>'
            for i, row in enumerate(top_frauds):
                num_cls = "rank-num top" if i < 3 else "rank-num"
                fraud_html += f"""
<div class="rank-row">
  <div class="{num_cls}" aria-label="第{row['rank']}名">{row['rank']}</div>
  <span class="rank-label">{row['type']}</span>
  <span class="rank-count">{row['count']}件</span>
</div>"""
            fraud_html += "</div></section>"
            ui.html(fraud_html, sanitize=False)

            # 右：地區表格
            tbl_html = '<section class="grad-shell" aria-labelledby="region-title"><div class="panel glass"><h2 class="panel-title" id="region-title">縣市案件統計</h2>'
            tbl_html += """
<div class="table-wrap">
<table class="data-table" aria-label="各縣市案件統計">
  <thead>
    <tr>
      <th scope="col">縣市</th>
      <th scope="col">案件數（件）</th>
      <th scope="col">財損金額（萬元）</th>
    </tr>
  </thead>
  <tbody>"""
            for r in region_table:
                tbl_html += f"""
    <tr>
      <td style="font-weight: 500;">{r['region']}</td>
      <td class="td-accent">{r['cases']}</td>
      <td style="font-weight: 500;">{r['loss']}</td>
    </tr>"""
            tbl_html += "</tbody></table></div></div></section>"
            ui.html(tbl_html, sanitize=False)

        # ── Footer ────────────────────────────────────────────────────────
        ui.html("""
<footer class="dash-footer" role="contentinfo">
  <p>© 2026 內政部警政署 165 全民防騙網 ·
     資料來源：刑事警察局 ·
     本頁面資料待接入資料庫後即時更新</p>
</footer>
""", sanitize=False)
