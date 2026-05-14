"""
飞机智能设计平台 L3 · 认证模块
最简版: 一个团队共享密码 + HMAC 签名的 cookie session
不需要 user 表, 无服务端 session 存储, 重启不丢登录态。

密码读取顺序:
1. 环境变量 L3_PASSWORD
2. 项目根目录 .password 文件
3. 兜底默认: "ce25a"   (上线请务必改掉!)
"""

import hmac
import hashlib
import os
import secrets

import config


# ────────────────────────────────────────────
# 配置读取
# ────────────────────────────────────────────
_PASSWORD_FILE = config.PROJECT_DIR / ".password"
_SECRET_FILE   = config.PROJECT_DIR / ".session_secret"

COOKIE_NAME    = "l3_session"
COOKIE_MAXAGE  = 7 * 86400      # 7 天


def get_password() -> str:
    """读密码: 环境变量 > .password 文件 > 默认 ce25a"""
    env = os.getenv("L3_PASSWORD", "").strip()
    if env:
        return env
    if _PASSWORD_FILE.exists():
        pwd = _PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if pwd:
            return pwd
    return "ce25a"


def get_secret() -> str:
    """会话签名 secret. 首次启动自动生成, 存到 .session_secret"""
    if _SECRET_FILE.exists():
        sec = _SECRET_FILE.read_text(encoding="utf-8").strip()
        if sec:
            return sec
    new = secrets.token_hex(32)
    _SECRET_FILE.write_text(new, encoding="utf-8")
    try:
        os.chmod(_SECRET_FILE, 0o600)
    except Exception:
        pass
    return new


# ────────────────────────────────────────────
# session token
# ────────────────────────────────────────────
def make_session_token() -> str:
    """生成 session token = HMAC-SHA256(secret, password)
    密码改了, 旧 token 自动失效 (因为 hash 不一样)。"""
    pwd    = get_password()
    secret = get_secret()
    return hmac.new(secret.encode(), pwd.encode(), hashlib.sha256).hexdigest()


def check_session(token: str | None) -> bool:
    """检查 cookie 里的 session token 是否有效"""
    if not token:
        return False
    try:
        return hmac.compare_digest(token, make_session_token())
    except Exception:
        return False


def verify_password(pwd: str) -> bool:
    """登录时验证用户输入的密码"""
    if not pwd:
        return False
    correct = get_password()
    return hmac.compare_digest(pwd, correct)


# ────────────────────────────────────────────
# 白名单
# ────────────────────────────────────────────
def is_whitelisted(path: str) -> bool:
    """是否免认证 (登录页本身、健康检查、静态文件)"""
    if path in ("/login", "/api/health"):
        return True
    if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".css", ".js",
                      ".ico", ".svg", ".woff", ".woff2")):
        return True
    return False
