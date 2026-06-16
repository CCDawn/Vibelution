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


def test_promptsref_top5_backgrounds_are_registered_as_bundled_theme_backgrounds():
    expected = [
        (
            "default-promptsref-candid-lifestyle.png",
            "PromptsRef 生活随拍",
            "PromptsRef Candid Lifestyle",
        ),
        (
            "default-promptsref-mirror-cosplay.png",
            "PromptsRef 镜像角色",
            "PromptsRef Mirror Characters",
        ),
        (
            "default-promptsref-sunlit-street.png",
            "PromptsRef 阳光街拍",
            "PromptsRef Sunlit Street",
        ),
        (
            "default-promptsref-negative-film-street.png",
            "PromptsRef 胶片街巷",
            "PromptsRef Negative Film Street",
        ),
        (
            "default-promptsref-tokyo-shadow-snap.png",
            "PromptsRef 东京光影",
            "PromptsRef Tokyo Shadow Snap",
        ),
    ]

    for filename, zh_label, en_label in expected:
        assert_bundled_background_registered(filename, zh_label=zh_label, en_label=en_label)
        assert_bundled_background_file_resolves(filename)
