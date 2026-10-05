import io
import json
import base64
from typing import List, Optional

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from langchain_core.tools import tool

# 中文字型設定，避免圖表標籤變成方框（依序：Windows、macOS、Linux，找不到的字型會自動略過）
plt.rcParams["font.sans-serif"] = [
    "Microsoft JhengHei", "Microsoft YaHei", "SimHei",
    "PingFang TC", "Heiti TC",
    "Noto Sans CJK TC", "Noto Sans CJK JP", "AR PL UMing TW", "WenQuanYi Zen Hei",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

MAX_DATA_TEXT_CHARS = 20000
MAX_ROWS = 2000
MAX_COLS = 50

STAT_OPERATIONS = {"describe", "mean", "median", "std", "min", "max", "sum", "count", "correlation", "groupby_agg"}
CHART_TYPES = {"bar", "line", "pie", "scatter"}
CHART_NAMES = {"bar": "長條圖", "line": "折線圖", "pie": "圓餅圖", "scatter": "散佈圖"}


def _to_native(value):
    """把 numpy 純量（如 np.int64）轉成 Python 原生型別，避免 json.dumps 把它們序列化成字串。"""
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _parse_tabular_data(data_text: str):
    """盡量寬容解析使用者貼上的資料。回傳 (DataFrame, None) 或 (None, 錯誤訊息字串)。"""
    if not data_text or not data_text.strip():
        return None, "錯誤：未提供資料內容 (data_text 為空)。"

    if len(data_text) > MAX_DATA_TEXT_CHARS:
        return None, f"錯誤：資料長度 {len(data_text)} 字元超過上限 {MAX_DATA_TEXT_CHARS} 字元，請縮減資料量或分批處理。"

    df = None
    text = data_text.strip()

    # ① JSON 陣列，或 SQL 查詢工具回傳的 {"columns": [...], "data": [[...], ...]} 形狀
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            df = pd.DataFrame(parsed)
        elif isinstance(parsed, dict) and "columns" in parsed and "data" in parsed:
            df = pd.DataFrame(parsed["data"], columns=parsed["columns"])
    except (json.JSONDecodeError, ValueError):
        pass

    # ② 逗號分隔 CSV
    if df is None:
        try:
            candidate = pd.read_csv(io.StringIO(text))
            if candidate.shape[1] > 1 or "," in text:
                df = candidate
        except Exception:
            pass

    # ③ Tab 分隔（Excel / Google 表單複製貼上）
    if df is None:
        try:
            candidate = pd.read_csv(io.StringIO(text), sep="\t")
            if candidate.shape[1] > 1:
                df = candidate
        except Exception:
            pass

    if df is None or df.empty:
        return None, (
            "錯誤：無法將提供的內容解析為表格資料。"
            "請確認資料是每列一筆記錄、欄位用逗號或 Tab 分隔，或提供 JSON 陣列（如 [{\"col\":\"value\"}, ...]）後再試一次。"
        )

    if len(df) > MAX_ROWS:
        return None, f"錯誤：資料列數 {len(df)} 超過上限 {MAX_ROWS} 列，請縮減資料量。"
    if len(df.columns) > MAX_COLS:
        return None, f"錯誤：資料欄數 {len(df.columns)} 超過上限 {MAX_COLS} 欄，請縮減資料量。"

    return df, None


@tool
def compute_statistics(
    data_text: str,
    operations: List[str],
    group_by: Optional[str] = None,
    target_column: Optional[str] = None,
) -> str:
    """
    對使用者提供的任意表格資料執行固定、安全的統計運算（不執行任意程式碼）。

    【輸入】
    - data_text: 表格資料，接受 JSON 陣列（如 [{"city":"台北","sales":100}, ...]）、
      逗號分隔 CSV，或從 Excel/Google 表單複製貼上的 Tab 分隔表格。
    - operations: 要執行的統計運算清單，只能是以下值：
      describe（描述性統計）、mean、median、std、min、max、sum、count、
      correlation（需搭配 target_column 為數值欄位、group_by 可略）、
      groupby_agg（需搭配 group_by 與 target_column）。
    - group_by: 分組欄位名稱（groupby_agg 或分組聚合時使用）。
    - target_column: 目標數值欄位名稱（大部分運算需要）。

    【回傳】JSON 字串，包含各運算的結果。
    """
    df, err = _parse_tabular_data(data_text)
    if err:
        return err

    invalid_ops = [op for op in operations if op not in STAT_OPERATIONS]
    if invalid_ops:
        return f"錯誤：不支援的統計操作 {invalid_ops}，僅支援 {sorted(STAT_OPERATIONS)}。"

    results = {}
    for op in operations:
        try:
            if op == "describe":
                results["describe"] = json.loads(df.describe(include="all").to_json(force_ascii=False))
            elif op == "groupby_agg":
                if not group_by or not target_column:
                    results["groupby_agg"] = "錯誤：groupby_agg 需要 group_by 與 target_column。"
                elif group_by not in df.columns or target_column not in df.columns:
                    results["groupby_agg"] = f"錯誤：找不到欄位 {group_by} 或 {target_column}，可用欄位：{list(df.columns)}。"
                else:
                    grouped = df.groupby(group_by)[target_column].agg(["count", "sum", "mean"])
                    results["groupby_agg"] = json.loads(grouped.to_json(force_ascii=False))
            elif op == "correlation":
                numeric_df = df.select_dtypes(include="number")
                if numeric_df.shape[1] < 2:
                    results["correlation"] = "錯誤：資料中數值欄位不足兩欄，無法計算相關係數。"
                else:
                    results["correlation"] = json.loads(numeric_df.corr().to_json(force_ascii=False))
            else:
                if not target_column:
                    results[op] = "錯誤：此運算需要指定 target_column。"
                elif target_column not in df.columns:
                    results[op] = f"錯誤：找不到欄位 {target_column}，可用欄位：{list(df.columns)}。"
                else:
                    series = pd.to_numeric(df[target_column], errors="coerce")
                    if group_by and group_by in df.columns:
                        grouped = series.groupby(df[group_by])
                        results[op] = json.loads(getattr(grouped, op)().to_json(force_ascii=False))
                    else:
                        results[op] = _to_native(getattr(series, op)())
        except Exception as e:
            results[op] = f"錯誤：執行 {op} 時發生例外 - {e}"

    return json.dumps({"row_count": len(df), "columns": list(df.columns), "results": results}, ensure_ascii=False, default=str)


@tool
def generate_chart(
    data_text: str,
    chart_type: str,
    x_column: str,
    y_column: Optional[str] = None,
    title: str = "",
    group_by: Optional[str] = None,
) -> str:
    """
    對使用者提供的任意表格資料產生圖表圖片（不執行任意程式碼，僅支援固定圖表類型）。

    【輸入】
    - data_text: 表格資料，格式同 compute_statistics（JSON 陣列 / CSV / Tab 分隔表格）。
    - chart_type: 只能是 bar（長條圖）、line（折線圖）、pie（圓餅圖）、scatter（散佈圖）之一。
    - x_column: X 軸欄位名稱（pie 圖用作類別欄位）。
    - y_column: Y 軸數值欄位名稱（pie 圖用作數值欄位，bar/line/scatter 皆需要）。
    - title: 圖表標題。
    - group_by: 若提供，會先依此欄位分組加總 y_column 再繪圖（例如依城市加總銷售額）。

    【回傳】JSON 字串 {"summary": "...", "chart_base64": "data:image/png;base64,..."}。
    summary 是給你（LLM）看的簡短確認訊息；chart_base64 是實際圖片資料，會直接顯示給使用者，不需要你重複輸出。
    """
    df, err = _parse_tabular_data(data_text)
    if err:
        return json.dumps({"summary": err, "chart_base64": None}, ensure_ascii=False)

    if chart_type not in CHART_TYPES:
        return json.dumps({"summary": f"錯誤：不支援的圖表類型 {chart_type}，僅支援 {sorted(CHART_TYPES)}。", "chart_base64": None}, ensure_ascii=False)

    if x_column not in df.columns:
        return json.dumps({"summary": f"錯誤：找不到欄位 {x_column}，可用欄位：{list(df.columns)}。", "chart_base64": None}, ensure_ascii=False)
    if chart_type != "pie" and not y_column:
        return json.dumps({"summary": f"錯誤：{chart_type} 圖需要指定 y_column。", "chart_base64": None}, ensure_ascii=False)
    if y_column and y_column not in df.columns:
        return json.dumps({"summary": f"錯誤：找不到欄位 {y_column}，可用欄位：{list(df.columns)}。", "chart_base64": None}, ensure_ascii=False)

    plot_df = df
    if group_by and group_by in df.columns and y_column and y_column in df.columns:
        plot_df = df.groupby(group_by, as_index=False)[y_column].sum()
        x_column = group_by

    fig, ax = plt.subplots(figsize=(8, 5))
    try:
        if chart_type == "bar":
            ax.bar(plot_df[x_column].astype(str), pd.to_numeric(plot_df[y_column], errors="coerce"))
        elif chart_type == "line":
            ax.plot(plot_df[x_column].astype(str), pd.to_numeric(plot_df[y_column], errors="coerce"), marker="o")
        elif chart_type == "scatter":
            y_vals = pd.to_numeric(plot_df[y_column], errors="coerce")
            if y_vals.notna().sum() == 0:
                return json.dumps({"summary": f"錯誤：scatter 圖的 y_column（{y_column}）必須是數值欄位，但轉換後沒有任何有效數字。", "chart_base64": None}, ensure_ascii=False)
            x_vals = pd.to_numeric(plot_df[x_column], errors="coerce")
            if x_vals.notna().sum() > 0:
                ax.scatter(x_vals, y_vals)
            else:
                # x_column 是類別型欄位（例如城市名稱）：以類別位置繪圖，而非硬轉數值產生空圖
                codes, categories = pd.factorize(plot_df[x_column].astype(str))
                ax.scatter(codes, y_vals)
                ax.set_xticks(range(len(categories)))
                ax.set_xticklabels(categories)
        elif chart_type == "pie":
            values_col = y_column if y_column else plot_df.columns[1] if len(plot_df.columns) > 1 else None
            if not values_col:
                return json.dumps({"summary": "錯誤：pie 圖需要 y_column 作為數值欄位。", "chart_base64": None}, ensure_ascii=False)
            ax.pie(pd.to_numeric(plot_df[values_col], errors="coerce"), labels=plot_df[x_column].astype(str), autopct="%1.1f%%")

        ax.set_title(title or f"{chart_type} chart")
        if chart_type != "pie":
            ax.set_xlabel(x_column)
            ax.set_ylabel(y_column or "")
            plt.xticks(rotation=45, ha="right")
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("ascii")
        chart_base64 = f"data:image/png;base64,{b64}"

        summary = f"已生成{chart_type}圖：X={x_column}" + (f"，Y={y_column}" if y_column else "") + f"（{len(plot_df)} 筆資料點）。"
        return json.dumps({"summary": summary, "chart_base64": chart_base64}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"summary": f"錯誤：繪圖時發生例外 - {e}", "chart_base64": None}, ensure_ascii=False)
    finally:
        plt.close(fig)


def parse_tabular_data(data_text: str):
    """供 UI 在送出前檢查資料能否解析。回傳 (DataFrame, None) 或 (None, 錯誤訊息)。"""
    return _parse_tabular_data(data_text)


def run_analysis_request(req: dict) -> list:
    """依「數據分析請求」表單的結構化參數直接執行統計與繪圖（不經 LLM 決定）。

    req: {"data_text", "operations": [...], "charts": [...], "target_column", "group_by"}
    圖表一律以 group_by 為 X 軸、target_column 為 Y 軸；bar / line / pie 依 X 加總 Y。
    回傳 [(工具, 參數, 結果字串), ...]，順序即執行順序。
    """
    data_text = req.get("data_text", "")
    target = req.get("target_column") or None
    group = req.get("group_by") or None
    steps = []

    operations = req.get("operations") or ["describe"]
    args = {"data_text": data_text, "operations": operations,
            "target_column": target, "group_by": group}
    steps.append((compute_statistics, args, compute_statistics.invoke(args)))

    for chart_type in req.get("charts") or []:
        args = {"data_text": data_text, "chart_type": chart_type,
                "x_column": group, "y_column": target,
                "group_by": group if chart_type != "scatter" else None,
                "title": f"{target} 依 {group}（{CHART_NAMES.get(chart_type, chart_type)}）"}
        steps.append((generate_chart, args, generate_chart.invoke(args)))
    return steps

