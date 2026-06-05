"""Lightweight team case orchestration for group conversations."""

from __future__ import annotations

import re
from typing import Any

from core.chat.chat_task_types import trim_lines


CONSULTATION_INTENTS = {"medical_consultation", "maternal_child_consultation_demo"}

_HEALTH_TOPIC_RE = re.compile(
    r"(孩子|儿童|婴儿|宝宝|新生儿|孕|产妇|哭|发热|发烧|咳嗽|疼|痛|呕吐|腹泻|吃奶|睡眠|问诊|症状|疾病|医院|医生)"
)
_DEMO_TOPIC_RE = re.compile(r"(demo|演示|展示|方案|产品|客户|公司|汇报|路演|标书|PPT)", re.IGNORECASE)
_AGE_RE = re.compile(r"(\d+\s*(岁|个月|月龄|天|周)|年龄|月龄|多大|新生儿|婴儿)")
_DURATION_RE = re.compile(r"(多久|几天|持续|小时|晚上|夜间|经常|连续|反复|频率|时长)")
_TEMPERATURE_RE = re.compile(r"(体温|发热|发烧|退烧|低烧|高烧|\d{2}(?:\.\d)?\s*度)")
_SYMPTOM_RE = re.compile(r"(呕吐|腹泻|腹胀|咳嗽|皮疹|抽搐|呼吸|精神|嗜睡|吃奶|拒奶|排便|小便|哭声|疼|痛)")
_HISTORY_RE = re.compile(r"(既往|病史|过敏|用药|疫苗|早产|基础病|就诊|检查)")


def build_team_case_state(
    *,
    room: dict[str, Any],
    topic: str,
    purpose: str,
    participants: list[dict[str, Any]],
    history: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a small per-round case state without changing Team membership."""

    normalized_topic = trim_lines(topic or "", max_lines=6).strip()
    room_config = {**_safe_dict(room.get("config")), **_safe_dict(config)}
    intent = _infer_intent(topic=normalized_topic, purpose=purpose, config=room_config)
    missing_facts = _missing_facts_for_intent(intent, normalized_topic)
    risk_flags = _risk_flags_for_topic(normalized_topic)
    information_sufficiency = _information_sufficiency(intent, missing_facts, risk_flags)
    next_action = _next_action(intent, information_sufficiency, missing_facts, risk_flags)
    user_facing_mode = _user_facing_mode(intent, next_action)
    discussion_visibility = _discussion_visibility(next_action)
    status = {
        "clarify": "waiting_user",
        "discuss": "discussing",
        "synthesize": "synthesizing",
        "answer": "completed",
    }.get(next_action, "discussing")
    assigned_roles = _assigned_roles_for_action(next_action, intent)

    case_state = {
        "schemaVersion": 1,
        "caseId": _case_id(room, history),
        "roomId": str(room.get("roomId") or "").strip(),
        "teamId": str(room_config.get("teamId") or "").strip(),
        "teamTemplateId": str(room_config.get("teamTemplateId") or "").strip(),
        "intent": intent,
        "userGoal": _user_goal(normalized_topic, intent),
        "knownFacts": [normalized_topic] if normalized_topic else [],
        "missingFacts": missing_facts,
        "riskFlags": risk_flags,
        "informationSufficiency": information_sufficiency,
        "nextAction": next_action,
        "userFacingMode": user_facing_mode,
        "discussionVisibility": discussion_visibility,
        "assignedRoles": assigned_roles,
        "status": status,
        "participantsConsidered": len([item for item in participants if item.get("enabled", True)]),
    }
    if intent == "maternal_child_consultation_demo":
        case_state["demoMapping"] = "先完成用户侧问诊信息对齐，再映射到妇幼数字健康产品能力。"
    return case_state


def select_speakers_for_case(
    speakers: list[dict[str, Any]],
    *,
    participants: list[dict[str, Any]],
    case_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Narrow speakers only when the case is waiting for user clarification."""

    if not isinstance(case_state, dict):
        return speakers
    if str(case_state.get("nextAction") or "").strip() != "clarify":
        return speakers
    enabled = [item for item in participants if item.get("enabled", True)]
    for bucket in _ask_user_role_buckets(str(case_state.get("intent") or "")):
        for participant in enabled:
            participant_id = str(participant.get("participantId") or "").strip()
            if not participant_id:
                continue
            if _participant_matches_any(participant, bucket):
                return [participant]
    return speakers[:1]


def format_case_state_prompt(case_state: dict[str, Any] | None) -> str:
    if not isinstance(case_state, dict) or not case_state:
        return ""
    next_action = str(case_state.get("nextAction") or "").strip()
    lines = [
        f"- 用户目标: {case_state.get('userGoal') or '未识别'}",
        f"- 意图: {case_state.get('intent') or 'unknown'}",
        f"- 信息充分性: {case_state.get('informationSufficiency') or 'unknown'}",
        f"- 下一步动作: {next_action or 'delegate'}",
        f"- 用户可见模式: {case_state.get('userFacingMode') or 'team_discussion'}",
    ]
    known = _string_list(case_state.get("knownFacts"))
    missing = _string_list(case_state.get("missingFacts"))
    risks = _string_list(case_state.get("riskFlags"))
    assigned = _string_list(case_state.get("assignedRoles"))
    if known:
        lines.append(f"- 已知信息: {'；'.join(known[:4])}")
    if missing:
        lines.append(f"- 缺失信息: {'；'.join(missing[:6])}")
    if risks:
        lines.append(f"- 风险信号: {'；'.join(risks[:4])}")
    if assigned:
        lines.append(f"- 本轮建议角色: {'；'.join(assigned[:5])}")
    demo_mapping = str(case_state.get("demoMapping") or "").strip()
    if next_action == "clarify" and demo_mapping:
        lines.append("- Demo 映射边界: 本轮不要做产品能力映射、方案包装或平台联动说明；只先把用户问题问清楚。")
    elif demo_mapping:
        lines.append(f"- Demo 映射原则: {demo_mapping}")
    return "\n".join(lines)


def case_prompt_lines(case_state: dict[str, Any] | None) -> list[str]:
    if not isinstance(case_state, dict):
        return []
    next_action = str(case_state.get("nextAction") or "").strip()
    intent = str(case_state.get("intent") or "").strip()
    if next_action == "clarify":
        lines = [
            "- 当前 case 还没有弄清关键条件；本轮目标是像真实问诊接话一样面向用户自然澄清，而不是开会讨论如何澄清。",
            "- 先用一句短话接住用户担心，再自然问 2-3 个最影响判断的问题；不要写成问卷、清单、表格或固定信息采集模板。",
            "- 只问当前最关键的症状线索，不要把年龄、体温、既往史、过敏史、用药史等整套项目一次性铺开。",
            "- 不要把追问写成内部任务分派、岗位待办、会议纪要或“请某角色补充”的话。",
        ]
        if intent in CONSULTATION_INTENTS:
            lines.append("- 涉及健康咨询时必须保留就医/急症边界，不做诊断、处方、剂量或保证性判断。")
        if intent == "maternal_child_consultation_demo":
            lines.append("- clarify 阶段禁止提“智能问诊记录、妇幼数字健康能力、产品能力、方案映射、平台联动、Demo 展示”等产品话术；等信息足够后再进入讨论和映射。")
        return lines
    if next_action == "discuss":
        return [
            "- 当前信息足以进入团队讨论；围绕用户目标给出本岗位的判断、依据、风险和可执行建议。",
            "- 不要把讨论退回成例行问卷；只有发现会改变结论的关键缺口时才补问。",
            "- 内部思考和角色间讨论会在界面默认折叠，所以正文要紧凑、可被主持人合并。",
        ]
    if next_action == "synthesize":
        return [
            "- 当前 case 已有足够团队意见，优先把碎片意见合并成用户可直接使用的结果。",
            "- 输出需要区分用户可读结论、团队依据、风险边界和下一步动作。",
        ]
    return [
        "- 围绕 caseState 推进用户目标，避免只按岗位自说自话。",
        "- 如果发现关键信息缺口会影响结论，请指出缺口并建议下一步，而不是强行给完整答案。",
    ]


def _infer_intent(*, topic: str, purpose: str, config: dict[str, Any]) -> str:
    normalized_purpose = str(purpose or "").strip()
    if normalized_purpose == "medical_triage":
        return "medical_consultation"
    if bool(config.get("heletechMaternalDigitalHealthDemo")) and _HEALTH_TOPIC_RE.search(topic):
        return "maternal_child_consultation_demo"
    if bool(config.get("heletechMaternalDigitalHealthDemo")):
        return "enterprise_demo_solution"
    if normalized_purpose == "research_coordination":
        return "research_coordination"
    if _DEMO_TOPIC_RE.search(topic):
        return "demo_solution"
    return normalized_purpose or "discussion"


def _missing_facts_for_intent(intent: str, topic: str) -> list[str]:
    if intent not in CONSULTATION_INTENTS:
        return []
    checks = [
        ("年龄/月龄", _AGE_RE),
        ("持续时间与频率", _DURATION_RE),
        ("体温或发热情况", _TEMPERATURE_RE),
        ("伴随症状", _SYMPTOM_RE),
        ("既往史/用药/过敏史", _HISTORY_RE),
    ]
    return [label for label, pattern in checks if not pattern.search(topic)]


def _risk_flags_for_topic(topic: str) -> list[str]:
    flags: list[str] = []
    if re.search(r"(呼吸困难|喘不上气|意识|昏迷|抽搐|大出血|紫绀|嘴唇发紫|严重过敏)", topic):
        flags.append("急症红旗")
    if re.search(r"(新生儿|出生|满月内)", topic):
        flags.append("低龄婴儿风险")
    return flags


def _information_sufficiency(intent: str, missing_facts: list[str], risk_flags: list[str]) -> str:
    if risk_flags:
        return "urgent_boundary_needed"
    if intent in CONSULTATION_INTENTS and len(missing_facts) >= 3:
        return "insufficient"
    if intent in CONSULTATION_INTENTS and missing_facts:
        return "partially_sufficient"
    return "sufficient"


def _next_action(
    intent: str,
    information_sufficiency: str,
    missing_facts: list[str],
    risk_flags: list[str],
) -> str:
    if risk_flags:
        return "clarify"
    if intent in CONSULTATION_INTENTS and information_sufficiency == "insufficient":
        return "clarify"
    if intent in CONSULTATION_INTENTS:
        return "discuss"
    return "discuss"


def _user_facing_mode(intent: str, next_action: str) -> str:
    if next_action == "clarify":
        return "direct_clarification"
    if next_action == "synthesize":
        return "final_answer"
    if intent in CONSULTATION_INTENTS:
        return "team_discussion_then_advice"
    return "team_discussion"


def _discussion_visibility(next_action: str) -> str:
    if next_action in {"discuss", "synthesize"}:
        return "collapsed_by_default"
    return "user_visible"


def _assigned_roles_for_action(next_action: str, intent: str) -> list[str]:
    if next_action == "clarify":
        if intent == "maternal_child_consultation_demo":
            return ["主持", "妇幼业务", "合规/安全"]
        return ["主持", "风险分诊", "症状采集"]
    if intent in {"enterprise_demo_solution", "maternal_child_consultation_demo"}:
        return ["主持", "业务", "集成", "数据", "合规"]
    return ["团队相关成员"]


def _ask_user_role_buckets(intent: str) -> list[tuple[str, ...]]:
    if intent == "maternal_child_consultation_demo":
        return [
            ("方案主持", "主持", "host", "moderator"),
            ("妇幼", "业务", "儿童保健", "intake", "symptom"),
            ("合规", "安全", "风险", "分诊", "safety", "risk"),
        ]
    return [
        ("问诊主持", "主持", "host", "moderator"),
        ("风险", "分诊", "红旗", "safety", "risk"),
        ("症状", "采集", "病史", "intake", "symptom", "history"),
    ]


def _participant_matches_any(participant: dict[str, Any], needles: tuple[str, ...]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            participant.get("teamRole"),
            participant.get("teamMemberPurpose"),
            participant.get("title"),
            participant.get("agentCode"),
            participant.get("agentId"),
            participant.get("participantId"),
        )
    ).lower()
    return any(str(needle or "").lower() in haystack for needle in needles)


def _case_id(room: dict[str, Any], history: list[dict[str, Any]]) -> str:
    room_id = str(room.get("roomId") or "room").strip() or "room"
    return f"{room_id}:case-{len([item for item in history if isinstance(item, dict)]) + 1}"


def _user_goal(topic: str, intent: str) -> str:
    if intent in CONSULTATION_INTENTS:
        return "先理解用户健康咨询场景并补齐影响判断的关键信息。"
    if intent in {"enterprise_demo_solution", "demo_solution"}:
        return "围绕用户给定场景形成可展示、可交付、不过度承诺的方案。"
    return trim_lines(topic or "推进当前团队议题。", max_lines=1)


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [trim_lines(str(item or ""), max_lines=1).strip() for item in value if str(item or "").strip()]
