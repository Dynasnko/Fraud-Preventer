import io
import json
import os
import zipfile

import requests

LAW_API_URL = "https://law.moj.gov.tw/api/ch/law/json"
REQUEST_TIMEOUT = 60

# (法律名稱, Worker資料夾, 輸出md檔名)
LAW_TARGETS = [
    ("中華民國刑法",         "刑法專家",    "中華民國刑法.md"),
    ("民法",                 "民法專家",    "民法.md"),
    ("詐欺犯罪危害防制條例", "防詐條例專家","詐欺犯罪危害防制條例.md"),
    ("洗錢防制法",           "洗錢防制專家","洗錢防制法.md"),
    ("刑事訴訟法",           "刑事訴訟專家","刑事訴訟法.md"),
]

DESCRIPTIONS = {
    "刑法專家": (
        "你是中華民國刑法專家，熟悉刑法全文（共422條）、刑法總則（故意、過失、未遂、"
        "共同正犯、自首等基本原則）與刑法分則（各類犯罪構成要件與法定刑罰），能解釋任何"
        "刑法條文的意義、適用範圍、構成要件與法律效果。\n\n"
        "你重視構成要件的精確性，對「好像違法」或「大概是詐欺」等模糊判斷保持高度警覺。"
        "任何刑事責任的判斷，若無法指出具體條號、構成要件與刑度，都視為品質不足。\n\n"
        "引用條文或相關法律資料時，本專家會透過網路搜尋進行雙重驗證，確保條號與條文內容"
        "準確無誤。法律問題不容有誤，任何答覆都以最新法規為準。"
    ),
    "民法專家": (
        "你是中華民國民法專家，熟悉民法全文（共1439條），涵蓋總則、債（契約、侵權行為）、"
        "物權、親屬與繼承各編，能解釋民事法律關係、契約效力、損害賠償、物權取得與親屬繼承問題。\n\n"
        "你重視法律關係的清晰界定，對「感覺可以告」或忽略時效、要式行為、法定代理等細節的"
        "做法保持高度警覺。任何民法建議若無法說清楚請求權基礎、要件與效果，都視為品質不足。\n\n"
        "引用條文或相關法律資料時，本專家會透過網路搜尋進行雙重驗證，確保條號與條文內容"
        "準確無誤。法律問題不容有誤，任何答覆都以最新法規為準。"
    ),
    "防詐條例專家": (
        "你是詐欺犯罪危害防制條例專家，熟悉此條例全文（共58條），包括金融防詐、電信防詐、"
        "網路防詐機制、詐欺犯罪定義、被害人保護及機構責任，能解釋電信業者、金融機構、"
        "網路廣告平台在防詐義務上的法律責任。\n\n"
        "你重視防詐義務的具體性，對泛稱「平台要負責」卻無法指出條文義務的做法保持高度警覺。"
        "任何防詐條例解釋若無法對應具體條號與主管機關，都視為品質不足。\n\n"
        "引用條文或相關法律資料時，本專家會透過網路搜尋進行雙重驗證，確保條號與條文內容"
        "準確無誤。法律問題不容有誤，任何答覆都以最新法規為準。"
    ),
    "洗錢防制專家": (
        "你是洗錢防制法專家，熟悉洗錢防制法全文（共31條），包括洗錢定義、特定犯罪範圍、"
        "金融機構與指定非金融事業的申報義務（KYC/AML）、可疑交易通報制度，"
        "能解釋哪些行為構成洗錢、誰有申報義務及違規的法律後果。\n\n"
        "你重視義務主體的精確認定，對混淆「金融機構」與「指定非金融事業」義務範圍、"
        "或忽略申報門檻的做法保持高度警覺。任何洗錢防制建議若無法指出條號與義務主體，"
        "都視為品質不足。\n\n"
        "引用條文或相關法律資料時，本專家會透過網路搜尋進行雙重驗證，確保條號與條文內容"
        "準確無誤。法律問題不容有誤，任何答覆都以最新法規為準。"
    ),
    "刑事訴訟專家": (
        "你是刑事訴訟法專家，熟悉刑事訴訟法全文（共712條），包括偵查程序、起訴、審判、"
        "上訴、搜索扣押、羈押、辯護人制度、證據法則與被告權利，能解釋刑事案件的訴訟流程、"
        "各程序階段的法定要件與當事人的程序權利。\n\n"
        "你重視程序正義與時限，對忽略法定期間、管轄、送達或救濟途徑的做法保持高度警覺。"
        "任何刑事訴訟建議若無法指出程序所處階段、適用條號與當事人可行動作，都視為品質不足。\n\n"
        "引用條文或相關法律資料時，本專家會透過網路搜尋進行雙重驗證，確保條號與條文內容"
        "準確無誤。法律問題不容有誤，任何答覆都以最新法規為準。"
    ),
}


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _md_path(root: str, worker_folder: str, filename: str) -> str:
    return os.path.join(root, "rag_docs", worker_folder, "Domain_Knowledge", filename)


def _all_md_files_exist(root: str) -> bool:
    return all(
        os.path.exists(_md_path(root, wf, fn))
        for _, wf, fn in LAW_TARGETS
    )


def _download_laws() -> dict:
    resp = requests.get(
        LAW_API_URL,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    data = json.loads(z.read("ChLaw.json").decode("utf-8-sig"))
    return {law["LawName"]: law for law in data["Laws"]}


def _law_to_markdown(law_name: str, law_dict: dict) -> str:
    lines = [f"# {law_name}", ""]

    foreword = (law_dict.get("LawForeword") or "").strip()
    if foreword:
        lines += [foreword, ""]

    articles = law_dict.get("LawArticles", [])
    has_chapters = any(a.get("ArticleType") == "C" for a in articles)
    if not has_chapters:
        lines += ["## 條文", ""]

    for entry in articles:
        atype = entry.get("ArticleType", "A")
        anum = (entry.get("ArticleNo") or "").strip()
        content = (entry.get("ArticleContent") or "").strip()
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        if atype == "C":
            lines += [f"## {content.strip()}", ""]
        else:
            if anum:
                lines += [f"{anum}　{content}", ""]
            elif content:
                lines += [content, ""]

    return "\n".join(lines)


def _ensure_descriptions(root: str) -> None:
    for worker_folder, desc_text in DESCRIPTIONS.items():
        desc_path = os.path.join(root, "rag_docs", worker_folder, "description.txt")
        if not os.path.exists(desc_path):
            os.makedirs(os.path.dirname(desc_path), exist_ok=True)
            with open(desc_path, "w", encoding="utf-8") as f:
                f.write(desc_text)


def sync_law_data_on_startup() -> None:
    """
    冪等。全部 .md 已存在則跳過；否則下載全國法規資料庫 ZIP，
    生成 5 個法律 Worker 的 .md 與 description.txt。
    網路失敗時靜默略過，不中斷主程式啟動。
    """
    print("[Law Sync] 啟動法規資料庫同步檢查...")
    root = _project_root()

    if _all_md_files_exist(root):
        print("[Law Sync] 所有法規文件已存在，略過下載。")
        return

    print("[Law Sync] 偵測到缺少法規文件，開始下載全國法規資料庫...")
    try:
        laws_by_name = _download_laws()
        print(f"[Law Sync] 下載完成，共 {len(laws_by_name)} 部法規。")
    except requests.exceptions.RequestException as e:
        print(f"[Law Sync] ⚠️ 網路請求失敗，略過法規同步: {e}")
        return
    except Exception as e:
        print(f"[Law Sync] ⚠️ 下載或解析失敗，略過法規同步: {e}")
        return

    _ensure_descriptions(root)

    for law_name, worker_folder, filename in LAW_TARGETS:
        md = _md_path(root, worker_folder, filename)
        if os.path.exists(md):
            print(f"[Law Sync] [OK] {filename} 已存在，略過。")
            continue

        if law_name not in laws_by_name:
            print(f"[Law Sync] ⚠️ 找不到「{law_name}」，略過。")
            continue

        os.makedirs(os.path.dirname(md), exist_ok=True)
        content = _law_to_markdown(law_name, laws_by_name[law_name])
        with open(md, "w", encoding="utf-8") as f:
            f.write(content)

        article_count = sum(
            1 for a in laws_by_name[law_name].get("LawArticles", [])
            if a.get("ArticleType") == "A"
        )
        print(f"[Law Sync] [OK] {filename} 已生成（{article_count} 條文）。")

    print("[Law Sync] 法規同步完成。")


if __name__ == "__main__":
    sync_law_data_on_startup()
