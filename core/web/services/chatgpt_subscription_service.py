"""Safe account commands; credentials and inference stay with their LLM owners."""

from __future__ import annotations

from typing import Any

from config.chatgpt_subscription import build_subscription_provider
from core.llm.chatgpt_subscription import get_chatgpt_subscription_auth

from .runtime_scene_service import record_runtime_scene_event


def _record(action: str, outcome: str) -> None:
    try:
        record_runtime_scene_event("config", "chatgpt_subscription", f"chatgpt_subscription.{action}",
                                   message="ChatGPT subscription account action", outcome=outcome,
                                   fields={"action": action}, lifecycle=True)
    except Exception:  # noqa: BLE001 - never repeat a successful auth command due to logging failure
        # Diagnostic persistence cannot turn a completed login/logout command
        # into a failed action that the caller would repeat.
        return


def subscription_status() -> dict[str, Any]:
    return get_chatgpt_subscription_auth().status()


def start_subscription_login() -> dict[str, Any]:
    result = get_chatgpt_subscription_auth().start_login()
    _record("login_started", "started")
    return result


def cancel_subscription_login(attempt_id: str) -> dict[str, Any]:
    result = get_chatgpt_subscription_auth().cancel_login(attempt_id)
    _record("login_cancelled", "cancelled")
    return result


def disconnect_subscription() -> dict[str, Any]:
    result = get_chatgpt_subscription_auth().logout()
    _record("disconnected", "succeeded" if result.get("revocationConfirmed") else "degraded")
    return result


def subscription_models() -> dict[str, Any]:
    models = get_chatgpt_subscription_auth().list_models()
    # No token, request body, or upstream diagnostic belongs to this response.
    return {"models": models, "provider": build_subscription_provider()}
