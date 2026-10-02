"""save_public_config 的 [ui] language 保留/override 落盘语义。

整份写路径（config workspace apply、git_status_service、developer_sandbox、
外部脚本 import config）都不该成为 ui.language 漂移的载体：保留模式下磁盘
存量语言赢；只有显式语言写入方（update_language、Launcher 界面语言设置）
通过 ui_language_override 声明改动。所有用例用 tmp_path 隔离配置路径。
"""

import pytest

from config.public_config import load_public_config, save_public_config


def _seed_config(config_path, language: str | None) -> None:
    lines = []
    if language is not None:
        lines += ["[ui]", f'language = "{language}"']
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _disk_language(config_path) -> str | None:
    ui = load_public_config(config_path).get("ui")
    if not isinstance(ui, dict):
        return None
    return ui.get("language")


def test_save_public_config_preserves_stored_ui_language(tmp_path):
    """保留模式：磁盘 zh、payload 带en 整份写 → 磁盘仍 zh，其余字段正常写入。"""

    config_path = tmp_path / "config.toml"
    _seed_config(config_path, "zh")
    payload = {"ui": {"language": "en"}, "workbench": {"window_mode": "windowed"}}

    save_public_config(payload, config_path)

    assert _disk_language(config_path) == "zh"
    assert load_public_config(config_path)["workbench"]["window_mode"] == "windowed"


def test_save_public_config_is_noop_when_payload_language_matches_disk(tmp_path):
    """payload 语言与磁盘一致时保留模式无感（update_intake_mode 等路径）。"""

    config_path = tmp_path / "config.toml"
    _seed_config(config_path, "en")
    payload = {"ui": {"language": "en"}, "workbench": {"window_mode": "windowed"}}

    save_public_config(payload, config_path)

    assert _disk_language(config_path) == "en"
    assert load_public_config(config_path)["workbench"]["window_mode"] == "windowed"


def test_save_public_config_skips_injection_when_disk_has_no_language(tmp_path):
    """首次初始化语义：磁盘无语言值时不注入、不回填，payload 原样通过。

    注：save_public_config 的备份步骤要求目标文件已存在；文件尚不存在时的
    首次初始化由 ensure_global_config_initialized 负责，不经本函数。
    """

    config_path = tmp_path / "config.toml"
    _seed_config(config_path, None)
    save_public_config({"workbench": {"window_mode": "windowed"}}, config_path)
    assert _disk_language(config_path) is None

    # 磁盘无语言值时 payload 自带的语言原样通过：保留层不回填也不改写。
    save_public_config({"ui": {"language": "en"}}, config_path)
    assert _disk_language(config_path) == "en"


def test_save_public_config_override_writes_declared_language(tmp_path):
    """override 模式：显式声明的新语言落盘（大小写归一化到 zh/en）。"""

    config_path = tmp_path / "config.toml"
    _seed_config(config_path, "zh")

    save_public_config({"ui": {"language": "en"}}, config_path, ui_language_override="EN")

    assert _disk_language(config_path) == "en"


def test_save_public_config_override_rejects_invalid_language(tmp_path):
    """override 传非法值：显式语言写入不允许静默丢弃，抛 ValueError 且不落盘。"""

    config_path = tmp_path / "config.toml"
    _seed_config(config_path, "zh")

    with pytest.raises(ValueError, match="Unsupported ui language override"):
        save_public_config({"ui": {"language": "en"}}, config_path, ui_language_override="fr")

    assert _disk_language(config_path) == "zh"
