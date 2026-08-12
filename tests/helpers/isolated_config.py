"""Helpers for config-driven unit tests that must not read operator config."""

from pathlib import Path

from config import Settings


_MISSING_TEST_CONFIG_PATH = Path(__file__).with_name("__missing_test_config__.toml")


def isolated_settings_config(**kwargs):
    """Build Settings from defaults plus explicit kwargs, without operator TOML.

    Schema-less kwargs that carry v1-shaped llm providers/profiles keep the
    v1 schema semantics these LLM client/protocol tests were written against
    (schema v2 rejects adding providers/credentials from incremental input).
    """
    normalized = dict(kwargs)
    has_llm_schema = any(
        key.startswith("llm.schema_version") or key.startswith("llm__schema_version")
        for key in normalized
    )
    has_v1_llm_shape = any(
        key.startswith("llm.providers.") or key.startswith("llm.profiles.")
        or key.startswith("llm__providers") or key.startswith("llm__profiles")
        for key in normalized
    )
    if not has_llm_schema and has_v1_llm_shape:
        normalized.setdefault("llm.schema_version", 1)
    return Settings(str(_MISSING_TEST_CONFIG_PATH), **normalized).config
