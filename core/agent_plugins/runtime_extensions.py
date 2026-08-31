"""Narrow runtime hooks for trusted first-party Agent plugins.

The ordinary Agent and Session cores depend on this contract, never on a
concrete plugin.  The surface intentionally contains only the hooks already
used by Vibelution; it is not a general third-party plugin platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AgentPluginRuntimeExtension(Protocol):
    plugin_id: str
    source_kind: str

    def build_prompt_segments(
        self,
        agent_id: str,
        *,
        session_id: str = "",
        run_id: str = "",
    ) -> list[dict[str, Any]]: ...

    def filter_tool_names(
        self,
        agent_id: str,
        tool_names: list[str],
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> list[str]: ...

    def blocked_tool_names(self, agent_id: str) -> list[str]: ...

    def prepare_agent_archive(
        self,
        agent_id: str,
        *,
        stage_workspace: bool = False,
    ) -> Any: ...

    def rollback_agent_archive(self, token: Any) -> None: ...

    def commit_agent_purge(self, token: Any) -> None: ...

    def proactive_turn_is_current(
        self,
        *,
        agent_id: str,
        binding_revision: int,
        delivery_token: str,
    ) -> bool: ...

    def cancel_proactive_attempt(
        self,
        *,
        agent_id: str,
        delivery_token: str,
        reason: str,
    ) -> None: ...

    def finalize_proactive_delivery(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def proactive_runtime_metadata(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AgentPluginArchiveToken:
    plugin_id: str
    token: Any


def installed_runtime_extensions() -> tuple[AgentPluginRuntimeExtension, ...]:
    # Lazy import keeps the extension contract independent from web-service
    # construction while preserving a fixed, trusted first-party registry.
    from .virtual_human_life.runtime_extension import (
        VIRTUAL_HUMAN_LIFE_RUNTIME_EXTENSION,
    )

    return (VIRTUAL_HUMAN_LIFE_RUNTIME_EXTENSION,)


def runtime_extension(plugin_id: str) -> AgentPluginRuntimeExtension | None:
    normalized = str(plugin_id or "").strip()
    return next(
        (
            extension
            for extension in installed_runtime_extensions()
            if extension.plugin_id == normalized
        ),
        None,
    )


def proactive_runtime_extension(
    *,
    plugin_id: str,
    source_kind: str,
) -> AgentPluginRuntimeExtension | None:
    extension = runtime_extension(plugin_id)
    if extension is None or extension.source_kind != str(source_kind or "").strip():
        return None
    return extension


def proactive_runtime_extension_for_context(
    context: dict[str, Any],
) -> AgentPluginRuntimeExtension | None:
    if not is_agent_plugin_proactive_turn(context):
        return None
    metadata = (
        context.get("proactive_plugin")
        if isinstance(context.get("proactive_plugin"), dict)
        else {}
    )
    return proactive_runtime_extension(
        plugin_id=str(metadata.get("pluginId") or "").strip(),
        source_kind=str(metadata.get("sourceKind") or "").strip(),
    )


def is_agent_plugin_proactive_turn(context: dict[str, Any]) -> bool:
    return str(context.get("origin") or "").strip() == "proactive_plugin"


def build_agent_plugin_prompt_segments(
    agent_id: str,
    *,
    session_id: str = "",
    run_id: str = "",
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for extension in installed_runtime_extensions():
        segments.extend(
            extension.build_prompt_segments(
                agent_id,
                session_id=session_id,
                run_id=run_id,
            )
        )
    return segments


def filter_agent_plugin_tool_names(
    agent_id: str,
    tool_names: list[str],
    *,
    runtime_context: dict[str, Any] | None = None,
) -> list[str]:
    filtered = list(tool_names)
    for extension in installed_runtime_extensions():
        filtered = extension.filter_tool_names(
            agent_id,
            filtered,
            runtime_context=runtime_context,
        )
    return filtered


def blocked_agent_plugin_tool_names(agent_id: str) -> list[str]:
    blocked: list[str] = []
    for extension in installed_runtime_extensions():
        for tool_name in extension.blocked_tool_names(agent_id):
            if tool_name not in blocked:
                blocked.append(tool_name)
    return blocked


def prepare_agent_plugin_archive(
    agent_id: str,
    *,
    stage_workspace: bool = False,
) -> tuple[AgentPluginArchiveToken, ...]:
    return tuple(
        AgentPluginArchiveToken(
            plugin_id=extension.plugin_id,
            token=extension.prepare_agent_archive(
                agent_id,
                stage_workspace=stage_workspace,
            ),
        )
        for extension in installed_runtime_extensions()
    )


def rollback_agent_plugin_archive(
    tokens: tuple[AgentPluginArchiveToken, ...],
) -> None:
    for receipt in reversed(tokens):
        extension = runtime_extension(receipt.plugin_id)
        if extension is not None:
            extension.rollback_agent_archive(receipt.token)


def commit_agent_plugin_purge(
    tokens: tuple[AgentPluginArchiveToken, ...],
) -> None:
    for receipt in tokens:
        extension = runtime_extension(receipt.plugin_id)
        if extension is not None:
            extension.commit_agent_purge(receipt.token)


def agent_plugin_proactive_turn_is_current(context: dict[str, Any]) -> bool:
    if not is_agent_plugin_proactive_turn(context):
        return True
    extension = proactive_runtime_extension_for_context(context)
    if extension is None:
        return False
    metadata = context.get("proactive_plugin")
    assert isinstance(metadata, dict)
    return extension.proactive_turn_is_current(
        agent_id=str(context.get("agent_id") or "").strip(),
        binding_revision=int(metadata.get("bindingRevision") or 0),
        delivery_token=str(metadata.get("deliveryToken") or "").strip(),
    )


def cancel_agent_plugin_proactive_attempt(
    context: dict[str, Any],
    *,
    reason: str,
) -> None:
    extension = proactive_runtime_extension_for_context(context)
    if extension is None:
        return
    metadata = context.get("proactive_plugin")
    assert isinstance(metadata, dict)
    extension.cancel_proactive_attempt(
        agent_id=str(context.get("agent_id") or "").strip(),
        delivery_token=str(metadata.get("deliveryToken") or "").strip(),
        reason=reason,
    )


def finalize_agent_plugin_proactive_delivery(
    context: dict[str, Any],
) -> dict[str, Any] | None:
    extension = proactive_runtime_extension_for_context(context)
    if extension is None:
        return None
    return extension.finalize_proactive_delivery(context)


def agent_plugin_proactive_runtime_metadata(
    context: dict[str, Any],
) -> dict[str, Any]:
    extension = proactive_runtime_extension_for_context(context)
    if extension is None:
        return {}
    return extension.proactive_runtime_metadata(context)


__all__ = [
    "AgentPluginArchiveToken",
    "AgentPluginRuntimeExtension",
    "agent_plugin_proactive_runtime_metadata",
    "agent_plugin_proactive_turn_is_current",
    "blocked_agent_plugin_tool_names",
    "build_agent_plugin_prompt_segments",
    "cancel_agent_plugin_proactive_attempt",
    "commit_agent_plugin_purge",
    "filter_agent_plugin_tool_names",
    "finalize_agent_plugin_proactive_delivery",
    "installed_runtime_extensions",
    "is_agent_plugin_proactive_turn",
    "prepare_agent_plugin_archive",
    "proactive_runtime_extension",
    "proactive_runtime_extension_for_context",
    "rollback_agent_plugin_archive",
    "runtime_extension",
]
