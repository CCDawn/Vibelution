"""Manifest constants for the virtual-human-life plugin."""

from __future__ import annotations

from typing import Any

from .prompt_pack import PROMPT_PACK_FILES

PLUGIN_ID = "virtual-human-life"
TOOL_BUNDLE_ID = "virtual_human_life"
PROMPT_PACK_ID = "virtual_human_life_v1"
PLUGIN_VERSION = "1.2.0"
STORAGE_SCHEMA_VERSION = 1

VIRTUAL_HUMAN_TOOL_NAMES = (
    "virtual_human_status_tool",
    "virtual_human_schedule_tool",
    "virtual_human_activity_tool",
    "virtual_human_diary_tool",
    "virtual_human_relationship_tool",
    "virtual_human_reflection_tool",
    "virtual_human_proactive_message_tool",
    "virtual_human_dialogue_decision_v2_tool",
)


def manifest_projection() -> dict[str, Any]:
    return {
        "pluginId": PLUGIN_ID,
        "displayName": "虚拟人生活",
        "description": "让一个 Agent 作为独立虚构人物拥有自己的日程、心情、活动与受控主动消息。",
        "version": PLUGIN_VERSION,
        "minimumHostVersion": 1,
        "storageSchemaVersion": STORAGE_SCHEMA_VERSION,
        "trustedFirstParty": True,
        "capabilities": [
            "life.state",
            "life.schedule",
            "life.activity",
            "life.mood",
            "life.diary",
            "life.proactive_message",
            "life.drives",
            "life.affect_afterglow",
            "life.relationship_ledger",
            "life.open_loops",
            "life.nightly_reflection",
            "life.memory_reinforcement",
            "life.environment_facts",
            "life.location_continuity",
            "life.long_term_calendar",
            "life.rhythms",
            "life.interests",
            "life.world_model",
            "life.social_circle",
            "life.local_feed",
            "life.expression_policy",
            "life.optional_embodiment",
            "life.reflection_review_queue",
        ],
        "hooks": [
            "onHostStart",
            "onHostStop",
            "onEnable",
            "onDisable",
            "onAgentArchive",
            "onAgentPurgePrepare",
            "onAgentPurgeCommit",
            "onAgentPurgeRollback",
            "onHeartbeat",
            "beforeTurnContext",
            "afterActivityOutcome",
        ],
        "toolBundleId": TOOL_BUNDLE_ID,
        "promptPackId": PROMPT_PACK_ID,
        "promptPackFiles": list(PROMPT_PACK_FILES),
        "toolNames": list(VIRTUAL_HUMAN_TOOL_NAMES),
    }
