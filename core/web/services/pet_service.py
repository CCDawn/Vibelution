"""Pet space summary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.public_config import load_public_config
from core.pet_system.pet_system import get_pet_system

from .i18n import get_web_language, text_for
from .runtime_scene_service import record_runtime_scene_event


class PetActionError(ValueError):
    """Raised when a pet action is not supported."""


@dataclass(frozen=True)
class PetActionDefinition:
    action: str
    hunger_delta: int = 0
    energy_delta: int = 0
    health_delta: int = 0
    love_delta: int = 0
    mood_delta: int = 0
    exp_delta: int = 0
    interaction_delta: int = 0
    task_type: str = ""


PET_ACTIONS = {
    "feed": PetActionDefinition(
        action="feed",
        hunger_delta=20,
        love_delta=3,
        mood_delta=4,
        exp_delta=1,
        task_type="pet_feed",
    ),
    "talk": PetActionDefinition(
        action="talk",
        energy_delta=-4,
        love_delta=8,
        mood_delta=6,
        exp_delta=1,
        interaction_delta=1,
        task_type="pet_talk",
    ),
    "care": PetActionDefinition(
        action="care",
        energy_delta=8,
        health_delta=12,
        love_delta=4,
        mood_delta=3,
        exp_delta=1,
        task_type="pet_care",
    ),
}


def get_pet_summary() -> dict:
    """Return a condensed summary for the pet space page."""

    public_config = load_public_config()
    lang = get_web_language()
    avatar_preset = public_config.get("avatar", {}).get("preset", "lobster")

    pet = get_pet_system()
    attributes = pet.data.attributes
    hunger = pet.data.hunger
    social = pet.data.social
    dream = pet.data.dream
    heart = pet.data.heart

    return {
        "name": attributes.name,
        "avatarPreset": avatar_preset,
        "level": attributes.level,
        "exp": attributes.exp,
        "expToNext": attributes.exp_to_next,
        "mood": attributes.mood,
        "hunger": attributes.hunger,
        "energy": attributes.energy,
        "health": attributes.health,
        "love": attributes.love,
        "totalTasks": attributes.total_tasks,
        "achievements": attributes.achievements[:6],
        "heartActive": heart.is_active,
        "inDream": dream.in_dream,
        "friendCount": len(social.friends),
        "dailyTokens": hunger.daily_tokens,
        "totalTokens": hunger.total_tokens,
        "statusLine": _build_status_line(lang, attributes.mood, attributes.hunger, dream.in_dream),
    }


def apply_pet_action(action: str) -> dict:
    """Apply one manual pet interaction and return the latest summary."""

    action_key = _normalize_pet_action(action)
    definition = PET_ACTIONS.get(action_key)
    if definition is None:
        _record_pet_action_scene_event(
            "action",
            "pet.action.rejected",
            message=f"Unsupported pet action: {action_key or '<empty>'}",
            level="warning",
            outcome="rejected",
            fields={"action": action_key, "reason": "unsupported_action"},
        )
        raise PetActionError(f"Unsupported pet action: {action_key or '<empty>'}")

    lang = get_web_language()
    pet = get_pet_system()
    attributes = pet.data.attributes
    before = _pet_action_snapshot(pet)

    attributes.hunger = _clamp_percent(attributes.hunger + definition.hunger_delta)
    attributes.energy = _clamp_percent(attributes.energy + definition.energy_delta)
    attributes.health = _clamp_percent(attributes.health + definition.health_delta)
    attributes.love = _clamp_percent(attributes.love + definition.love_delta)
    attributes.mood = _clamp_percent(attributes.mood + definition.mood_delta)
    pet.data.health.overall = attributes.health
    if definition.interaction_delta:
        pet.data.social.total_interactions += definition.interaction_delta
    if definition.exp_delta:
        pet.add_exp(definition.exp_delta)
    pet.save()

    after = _pet_action_snapshot(pet)
    _record_pet_action_scene_event(
        "action",
        "pet.action.applied",
        message=f"Pet action applied: {definition.action}",
        outcome="success",
        fields={
            "action": definition.action,
            "before": before,
            "after": after,
            "deltas": {
                "hunger": definition.hunger_delta,
                "energy": definition.energy_delta,
                "health": definition.health_delta,
                "love": definition.love_delta,
                "mood": definition.mood_delta,
                "exp": definition.exp_delta,
                "interactions": definition.interaction_delta,
            },
        },
    )

    return {
        "action": definition.action,
        "message": _pet_action_message(lang, definition.action),
        "summary": get_pet_summary(),
    }


def _normalize_pet_action(action: str) -> str:
    return str(action or "").strip().lower().replace("-", "_")


def _clamp_percent(value: int) -> int:
    return max(0, min(100, int(value or 0)))


def _pet_action_snapshot(pet: Any) -> dict[str, int]:
    attributes = pet.data.attributes
    return {
        "mood": int(attributes.mood),
        "hunger": int(attributes.hunger),
        "energy": int(attributes.energy),
        "health": int(attributes.health),
        "love": int(attributes.love),
        "exp": int(attributes.exp),
        "level": int(attributes.level),
        "totalInteractions": int(pet.data.social.total_interactions),
    }


def _pet_action_message(lang: str, action: str) -> str:
    if action == "feed":
        return text_for(lang, zh="已喂食，宠物补充了燃料。", en="Fed. The companion has refueled.")
    if action == "talk":
        return text_for(lang, zh="已沟通，亲密度提升了。", en="Talked. Bond has improved.")
    if action == "care":
        return text_for(lang, zh="已照看，状态恢复了一些。", en="Cared. The companion recovered a little.")
    return text_for(lang, zh="互动已完成。", en="Interaction complete.")


def _record_pet_action_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "pet",
            phase,
            event_code,
            message=message or event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
        )
    except Exception:
        return


def _build_status_line(lang: str, mood: int, hunger: int, in_dream: bool) -> str:
    if in_dream:
        return text_for(lang, zh="正安静待在梦境循环里", en="resting inside a dream cycle")
    if hunger < 30:
        return text_for(lang, zh="有点想补充燃料了", en="asking for a little more fuel")
    if mood > 80:
        return text_for(lang, zh="状态明亮、稳定，而且很在场", en="bright, steady, and very present")
    if mood > 50:
        return text_for(lang, zh="情绪平稳，正在安静观察", en="calm and tracking the room")
    return text_for(lang, zh="状态有点低，但还在认真守着", en="a little low, but still keeping watch")
