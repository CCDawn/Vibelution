"""Language helpers for the web workbench."""

from __future__ import annotations

from config.public_config import get_public_config_snapshot


DEFAULT_LANGUAGE = "zh"
SUPPORTED_LANGUAGES = {"zh", "en"}


def resolve_language(value: object) -> str:
    text = str(value or DEFAULT_LANGUAGE).strip().lower()
    return text if text in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def get_web_language() -> str:
    # 会话归一化等热路径每请求要取多次语言；走进程内共享快照（一次 stat），
    # 不做 resolve/读盘/深拷贝。写路径与外部改文件都会让快照换新。
    try:
        public_config = get_public_config_snapshot()
    except Exception:
        return DEFAULT_LANGUAGE
    return resolve_language(public_config.get("ui", {}).get("language", DEFAULT_LANGUAGE))


def text_for(lang: str, *, zh: str, en: str) -> str:
    return zh if resolve_language(lang) == "zh" else en
