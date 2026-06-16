from pathlib import Path

from core.web.services import theme_background_service


def assert_bundled_background_registered(filename: str, *, zh_label: str, en_label: str) -> None:
    expected_value = f"theme_backgrounds/{filename}"
    zh_options = theme_background_service.list_default_theme_background_options("zh-CN")
    en_options = theme_background_service.list_default_theme_background_options("en-US")

    assert {"value": expected_value, "label": zh_label} in zh_options
    assert {"value": expected_value, "label": en_label} in en_options
    assert filename in theme_background_service.DEFAULT_THEME_BACKGROUND_FILENAMES


def assert_bundled_background_file_resolves(filename: str) -> None:
    resolved = theme_background_service.resolve_theme_background_file(filename)

    assert resolved == theme_background_service.BUNDLED_THEME_BACKGROUND_DIR / filename
    assert Path(resolved).is_file()


def test_sunlit_wink_is_registered_as_bundled_theme_background():
    assert_bundled_background_registered(
        "default-sunlit-wink.png",
        zh_label="阳光眨眼",
        en_label="Sunlit Wink",
    )


def test_sunlit_wink_bundled_theme_background_file_resolves():
    assert_bundled_background_file_resolves("default-sunlit-wink.png")


def test_nika_luffy_poster_is_registered_as_bundled_theme_background():
    assert_bundled_background_registered(
        "default-nika-luffy-poster.png",
        zh_label="尼卡海报",
        en_label="Nika Poster",
    )


def test_nika_luffy_poster_bundled_theme_background_file_resolves():
    assert_bundled_background_file_resolves("default-nika-luffy-poster.png")
