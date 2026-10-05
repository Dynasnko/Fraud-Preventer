"""
NiceGUI 認證中介邏輯
利用 app.storage.user 管理登入 session
"""
from functools import wraps
from nicegui import app, ui


def get_current_user() -> dict | None:
    """從 session 取得當前登入的使用者資料，未登入回傳 None"""
    return app.storage.user.get("auth_user", None)


def is_logged_in() -> bool:
    return get_current_user() is not None


def is_admin() -> bool:
    user = get_current_user()
    return user is not None and user.get("role") == "admin"


def login_user(user_dict: dict):
    """將使用者資料寫入 session（移除密碼 hash）"""
    safe = {k: v for k, v in user_dict.items() if k != "password_hash"}
    app.storage.user["auth_user"] = safe


def logout_user():
    """清除登入 session"""
    app.storage.user.pop("auth_user", None)


def require_login(page_func):
    """裝飾器：未登入則導向 /login"""
    @wraps(page_func)
    async def wrapper(*args, **kwargs):
        if not is_logged_in():
            ui.navigate.to("/login")
            return
        return await page_func(*args, **kwargs)
    return wrapper


def require_admin(page_func):
    """裝飾器：非 admin 則導向 /dashboard"""
    @wraps(page_func)
    async def wrapper(*args, **kwargs):
        if not is_logged_in():
            ui.navigate.to("/login")
            return
        if not is_admin():
            ui.navigate.to("/dashboard")
            return
        return await page_func(*args, **kwargs)
    return wrapper
