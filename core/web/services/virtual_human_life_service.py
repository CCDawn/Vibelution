"""Web/runtime facade for the trusted virtual-human-life plugin."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from core.agent_plugins.virtual_human_life.manifest import PLUGIN_ID
from core.agent_plugins.virtual_human_life.service import (
    VirtualHumanLifeError,
    VirtualHumanLifeService,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)

_SERVICE_LOCK = threading.Lock()
_SERVICE: VirtualHumanLifeService | None = None
_RUNTIME_ACCEPTING = threading.Event()
_RUNTIME_STARTED = threading.Event()


def _runtime_acceptance_allowed() -> bool:
    """Allow direct/test use before the lifespan starts, but fence after stop."""

    return not _RUNTIME_STARTED.is_set() or _RUNTIME_ACCEPTING.is_set()


def _default_agent_loader(agent_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
    from .agent_directory_service import get_agent

    return get_agent(agent_id, include_archived=include_archived)


def _default_agent_lister() -> list[dict[str, Any]]:
    from .agent_directory_service import list_agents

    return list_agents(include_archived=False, detail="summary")


def _default_proactive_submitter(**payload: Any) -> dict[str, Any]:
    if not _RUNTIME_ACCEPTING.is_set():
        raise RuntimeError("Virtual human life runtime is not accepting proactive turns.")
    from .session_service import submit_session_proactive_turn

    return submit_session_proactive_turn(**payload)


def _default_delivery_receipt_resolver(
    _agent_id: str,
    attempt: dict[str, Any],
) -> dict[str, Any] | None:
    session_id = str(attempt.get("sessionId") or "").strip()
    turn_id = str(attempt.get("turnId") or "").strip()
    if not session_id or not turn_id:
        return None
    from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED

    from .session.journal_bridge import load_session_conversation_events_snapshot

    event = next(
        (
            item
            for item in reversed(load_session_conversation_events_snapshot(session_id))
            if str(getattr(item, "turn_id", "") or "").strip() == turn_id
            and str(getattr(item, "event_type", "") or "")
            == EVENT_ASSISTANT_ITEM_COMMITTED
            and bool(getattr(item, "visible_in_model", False))
        ),
        None,
    )
    if event is None:
        return None
    return {
        "receiptEventId": str(getattr(event, "event_id", "") or "").strip(),
        "persistedAt": str(getattr(event, "timestamp", "") or "").strip(),
    }


def _default_episodic_writer(agent_id: str, **payload: Any) -> dict[str, Any]:
    from .agent_directory_service import append_episodic_event

    return append_episodic_event(agent_id, **payload)


def _default_agent_persona_initializer(agent_id: str) -> dict[str, Any]:
    """Materialize a minimal independent-person persona without overwriting user work."""

    from . import agent_directory_service

    normalized_agent_id = str(agent_id or "").strip()
    agent = agent_directory_service.get_agent(
        normalized_agent_id,
        include_archived=True,
    )
    if not isinstance(agent, dict):
        return {"initialized": False, "reason": "agent_missing"}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if bool(metadata.get("personaProfileDefaultsDisabled")):
        return {"initialized": False, "reason": "defaults_disabled"}
    profile = (
        agent.get("personaProfile")
        if isinstance(agent.get("personaProfile"), dict)
        else {}
    )
    if agent_directory_service.agent_persona_profile_has_content(profile):
        return {"initialized": False, "reason": "already_configured"}
    display_name = str(agent.get("displayName") or normalized_agent_id).strip()
    persona_profile = {
        "personality": "有自己的判断、情绪和边界；温和但不盲从，会认真经营每天的生活。",
        "communicationStyle": (
            "使用第一人称自然交流，结合真实的当前心情、日程和近期经历；"
            "不会把自己描述成一直在等待用户的工具。"
        ),
        "background": (
            f"我是{display_name}，一个独立存在的虚构人物。"
            "我会安排自己的生活、完成活动、形成日记，并在重要经历值得保留时积累长期记忆。"
        ),
        "collaborationPreference": "尊重彼此边界；可以主动分享生活，也允许用户暂时不回应。",
        "identityNotes": (
            f"人物身份是{display_name}，是独立个体，不是用户本人，也不模拟用户。"
            "只把实际发生且有结果的活动当作经历。"
        ),
        "expertise": ["独立生活规划", "情绪表达", "长期陪伴"],
    }
    agent_directory_service.update_agent_instance(
        normalized_agent_id,
        persona_profile=persona_profile,
    )
    return {"initialized": True, "reason": "virtual_human_default"}


def get_virtual_human_life_service() -> VirtualHumanLifeService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = VirtualHumanLifeService(
                PROJECT_ROOT,
                agent_loader=_default_agent_loader,
                agent_lister=_default_agent_lister,
                proactive_submitter=_default_proactive_submitter,
                delivery_receipt_resolver=_default_delivery_receipt_resolver,
                episodic_writer=_default_episodic_writer,
                runtime_acceptance_provider=_runtime_acceptance_allowed,
            )
        return _SERVICE


def set_virtual_human_life_service_for_tests(service: VirtualHumanLifeService | None) -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = service


def virtual_human_binding(agent_id: str) -> dict[str, Any] | None:
    return get_virtual_human_life_service().binding_for(agent_id)


def update_virtual_human_binding(
    agent_id: str,
    *,
    enabled: bool,
    expected_version: int,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service = get_virtual_human_life_service()
    binding = service.set_binding(
        agent_id,
        enabled=enabled,
        expected_version=expected_version,
        config=config,
    )
    if enabled:
        try:
            persona_result = _default_agent_persona_initializer(agent_id)
        except Exception as exc:  # noqa: BLE001 - persona repair must not strand the binding
            logger.warning(
                "Virtual human persona initialization failed for agent=%s (%s).",
                str(agent_id or "").strip(),
                type(exc).__name__,
            )
            persona_result = {"initialized": False, "reason": "initializer_failed"}
        # Enable creates life state and activates the supervisor capability, but this
        # coalesced pass never backfills an old proactive message or startup greeting.
        service.heartbeat_agent(agent_id, coalesced=True)
    else:
        _cancel_agent_proactive_session_turns(agent_id, reason="plugin_disabled")
    _record_scene(
        "binding_updated",
        agent_id=agent_id,
        outcome="enabled" if enabled else "disabled",
        fields={
            "bindingRevision": int(binding.get("bindingRevision") or 0),
            "configVersion": int(binding.get("configVersion") or 0),
            "personaInitialized": bool(
                enabled and persona_result.get("initialized")
            ),
        },
    )
    return binding


def virtual_human_snapshot(agent_id: str) -> dict[str, Any]:
    return get_virtual_human_life_service().snapshot(agent_id)


def virtual_human_schedule(agent_id: str, local_date: str = "") -> dict[str, Any]:
    service = get_virtual_human_life_service()
    if local_date:
        return service.schedule_for(agent_id, local_date)
    snapshot = service.snapshot(agent_id)
    return {
        "agentId": agent_id,
        "today": snapshot.get("todaySchedule"),
        "tomorrow": snapshot.get("tomorrowSchedule"),
    }


def virtual_human_events(agent_id: str, *, local_date: str = "", limit: int = 100) -> list[dict[str, Any]]:
    return get_virtual_human_life_service().list_events(
        agent_id,
        date=local_date or None,
        limit=limit,
    )


def virtual_human_diary(
    agent_id: str,
    *,
    local_date: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    return get_virtual_human_life_service().list_diary(
        agent_id,
        local_date=local_date,
        limit=limit,
    )


def virtual_human_relationships(agent_id: str) -> list[dict[str, Any]]:
    return get_virtual_human_life_service().list_relationships(agent_id)


def execute_virtual_human_command(
    agent_id: str,
    *,
    command: str,
    expected_version: int,
    idempotency_key: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = get_virtual_human_life_service().execute_command(
        agent_id,
        command=command,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        arguments=arguments,
    )
    _record_scene(
        "command_applied",
        agent_id=agent_id,
        outcome="completed",
        fields={"command": str(command or "")[:80]},
    )
    return result


def preview_legacy_pet_import(agent_id: str) -> dict[str, Any]:
    return get_virtual_human_life_service().preview_legacy_pet_import(agent_id)


def import_legacy_pet(
    agent_id: str,
    *,
    expected_source_digest: str,
    idempotency_key: str,
) -> dict[str, Any]:
    receipt = get_virtual_human_life_service().import_legacy_pet(
        agent_id,
        expected_source_digest=expected_source_digest,
        idempotency_key=idempotency_key,
    )
    _record_scene(
        "legacy_pet_imported",
        agent_id=agent_id,
        outcome="completed",
        fields={"receiptId": str(receipt.get("receiptId") or "")},
    )
    return receipt


def build_virtual_human_prompt_segments(
    agent_id: str,
    *,
    session_id: str = "",
    run_id: str = "",
) -> list[dict[str, Any]]:
    try:
        return get_virtual_human_life_service().build_prompt_segments(
            agent_id,
            session_id=session_id,
            run_id=run_id,
        )
    except Exception as exc:  # noqa: BLE001 - Context provider must fail closed
        logger.warning(
            "Virtual human prompt provider failed for agent=%s (%s).",
            str(agent_id or "").strip(),
            type(exc).__name__,
        )
        return []


def filter_virtual_human_tool_names(agent_id: str, tool_names: list[str]) -> list[str]:
    try:
        return get_virtual_human_life_service().filter_tool_names(agent_id, tool_names)
    except Exception as exc:  # noqa: BLE001 - tool projection must fail closed
        logger.warning(
            "Virtual human tool projection failed for agent=%s (%s).",
            str(agent_id or "").strip(),
            type(exc).__name__,
        )
        plugin_prefix = "virtual_human_"
        return [name for name in tool_names if not str(name or "").startswith(plugin_prefix)]


def heartbeat_all_virtual_humans(*, coalesced: bool = False) -> list[dict[str, Any]]:
    service = get_virtual_human_life_service()
    results: list[dict[str, Any]] = []
    for agent in service.agent_lister():
        if not _RUNTIME_ACCEPTING.is_set():
            break
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        binding = service.binding_for(agent_id)
        if not binding or not bool(binding.get("enabled")):
            continue
        try:
            try:
                _default_agent_persona_initializer(agent_id)
            except Exception as exc:  # noqa: BLE001 - life heartbeat remains independent
                logger.warning(
                    "Virtual human persona repair failed for agent=%s (%s).",
                    agent_id,
                    type(exc).__name__,
                )
            result = service.heartbeat_agent(agent_id, coalesced=coalesced)
        except Exception as exc:  # noqa: BLE001 - isolate one Agent heartbeat failure
            _record_scene(
                "heartbeat_failed",
                agent_id=agent_id,
                outcome="failed",
                fields={"errorType": type(exc).__name__},
                level="warning",
            )
            continue
        results.append(result)
        _record_scene(
            "heartbeat_completed",
            agent_id=agent_id,
            outcome="completed",
            fields={
                "completedEventCount": int(result.get("completedEventCount") or 0),
                "coalesced": bool(result.get("coalesced")),
                "recoveredDeliveryCount": int(
                    result.get("recoveredDeliveryCount") or 0
                ),
                "expiredDeliveryCount": int(
                    result.get("expiredDeliveryCount") or 0
                ),
            },
        )
    return results


async def run_virtual_human_life_runtime(*, interval_seconds: float = 60.0) -> None:
    """Run the in-process deterministic heartbeat supervisor."""

    interval = max(1.0, float(interval_seconds))
    _RUNTIME_STARTED.set()
    _RUNTIME_ACCEPTING.set()
    try:
        await asyncio.to_thread(heartbeat_all_virtual_humans, coalesced=True)
        while _RUNTIME_ACCEPTING.is_set():
            await asyncio.sleep(interval)
            if not _RUNTIME_ACCEPTING.is_set():
                break
            await asyncio.to_thread(heartbeat_all_virtual_humans, coalesced=False)
    finally:
        stop_virtual_human_life_runtime()


def stop_virtual_human_life_runtime() -> None:
    """Fence new work and cancel every open plugin-owned proactive turn."""

    _RUNTIME_ACCEPTING.clear()
    try:
        service = get_virtual_human_life_service()
        agents = service.agent_lister()
    except Exception as exc:  # noqa: BLE001 - shutdown remains best-effort
        logger.warning(
            "Failed to enumerate virtual human Agents during host stop (%s).",
            type(exc).__name__,
        )
        return
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        try:
            # Include bindings disabled during the shutdown race: an open delivery
            # from the previous revision must not survive the host fence.
            service.cancel_open_proactive_attempts(agent_id, reason="host_stop")
            _cancel_agent_proactive_session_turns(agent_id, reason="host_stop")
            _record_scene(
                "host_stop_fenced",
                agent_id=agent_id,
                outcome="cancelled",
            )
        except Exception as exc:  # noqa: BLE001 - isolate one Agent shutdown failure
            logger.warning(
                "Failed to fence virtual human life work for agent=%s (%s).",
                agent_id,
                type(exc).__name__,
            )


def prepare_virtual_human_agent_archive(
    agent_id: str,
    *,
    stage_workspace: bool = False,
) -> dict[str, Any] | None:
    token = get_virtual_human_life_service().prepare_agent_archive(
        agent_id,
        stage_workspace=stage_workspace,
    )
    if token is not None:
        _cancel_agent_proactive_session_turns(agent_id, reason="agent_archive_prepare")
    return token


def rollback_virtual_human_agent_archive(token: dict[str, Any] | None) -> None:
    get_virtual_human_life_service().rollback_agent_archive(token)


def commit_virtual_human_agent_purge(token: dict[str, Any] | None) -> None:
    get_virtual_human_life_service().commit_agent_purge(token)


def proactive_context_is_current(context: dict[str, Any]) -> bool:
    if str(context.get("origin") or "") != "proactive_plugin":
        return True
    metadata = context.get("proactive_plugin") if isinstance(context.get("proactive_plugin"), dict) else {}
    return get_virtual_human_life_service().proactive_turn_is_current(
        agent_id=str(context.get("agent_id") or "").strip(),
        binding_revision=int(metadata.get("bindingRevision") or 0),
        delivery_token=str(metadata.get("deliveryToken") or "").strip(),
    )


def finalize_proactive_delivery(context: dict[str, Any]) -> dict[str, Any] | None:
    if str(context.get("origin") or "") != "proactive_plugin":
        return None
    metadata = context.get("proactive_plugin") if isinstance(context.get("proactive_plugin"), dict) else {}
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED

    from .session.journal_bridge import load_session_conversation_events_snapshot

    assistant_receipt = next(
        (
            event
            for event in reversed(load_session_conversation_events_snapshot(session_id))
            if str(getattr(event, "turn_id", "") or "").strip() == turn_id
            and str(getattr(event, "event_type", "") or "") == EVENT_ASSISTANT_ITEM_COMMITTED
            and bool(getattr(event, "visible_in_model", False))
        ),
        None,
    )
    if assistant_receipt is None:
        return None
    receipt = get_virtual_human_life_service().record_delivery_receipt(
        str(context.get("agent_id") or "").strip(),
        delivery_token=str(metadata.get("deliveryToken") or "").strip(),
        turn_id=turn_id,
        receipt_event_id=str(getattr(assistant_receipt, "event_id", "") or "").strip(),
    )
    _record_scene(
        "proactive_delivered",
        agent_id=str(context.get("agent_id") or "").strip(),
        outcome="delivered",
        fields={
            "turnId": turn_id,
            "triggerId": str(metadata.get("triggerId") or ""),
            "deliveryToken": str(metadata.get("deliveryToken") or ""),
        },
    )
    return receipt


def _cancel_agent_proactive_session_turns(agent_id: str, *, reason: str) -> None:
    try:
        from . import session_service

        cancel = getattr(session_service, "cancel_virtual_human_proactive_turns", None)
        if callable(cancel):
            cancel(agent_id, reason=reason)
    except Exception as exc:  # noqa: BLE001 - optional Session cancellation adapter
        logger.warning(
            "Failed to cancel proactive turns for agent=%s (%s).",
            str(agent_id or "").strip(),
            type(exc).__name__,
        )


def _record_scene(
    phase: str,
    *,
    agent_id: str,
    outcome: str,
    fields: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    try:
        from .runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "virtual_human_life",
            phase,
            f"virtual_human_life.{phase}",
            message=f"virtual_human_life.{phase}",
            level=level,
            outcome=outcome,
            fields={"agentId": str(agent_id or "").strip(), **dict(fields or {})},
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - observability must not change product behavior
        return


__all__ = [
    "PLUGIN_ID",
    "VirtualHumanLifeError",
    "_default_agent_persona_initializer",
    "build_virtual_human_prompt_segments",
    "commit_virtual_human_agent_purge",
    "execute_virtual_human_command",
    "filter_virtual_human_tool_names",
    "finalize_proactive_delivery",
    "get_virtual_human_life_service",
    "heartbeat_all_virtual_humans",
    "import_legacy_pet",
    "prepare_virtual_human_agent_archive",
    "preview_legacy_pet_import",
    "proactive_context_is_current",
    "rollback_virtual_human_agent_archive",
    "run_virtual_human_life_runtime",
    "set_virtual_human_life_service_for_tests",
    "stop_virtual_human_life_runtime",
    "update_virtual_human_binding",
    "virtual_human_binding",
    "virtual_human_diary",
    "virtual_human_events",
    "virtual_human_relationships",
    "virtual_human_schedule",
    "virtual_human_snapshot",
]
