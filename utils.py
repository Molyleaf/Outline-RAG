# utils.py
# 包含登录校验、获取当前用户、文件类型检查等通用辅助函数
from flask import session, abort, current_app

import config


def require_login():
    """
    校验用户是否登录且会话是否为当前应用实例所创建。
    如果 boot_id 不匹配，说明应用已重启，强制用户重新登录。
    """
    if "user" not in session or session.get("boot_id") != current_app.config.get("BOOT_ID"):
        session.clear()
        abort(401)

def current_user():
    """获取当前登录的用户信息。"""
    return session.get("user")

def allowed_file(filename):
    """检查文件名后缀是否在允许列表中。"""
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in config.ALLOWED_FILE_EXTENSIONS
