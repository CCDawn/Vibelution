"""Helpers for config-driven unit tests that must not read operator config."""

from pathlib import Path

from config import Settings


_MISSING_TEST_CONFIG_PATH = Path(__file__).with_name("__missing_test_config__.toml")


def isolated_settings_config(**kwargs):
    """Build Settings from defaults plus explicit kwargs, without operator TOML."""
    return Settings(str(_MISSING_TEST_CONFIG_PATH), **kwargs).config
