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


def test_promptsref_wallpaper_top5_backgrounds_are_registered_as_bundled_theme_backgrounds():
    expected = [
        (
            "default-wallpaper-football-editorial.png",
            "壁纸 足球海报",
            "Wallpaper Football Editorial",
        ),
        (
            "default-wallpaper-storm-manga-warrior.png",
            "壁纸 风暴漫画",
            "Wallpaper Storm Manga",
        ),
        (
            "default-wallpaper-neon-hunter-stage.png",
            "壁纸 霓虹猎手",
            "Wallpaper Neon Hunter",
        ),
        (
            "default-wallpaper-golden-stadium.png",
            "壁纸 金色球场",
            "Wallpaper Golden Stadium",
        ),
        (
            "default-wallpaper-neon-casino-lounge.png",
            "壁纸 霓虹赌场",
            "Wallpaper Neon Casino",
        ),
    ]

    for filename, zh_label, en_label in expected:
        assert_bundled_background_registered(filename, zh_label=zh_label, en_label=en_label)
        assert_bundled_background_file_resolves(filename)


def test_prompt_trend_wallpapers_are_registered_as_bundled_theme_backgrounds(monkeypatch, tmp_path):
    monkeypatch.setattr(theme_background_service, "CONFIG_PATH", tmp_path / "config.toml")
    expected = [
        (
            "prompt-trend-wallpaper-01-mountain-observatory.png",
            "提示词趋势 高山观测站",
            "Prompt Trend Mountain Observatory",
        ),
        (
            "prompt-trend-wallpaper-02-memory-atrium.png",
            "提示词趋势 记忆中庭",
            "Prompt Trend Memory Atrium",
        ),
        (
            "prompt-trend-wallpaper-03-pixel-skyline.png",
            "提示词趋势 像素天际线",
            "Prompt Trend Pixel Skyline",
        ),
        (
            "prompt-trend-wallpaper-04-floating-archive-islands.png",
            "提示词趋势 漂浮档案群岛",
            "Prompt Trend Floating Archive Islands",
        ),
        (
            "prompt-trend-wallpaper-05-eco-cyber-city.png",
            "提示词趋势 生态赛博城市",
            "Prompt Trend Eco Cyber City",
        ),
    ]

    for filename, zh_label, en_label in expected:
        assert_bundled_background_registered(filename, zh_label=zh_label, en_label=en_label)
        assert_bundled_background_file_resolves(filename)
