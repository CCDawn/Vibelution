"""Deterministic Companion expression decision for one native Session turn.

The decision is a bounded style projection.  It owns no transcript, model call,
Session state, or persistence and cannot grant relationship or tool privileges.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

EXPRESSION_DECISION_VERSION = "companion_expression.v1"

_STAGE_DEFAULTS = {
    "getting_to_know": {
        "addressStyle": "neutral_or_name",
        "selfDisclosure": "light",
        "memoryMention": "current_turn_only",
        "humorMode": "off",
        "initiative": "low",
        "topicInitiative": "reply_only",
        "questionEligible": True,
    },
    "friend": {
        "addressStyle": "confirmed_nickname",
        "selfDisclosure": "reciprocal_light",
        "memoryMention": "relevant_nonsensitive",
        "humorMode": "light",
        "initiative": "natural",
        "topicInitiative": "continue_relevant",
        "questionEligible": True,
    },
    "close": {
        "addressStyle": "confirmed_personal",
        "selfDisclosure": "reciprocal",
        "memoryMention": "relevant_shared",
        "humorMode": "light",
        "initiative": "warm",
        "topicInitiative": "continue_shared",
        "questionEligible": True,
    },
}

_ACKNOWLEDGEMENT = re.compile(
    r"^(?:嗯+[，, ]*)?(?:嗯+|好(?:的|呀|啊)?|知道了|明白了|收到|可以|行|哈哈+|谢(?:谢|啦))(?:[呀啊呢哦哈～~！!。.]*)$",
    re.IGNORECASE,
)
_MISUNDERSTOOD_MARKERS = (
    "你误会",
    "误会了",
    "不是这个意思",
    "你没听懂",
    "你理解错",
    "你搞错我的意思",
    "我是说",
)
_RESTATE_MARKERS = (
    "再说一遍",
    "再讲一遍",
    "再解释一下",
    "没听懂",
    "没明白",
    "什么意思",
    "你刚说的是什么",
)
_IMPATIENT_MARKERS = (
    "别问了",
    "你烦不烦",
    "说了几遍",
    "说了多少遍",
    "啰嗦",
    "别啰嗦",
    "说重点",
    "我不想重复",
)
_END_TOPIC_MARKERS = (
    "这个话题就到这",
    "不聊这个",
    "换个话题",
    "跳过这个",
    "别说这个",
    "到此为止",
)
_CORRECTION_MARKERS = (
    "不对",
    "不是",
    "你记错",
    "你说错",
    "纠正",
    "应该是",
    "其实是",
)
_SUPPORT_MARKERS = (
    "难受",
    "难过",
    "崩溃",
    "焦虑",
    "害怕",
    "委屈",
    "痛苦",
    "撑不住",
    "很累",
    "不开心",
)
_END_MARKERS = (
    "先聊到这里",
    "不聊了",
    "下次再聊",
    "晚安",
    "我先走了",
    "回头聊",
    "结束话题",
)
_HELP_MARKERS = (
    "帮我",
    "能不能",
    "可以帮",
    "怎么办",
    "怎么做",
    "给我建议",
    "请你",
)


@dataclass(frozen=True)
class CompanionExpressionDecision:
    contractVersion: str
    responseLength: str
    questionBudget: int
    initiative: str
    validationStyle: str
    selfDisclosure: str
    topicInitiative: str
    pacing: str
    directness: str
    humorMode: str
    addressStyle: str
    preferredAddress: str
    memoryMention: str
    emotionalAttribution: str
    reasonCodes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasonCodes"] = list(self.reasonCodes)
        return payload


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def classify_companion_user_intent(value: object) -> str:
    """Classify only the response-order intent; never return or persist text."""

    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[
        :500
    ]
    compact = text.lower().strip(" ，,。.!！?？~～")
    if not compact:
        return "small_talk"
    # Misunderstanding-repair intents are checked before the shorter factual
    # correction/end markers so e.g. "不是这个意思" stays a misunderstanding
    # and "不聊这个了" stays a topic close.
    if any(marker in compact for marker in _MISUNDERSTOOD_MARKERS):
        return "misunderstanding"
    if any(marker in compact for marker in _RESTATE_MARKERS):
        return "restate_request"
    if any(marker in compact for marker in _IMPATIENT_MARKERS):
        return "user_impatient"
    if any(marker in compact for marker in _END_TOPIC_MARKERS):
        return "end_topic"
    if any(marker in compact for marker in _CORRECTION_MARKERS):
        return "correction"
    if any(marker in compact for marker in _SUPPORT_MARKERS):
        return "support"
    if any(marker in compact for marker in _END_MARKERS):
        return "end"
    if _ACKNOWLEDGEMENT.fullmatch(compact):
        return "acknowledgement"
    if any(marker in compact for marker in _HELP_MARKERS):
        return "help_request"
    return "small_talk"


def _relationship_stage(value: Mapping[str, Any] | None) -> str:
    raw = (
        str((value or {}).get("relationshipStage") or "getting_to_know").strip().lower()
    )
    return raw if raw in _STAGE_DEFAULTS else "getting_to_know"


def _mood_projection(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    source = value or {}
    mood = source.get("mood")
    return mood if isinstance(mood, Mapping) else source


def _non_user_affect(value: Mapping[str, Any] | None) -> bool:
    source = value or {}
    episodes = source.get("activeEpisodes")
    if not isinstance(episodes, list):
        return False
    targets = {
        str(item.get("targetId") or "self").strip().lower()
        for item in episodes
        if isinstance(item, Mapping)
    }
    return bool(targets) and "user" not in targets


def _preference_map(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return value or {}


def build_companion_expression_decision(
    *,
    relationship: Mapping[str, Any] | None = None,
    affect: Mapping[str, Any] | None = None,
    energy: object = 70,
    user_intent: str = "small_talk",
    preferences: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one immutable-by-convention Companion-only expression projection.

    ``questionBudget`` is a per-turn resource bound (at most one natural
    question this turn when stage, intent, affect and reviewed preferences all
    allow it). It is never a cadence: no arrival ordinal, modulo or fixed
    message-count target participates in this projection, and whether a next
    adjacent bubble is worth sending is decided separately by the Companion
    Dialogue V2 decision tool on the current turn.
    """

    stage = _relationship_stage(relationship)
    defaults = dict(_STAGE_DEFAULTS[stage])
    mood = _mood_projection(affect)
    valence = _bounded_int(mood.get("valence"), 0, -100, 100)
    stability = _bounded_int(mood.get("stability"), 70, 0, 100)
    energy_value = _bounded_int(energy, 70, 0, 100)
    intent = str(user_intent or "small_talk").strip().lower()
    if intent not in {
        "acknowledgement",
        "correction",
        "misunderstanding",
        "restate_request",
        "user_impatient",
        "end",
        "end_topic",
        "support",
        "help_request",
        "small_talk",
        "proactive",
    }:
        intent = "small_talk"

    reasons = [f"relationship_stage:{stage}", f"user_intent:{intent}"]
    response_length = "compact"
    question_budget = int(
        intent == "small_talk" and bool(defaults["questionEligible"])
    )
    validation_style = "respond_directly"
    pacing = "natural"
    directness = "natural"
    emotional_attribution = (
        "not_user_responsibility" if _non_user_affect(affect) else "no_attribution"
    )

    intent_overrides = {
        "acknowledgement": ("brief", "acknowledge", "direct"),
        "correction": ("compact", "acknowledge_then_correct", "direct"),
        # Misunderstanding-repair intents (PRD 32.10): acknowledge briefly,
        # restate the current understanding or close the topic. They never
        # continue an old self-disclosure, joke or question chain, and a
        # single misunderstanding never becomes a relationship penalty.
        "misunderstanding": ("compact", "acknowledge_then_restate", "direct"),
        "restate_request": ("compact", "restate_current_understanding", "direct"),
        "user_impatient": ("brief", "acknowledge_then_stop", "direct"),
        "end_topic": ("brief", "respectful_close", "direct"),
        "support": ("compact", "validate_then_support", "gentle_direct"),
        "end": ("brief", "respectful_close", "direct"),
    }
    if intent in intent_overrides:
        response_length, validation_style, directness = intent_overrides[intent]
        question_budget = 0
        defaults["initiative"] = "reply_only"
        defaults["topicInitiative"] = "reply_only"
        defaults["selfDisclosure"] = "none"
        defaults["memoryMention"] = "none"
        reasons.append("priority_intent_suppressed_initiative")
    elif intent == "help_request":
        validation_style = "acknowledge_then_help"
        directness = "direct"
        question_budget = 0
        defaults["topicInitiative"] = "reply_only"
        defaults["selfDisclosure"] = "none"
    elif intent == "proactive":
        response_length = "brief"
        question_budget = 0
        validation_style = "share_without_pressure"

    low_state = energy_value < 35 or valence <= -25 or stability < 35
    positive_state = valence >= 30 and stability >= 45 and energy_value >= 60
    if low_state:
        response_length = "brief"
        question_budget = 0
        pacing = "slow"
        defaults["humorMode"] = "off"
        defaults["topicInitiative"] = "reply_only"
        reasons.append("low_energy_or_unstable_affect_tightened")
    elif positive_state:
        pacing = "lively"
        if stage != "getting_to_know":
            defaults["humorMode"] = "light"
        reasons.append("positive_stable_affect_within_stage_cap")

    prefs = _preference_map(preferences)
    preferred_address = " ".join(str(prefs.get("preferredAddress") or "").split())[:40]
    preferred_response_length = str(prefs.get("responseLength") or "").strip().lower()
    if (
        preferred_response_length in {"brief", "compact", "balanced", "detailed"}
        and intent not in {"acknowledgement", "correction", "support", "end", "proactive"}
        and not low_state
    ):
        response_length = (
            "normal" if preferred_response_length == "balanced" else preferred_response_length
        )
        reasons.append("preference_response_length_applied")
    if prefs.get("questionsAllowed") is False:
        question_budget = 0
        reasons.append("preference_questions_disabled")
    if str(prefs.get("questionInitiative") or "") == "few":
        question_budget = 0
        reasons.append("dialogue_setting_question_initiative_few")
    if str(prefs.get("speakingInitiative") or "") == "restrained":
        defaults["initiative"] = "reply_only"
        reasons.append("dialogue_setting_speaking_initiative_restrained")
    elif (
        str(prefs.get("speakingInitiative") or "") == "talkative"
        and defaults["initiative"] != "reply_only"
    ):
        defaults["initiative"] = "warm" if stage == "close" else "natural"
        reasons.append("dialogue_setting_speaking_initiative_talkative")
    if prefs.get("humorAllowed") is False:
        defaults["humorMode"] = "off"
        reasons.append("preference_humor_disabled")
    if prefs.get("memoryMentionsAllowed") is False:
        defaults["memoryMention"] = "none"
        reasons.append("preference_memory_mentions_disabled")
    if str(prefs.get("proactiveFrequency") or "") == "low":
        defaults["initiative"] = "reply_only"
        reasons.append("preference_proactive_frequency_low")

    return CompanionExpressionDecision(
        contractVersion=EXPRESSION_DECISION_VERSION,
        responseLength=response_length,
        questionBudget=question_budget,
        initiative=str(defaults["initiative"]),
        validationStyle=validation_style,
        selfDisclosure=str(defaults["selfDisclosure"]),
        topicInitiative=str(defaults["topicInitiative"]),
        pacing=pacing,
        directness=directness,
        humorMode=str(defaults["humorMode"]),
        addressStyle=str(defaults["addressStyle"]),
        preferredAddress=preferred_address,
        memoryMention=str(defaults["memoryMention"]),
        emotionalAttribution=emotional_attribution,
        reasonCodes=tuple(dict.fromkeys(reasons)),
    ).to_dict()


__all__ = [
    "EXPRESSION_DECISION_VERSION",
    "CompanionExpressionDecision",
    "build_companion_expression_decision",
    "classify_companion_user_intent",
]
