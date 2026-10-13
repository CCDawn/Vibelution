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

    def tool_execution_denial(
        self, runtime: dict[str, Any], tool_name: str
    ) -> str | None:
        from .native_wakeup import execution_denial

        return execution_denial(runtime, tool_name)

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
        try:
            resolved = self._facade().resolve_virtual_human_runtime_target(agent_id)
        except (ValueError, RuntimeError):
            return False
        service = self._facade().get_virtual_human_life_service()
        if resolved.get("selfWake"):
            from .self_continuity import SESSION_PATH

            owner_id = str(resolved["targetAgentId"])
            attempt = service.proactive_attempt(owner_id, delivery_token) or {}
            reference = service.store.read_json(owner_id, SESSION_PATH) or {}
            if attempt.get("deliveryKind") != "self_wake" or attempt.get(
                "sessionId"
            ) != reference.get("sessionId"):
                return False
        return bool(
            service.proactive_turn_is_current(
                agent_id=str(resolved["targetAgentId"]),
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
        service = self._facade().get_virtual_human_life_service()
        # Cancellation remains available after disable/stop fences the owner.
        if not service.binding_for(agent_id):
            from .native_wakeup import resolve_worker

            agent_id = resolve_worker(agent_id, require_enabled=False)
        service.cancel_proactive_attempt(
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
        if trigger.get("deliveryKind") == "self_wake":
            wake = (
                trigger.get("selfWake")
                if isinstance(trigger.get("selfWake"), dict)
                else {}
            )
            return {
                "virtualHumanLife": {
                    "kind": "self_wake",
                    "wakeId": str(wake.get("wakeId") or "")[:160],
                    "requiredToolNames": [
                        str(name).strip()[:160]
                        for name in wake.get("requiredToolNames", [])
                    ][:8],
                }
            }
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
