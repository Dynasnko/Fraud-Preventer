"""錄影 Demo 用：以 Playwright 開一個真的瀏覽器，逐字打進實際頁面欄位。

不修改任何頁面程式，操作方式跟真人一樣（點開表單、打字、選下拉、上傳檔案）。
只負責「填」，不會按送出 / 傳送 / 新增，由錄影的人自己按。

前置：
    pip install playwright
    預設使用電腦上已安裝的 Google Chrome（不需另外下載瀏覽器）；
    改用 --browser chromium 時才需要先執行 python -m playwright install chromium
    先啟動 python main.py（port 8081）

使用：
    python dev_scripts/demo_autofill.py                      # 預設 admin / admin123
    python dev_scripts/demo_autofill.py --user demo --password xxxxxx --delay 25
    python dev_scripts/demo_autofill.py --fast               # 不逐字，直接貼上
    python dev_scripts/demo_autofill.py --browser msedge     # 改用 Edge

啟動後瀏覽器保持開啟，在終端機輸入選單代號即可填入對應內容。
範例內容定義在 dev_scripts/demo_autofill_data.py。
"""
import argparse
import os
import sys
from urllib.parse import urlparse

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_autofill_data as D  # noqa: E402


class Filler:
    def __init__(self, page: Page, base: str, delay: int, fast: bool):
        self.page, self.base, self.delay, self.fast = page, base.rstrip("/"), delay, fast

    # ── 基本動作 ──────────────────────────────────────────────────────────
    def goto(self, path: str, reload: bool = False):
        """已在該頁就不重新載入（避免清掉對話紀錄）；reload=True 強制重載以清空表單。"""
        if reload or urlparse(self.page.url).path != path:
            self.page.goto(self.base + path)
            self.page.wait_for_load_state("networkidle")

    def type_into(self, loc, text: str):
        loc.scroll_into_view_if_needed()
        loc.click()
        loc.fill("")
        if self.fast:
            loc.fill(text)
        else:
            loc.press_sequentially(text, delay=self.delay)

    def choose(self, select_loc, option: str):
        """Quasar q-select：點開後找選項；選項在虛擬捲動清單外時用方向鍵往下捲。"""
        select_loc.scroll_into_view_if_needed()
        select_loc.click()
        opt = self.page.locator(".q-menu .q-item", has_text=option).first
        for _ in range(40):
            if opt.count() and opt.is_visible():
                opt.click()
                return
            self.page.keyboard.press("ArrowDown")
            self.page.wait_for_timeout(40)
        self.page.keyboard.press("Escape")
        print(f"   ⚠️ 找不到選項「{option}」")

    def open_expansion(self, title: str):
        exp = self.page.locator(".q-expansion-item", has_text=title).first
        header = exp.locator(".q-expansion-item__container > .q-item").first
        if "q-expansion-item--expanded" not in (exp.get_attribute("class") or ""):
            header.click()
            self.page.wait_for_timeout(300)
        return exp

    # ── 各項 Demo ─────────────────────────────────────────────────────────
    def login(self, user: str, password: str):
        self.page.goto(self.base + "/login")
        self.page.wait_for_load_state("networkidle")
        if urlparse(self.page.url).path != "/login":
            return  # 已登入
        self.type_into(self.page.get_by_placeholder("請輸入帳號"), user)
        self.type_into(self.page.get_by_placeholder("請輸入密碼"), password)
        self.page.get_by_role("button", name="登入").click()
        self.page.wait_for_url(lambda u: "/login" not in u, timeout=15000)

    def chat(self, text: str):
        self.goto("/assistant")
        self.type_into(self.page.locator("#asst-input"), text)

    def advanced(self, form: dict):
        self.goto("/assistant")
        exp = self.open_expansion(form["title"])
        if form.get("upload"):
            exp.locator("input[type=file]").first.set_input_files(form["upload"])
            exp.get_by_text("已上傳").wait_for(timeout=15000)
        for placeholder, value in form.get("fields", []):
            self.type_into(exp.get_by_placeholder(placeholder, exact=True), value)
        for idx, option in form.get("selects", []):
            self.choose(exp.locator(".q-select").nth(idx), option)
        for idx, value in form.get("chips", []):
            exp.locator(".option-chip-row").nth(idx).locator("button.option-chip", has_text=value).click()
        for label in form.get("option_chips", []):
            chip = exp.locator("button.option-chip", has_text=label).first
            if "selected" not in (chip.get_attribute("class") or ""):
                chip.click()
                self.page.wait_for_timeout(150)

    def worker(self):
        self.goto("/assistant")
        self.page.get_by_role("button", name="+ 新增 Worker").click()
        dlg = self.page.locator(".q-dialog").last
        dlg.get_by_placeholder("例如：旅遊專家").wait_for()
        self.type_into(dlg.get_by_placeholder("例如：旅遊專家"), D.WORKER_NAME)
        self.type_into(dlg.get_by_placeholder("此 Worker 擅長解答關於…"), D.WORKER_DESC)
        dlg.locator("input[type=file]").first.set_input_files(D.worker_files())
        dlg.get_by_text("新增", exact=True).first.wait_for()

    def report(self, rep: dict):
        self.goto("/report", reload=True)  # 清掉上一筆範例殘留的欄位
        for label, option in rep["selects"]:
            self.choose(self.page.locator(".q-select", has_text=label).first, option)
        for placeholder, value in rep["fields"]:
            self.type_into(self.page.get_by_placeholder(placeholder, exact=True), value)


def build_menu():
    items = []
    for i, (label, text) in enumerate(D.CHAT_PROMPTS, 1):
        items.append((f"c{i}", f"對話框：{label}", lambda f, t=text: f.chat(t)))
    for i, form in enumerate(D.ADVANCED, 1):
        items.append((f"a{i}", f"進階問答：{form['title']}", lambda f, x=form: f.advanced(x)))
    items.append(("w", f"新增 Worker：{D.WORKER_NAME}（含 3 份知識文件）", lambda f: f.worker()))
    for i, rep in enumerate(D.REPORTS, 1):
        items.append((f"r{i}", f"案件通報：{rep['title']}", lambda f, x=rep: f.report(x)))
    return items


def main():
    ap = argparse.ArgumentParser(description="Demo 錄影自動填入")
    ap.add_argument("--url", default="http://localhost:8081")
    ap.add_argument("--browser", default="chrome", choices=["chrome", "msedge", "chromium"],
                    help="chrome / msedge 使用電腦上已安裝的瀏覽器；chromium 使用 Playwright 下載的版本")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--delay", type=int, default=30, help="逐字輸入每字間隔（毫秒）")
    ap.add_argument("--fast", action="store_true", help="直接貼上，不逐字輸入")
    ap.add_argument("--run", help="非互動：依序執行這些代號（逗號分隔），跑完即結束，供測試用")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--screenshot-dir", help="--run 模式下，每個步驟後截圖存到此資料夾")
    args = ap.parse_args()

    menu = build_menu()
    by_key = {k: (desc, fn) for k, desc, fn in menu}

    with sync_playwright() as p:
        channel = None if args.browser == "chromium" else args.browser
        browser = p.chromium.launch(channel=channel, headless=args.headless, args=["--start-maximized"])
        ctx = browser.new_context(no_viewport=not args.headless,
                                  viewport={"width": 1600, "height": 1000} if args.headless else None)
        page = ctx.new_page()
        f = Filler(page, args.url, args.delay, args.fast)
        f.login(args.user, args.password)
        f.goto("/assistant")

        def run(key):
            desc, fn = by_key[key]
            print(f"▶ {desc}")
            try:
                fn(f)
                print("   ✅ 已填入（請自行按送出）")
            except PWTimeout as e:
                print(f"   ❌ 逾時：{e}")
            except Exception as e:  # 單一步驟失敗不讓整個腳本結束，錄影可繼續
                print(f"   ❌ {type(e).__name__}: {e}")

        if args.run:
            for key in args.run.split(","):
                run(key.strip())
                if args.screenshot_dir:
                    os.makedirs(args.screenshot_dir, exist_ok=True)
                    page.screenshot(path=os.path.join(args.screenshot_dir, f"{key.strip()}.png"), full_page=True)
            browser.close()
            return

        while True:
            print("\n" + "─" * 60)
            for k, desc, _ in menu:
                print(f"  {k:>3}  {desc}")
            print("    q  結束")
            key = input("輸入代號 > ").strip().lower()
            if key in ("q", "quit", "exit"):
                break
            if key in by_key:
                run(key)
            elif key:
                print("   代號不存在")
        browser.close()


if __name__ == "__main__":
    main()
