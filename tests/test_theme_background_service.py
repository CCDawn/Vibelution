from pathlib import Path

from core.web.services import theme_background_service


def test_sunlit_wink_is_registered_as_bundled_theme_background():
    expected_value = "theme_backgrounds/default-sunlit-wink.png"

    zh_options = theme_background_service.list_default_theme_background_options("zh-CN")
    en_options = theme_background_service.list_default_theme_background_options("en-US")

    assert {"value": expected_value, "label": "阳光眨眼"} in zh_options
    assert {"value": expected_value, "label": "Sunlit Wink"} in en_options
    assert "default-sunlit-wink.png" in theme_background_service.DEFAULT_THEME_BACKGROUND_FILENAMES


def test_sunlit_wink_bundled_theme_background_file_resolves():
    resolved = theme_background_service.resolve_theme_background_file("default-sunlit-wink.png")

    assert resolved == theme_background_service.BUNDLED_THEME_BACKGROUND_DIR / "default-sunlit-wink.png"
    assert Path(resolved).is_file()
