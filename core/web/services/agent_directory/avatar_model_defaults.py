"""Stable default-avatar mapping for configured Agent dialogue models.

The mapping deliberately consumes the configured model identifier instead of a
runtime provider route.  A provider fallback must not make an Agent's identity
or avatar change between turns.
"""

import re

MODEL_AVATAR_GENERIC_FILENAME = "model-generic.svg"
MODEL_AVATAR_FILENAMES = (
    "model-openai.svg",
    "model-anthropic.svg",
    "model-qwen.svg",
    "model-deepseek.svg",
    "model-gemini.svg",
    "model-meta.svg",
    "model-minimax.svg",
    "model-xai.svg",
    "model-xiaomi.svg",
    MODEL_AVATAR_GENERIC_FILENAME,
)


def model_default_avatar_filename(model_id: object) -> str:
    """Return the bundled logo filename for a configured dialogue model.

    Model IDs vary by provider (``relay/gpt-5.6``), deployed local aliases, and
    GGUF filenames.  Matching on normalized model-name tokens keeps the
    default stable while avoiding provider-only guesses such as a generic
    relay route being treated as OpenAI.
    """

    tokens = tuple(
        token
        for token in re.split(r"[^a-z0-9]+", str(model_id or "").strip().lower())
        if token
    )
    if not tokens:
        return MODEL_AVATAR_GENERIC_FILENAME

    if _contains_token(tokens, "deepseek"):
        return "model-deepseek.svg"
    if _contains_token(tokens, "codeqwen") or _contains_token(tokens, "qwen"):
        return "model-qwen.svg"
    if _contains_token(tokens, "claude"):
        return "model-anthropic.svg"
    if _contains_token(tokens, "gemini"):
        return "model-gemini.svg"
    if _contains_token(tokens, "grok"):
        return "model-xai.svg"
    if _contains_token(tokens, "minimax"):
        return "model-minimax.svg"
    if _contains_token(tokens, "mimo"):
        return "model-xiaomi.svg"
    if _contains_token(tokens, "llama") or _contains_token(tokens, "meta"):
        return "model-meta.svg"
    if _contains_token(tokens, "gpt") or _contains_token(tokens, "codex"):
        return "model-openai.svg"
    return MODEL_AVATAR_GENERIC_FILENAME


def _contains_token(tokens: tuple[str, ...], prefix: str) -> bool:
    return any(token == prefix or token.startswith(prefix) for token in tokens)
