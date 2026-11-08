"""Fixed, public errors; upstream exception strings never cross this boundary."""

from __future__ import annotations

_MESSAGES = {
    "storage_unavailable": "无法使用系统安全凭据存储。",
    "storage_corrupt": "ChatGPT 凭据无法解密或已损坏，请重新连接。",
    "storage_failed": "无法安全保存 ChatGPT 凭据。",
    "busy": "ChatGPT 连接正在更新，请稍后重试。",
    "network": "无法连接 OpenAI，请检查网络后重试。",
    "timeout": "OpenAI 请求超时，请稍后重试。",
    "rate_limited": "OpenAI 暂时限制了请求，请稍后重试。",
    "upstream_unavailable": "OpenAI 服务暂时不可用。",
    "reauth_required": "ChatGPT 连接已失效，请重新登录。",
    "permission_missing": "尚未授予使用 ChatGPT 订阅的权限，请重新连接并授权。",
    "invalid_response": "OpenAI 返回了无法验证的响应。",
    "invalid_identity": "无法验证 ChatGPT 登录身份，请重新登录。",
    "identity_mismatch": "登录账户与原账户不一致，原连接已保留。",
    "registration_incomplete": "ChatGPT 注册未完成，请重新连接。",
    "login_declined": "ChatGPT 登录未获授权。",
    "login_expired": "ChatGPT 登录已过期，请重新连接。",
    "login_cancelled": "ChatGPT 登录已取消。",
    "callback_unavailable": "无法启动本机登录回调，请稍后重试。",
    "signed_out": "请先连接 ChatGPT。",
}


class ChatGPTSubscriptionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in _MESSAGES else "invalid_response"
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)

    def safe_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}
