"""Runtime-extension adapter owned by the virtual-human-life plugin."""

from __future__ import annotations

from typing import Any

from .manifest import PLUGIN_ID, VIRTUAL_HUMAN_TOOL_NAMES


class VirtualHumanLifeRuntimeExtension:
    plugin_id = PLUGIN_ID
    source_kind = PLUGIN_ID

    @staticmethod
    def _facade():
        from core.web.services import virtual_human_life_service

        return virtual_human_life_service

    def build_prompt_segments(
        self,
        agent_id: str,
        *,
        session_id: str = "",
        run_id: str = "",
    ) -> list[dict[str, Any]]:
        return self._facade().build_virtual_human_prompt_segments(
            agent_id,
            session_id=session_id,
            run_id=run_id,
        )

    def filter_tool_names(
        self,
        agent_id: str,
        tool_names: list[str],
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> list[str]:
        return self._facade().filter_virtual_human_tool_names(
            agent_id,
            tool_names,
            runtime_context=runtime_context,
        )

    def blocked_tool_names(self, agent_id: str) -> list[str]:
        try:
            binding = self._facade().virtual_human_binding(agent_id)
        except Exception:  # noqa: BLE001 - binding visibility remains deny-first
            binding = None
        if binding and bool(binding.get("enabled")):
            return []
        return list(VIRTUAL_HUMAN_TOOL_NAMES)

    def prepare_agent_archive(
        self,
        agent_id: str,
        *,
        stage_workspace: bool = False,
    ) -> Any:
        return self._facade().prepare_virtual_human_agent_archive(
            agent_id,
            stage_workspace=stage_workspace,
        )

    def rollback_agent_archive(self, token: Any) -> None:
        self._facade().rollback_virtual_human_agent_archive(token)

    def commit_agent_purge(self, token: Any) -> None:
        self._facade().commit_virtual_human_agent_purge(token)

    def proactive_turn_is_current(
        self,
        *,
        agent_id: str,
        binding_revision: int,
        delivery_token: str,
    ) -> bool:
        return bool(
            self._facade().get_virtual_human_life_service().proactive_turn_is_current(
                agent_id=agent_id,
                binding_revision=binding_revision,
                delivery_token=delivery_token,
            )
        )

    def cancel_proactive_attempt(
        self,
        *,
        agent_id: str,
        delivery_token: str,
        reason: str,
    ) -> None:
        self._facade().get_virtual_human_life_service().cancel_proactive_attempt(
            agent_id,
            delivery_token,
            reason=reason,
        )

    def finalize_proactive_delivery(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._facade().finalize_proactive_delivery(context)

    def proactive_runtime_metadata(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        plugin_metadata = (
            context.get("proactive_plugin")
            if isinstance(context.get("proactive_plugin"), dict)
            else {}
        )
        trigger = (
            plugin_metadata.get("trigger")
            if isinstance(plugin_metadata.get("trigger"), dict)
            else {}
        )
        tool_activity = (
            trigger.get("toolActivity")
            if isinstance(trigger.get("toolActivity"), dict)
            else {}
        )
        if not tool_activity:
            return {}
        return {
            "virtualHumanLife": {
                "kind": "tool_activity",
                "activityId": str(tool_activity.get("activityId") or "").strip(),
                "requiredToolNames": [
                    str(name or "").strip()
                    for name in list(tool_activity.get("requiredToolNames") or [])
                    if str(name or "").strip()
                ][:8],
            }
        }


VIRTUAL_HUMAN_LIFE_RUNTIME_EXTENSION = VirtualHumanLifeRuntimeExtension()


__all__ = [
    "VIRTUAL_HUMAN_LIFE_RUNTIME_EXTENSION",
    "VirtualHumanLifeRuntimeExtension",
]
