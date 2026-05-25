"""Scoring and de-duplication helpers for theme discovery."""

from __future__ import annotations

import re
from typing import Iterable

from .models import CandidateTheme, clamp_score


SCORE_WEIGHTS = {
    "noveltyGap": 0.25,
    "scientificValue": 0.20,
    "technicalDepth": 0.15,
    "interdisciplinaryAuthenticity": 0.15,
    "verifiability": 0.10,
    "competitionFit": 0.10,
    "implementationFeasibility": 0.05,
}

NOVELTY_PATH_PRIORITY = {
    "problem_perspective": 4,
    "method_transfer": 3,
    "discipline_combination": 2,
    "application_scenario": 1,
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "using",
    "ai",
    "llm",
    "research",
    "scientist",
    "theme",
}


def calculate_recommendation_score(scores: dict[str, float]) -> float:
    total = 0.0
    for key, weight in SCORE_WEIGHTS.items():
        total += clamp_score(scores.get(key, 0.0)) * weight
    return round(total, 2)


def rank_themes(themes: Iterable[CandidateTheme]) -> list[CandidateTheme]:
    return sorted(
        themes,
        key=lambda item: (
            item.recommendation_score,
            clamp_score(item.scores.get("noveltyGap")),
            NOVELTY_PATH_PRIORITY.get(item.novelty_path, 0),
            item.title,
        ),
        reverse=True,
    )


def deduplicate_themes(
    themes: Iterable[CandidateTheme],
    *,
    limit: int = 5,
    similarity_threshold: float = 0.62,
) -> list[CandidateTheme]:
    selected: list[CandidateTheme] = []
    for theme in rank_themes(themes):
        if all(theme_similarity(theme, existing) < similarity_threshold for existing in selected):
            selected.append(theme)
        if len(selected) >= limit:
            break
    return selected


def theme_similarity(left: CandidateTheme, right: CandidateTheme) -> float:
    left_tokens = _theme_tokens(left)
    right_tokens = _theme_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    lexical = overlap / union if union else 0.0
    same_path_bonus = 0.15 if left.novelty_path == right.novelty_path else 0.0
    shared_disciplines = set(left.interdisciplinary_combination) & set(right.interdisciplinary_combination)
    discipline_bonus = min(0.15, 0.05 * len(shared_disciplines))
    return min(1.0, lexical + same_path_bonus + discipline_bonus)


def _theme_tokens(theme: CandidateTheme) -> set[str]:
    text = " ".join(
        [
            theme.title,
            theme.one_line,
            theme.core_question,
            " ".join(theme.interdisciplinary_combination),
        ]
    ).lower()
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text)
        if token not in STOPWORDS and len(token) >= 3
    }
