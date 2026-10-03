"""模型条目迁移器（scripts/migrate_model_entries.py）测试。

覆盖三类条目形态与 apply 安全语义：
- tool_chat 错层（interaction_contract 已有值 / 缺失两种）；
- 正常 deepseek_reasoning 协议条目（保持不动）；
- 自造协议名 qwen_openai_compat（族表已收编，保持不动）；
- dry-run 不写盘、apply 备份 + 写后校验、post-apply gate 失败回滚。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "migrate_model_entries.py"


def _load_migrator():
    spec = importlib.util.spec_from_file_location("migrate_model_entries_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


FIXTURE_TOML = """
[llm]
schema_version = 2

[llm.providers.relay_a]
label = "Relay A"
service_class = "relay"
vendor = "multi_model"
driver = "openai"
base_url = "https://relay.example/v1"
auth_kind = "api_key"
credential_ref = "env:VIBELUTION_LLM_TEST_RELAY_A_API_KEY"
requires_credential = true

[llm.providers.relay_a.protocols]
default = "chat_completions"
allowed = ["chat_completions"]

[llm.providers.relay_a.models."misfiled-tool"]
upstream_id = "misfiled-tool"
label = "Misfiled Tool Chat"
model_protocol = "tool_chat"
interaction_contract = "tool_chat"

[llm.providers.relay_a.models."misfiled-no-ic"]
upstream_id = "misfiled-no-ic"
label = "Misfiled Without Contract"
model_protocol = "tool_chat"

[llm.providers.relay_a.models."deepseek-v4"]
upstream_id = "deepseek-v4"
label = "DeepSeek V4"
model_protocol = "deepseek_reasoning"
reasoning_state_field = "reasoning_content"

[llm.providers.relay_a.models."qwen-compat"]
upstream_id = "qwen-compat"
label = "Qwen Compat"
model_protocol = "qwen_openai_compat"

[llm.providers.relay_a.models."image-model"]
upstream_id = "image-model"
label = "Image Model"
interaction_contract = "tool_chat"

[llm.providers.relay_a.models."image-model".defaults]
tool_calling_mode = "disabled"

[llm.profiles.primary]
model_ref = "relay_a/misfiled-tool"
""".strip() + "\n"


@pytest.fixture()
def migrator():
    return _load_migrator()


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(FIXTURE_TOML, encoding="utf-8")
    return path


def _run(migrator, *argv: str) -> tuple[int, dict]:
    import contextlib
    import io

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = migrator.main(list(argv))
    payload = {}
    out = stdout.getvalue().strip()
    if out.startswith("{"):
        payload = json.loads(out)
    return code, payload


def _plan_for(payload: dict, model_key: str) -> dict:
    matches = [item for item in payload["plan"] if item["modelKey"] == model_key]
    assert len(matches) == 1
    return matches[0]


def test_dry_run_plans_misfiled_entries_without_mutating_file(migrator, config_path: Path) -> None:
    original_bytes = config_path.read_bytes()

    code, payload = _run(migrator, "--dry-run", "--config", str(config_path), "--json")

    assert code == 0
    assert payload["mode"] == "dry-run"
    assert payload["schemaVersion"] == 2
    assert payload["totalEntries"] == 5
    assert payload["planCount"] == 2
    assert payload["valid"] is True
    assert config_path.read_bytes() == original_bytes

    with_ic = _plan_for(payload, "misfiled-tool")
    assert with_ic["changes"] == [
        {"field": "model_protocol", "before": "tool_chat", "after": ""}
    ]
    # 错层条目在迁移前应带 interaction-contract-in-model_protocol 错误。
    assert with_ic["issuesBefore"]["errors"]
    assert with_ic["issuesAfter"]["errors"] == []

    without_ic = _plan_for(payload, "misfiled-no-ic")
    assert without_ic["changes"] == [
        {"field": "interaction_contract", "before": "", "after": "tool_chat"},
        {"field": "model_protocol", "before": "tool_chat", "after": ""},
    ]
    assert without_ic["issuesAfter"]["errors"] == []

    skipped_keys = {item["modelKey"]: item["reason"] for item in payload["skipped"]}
    assert set(skipped_keys) == {"deepseek-v4", "qwen-compat", "image-model"}
    assert "deepseek_reasoning" in skipped_keys["deepseek-v4"]
    assert "qwen_openai_compat" in skipped_keys["qwen-compat"]

    # 迁移范围外的既有 doctor 错误（合同与 tool_calling_mode 矛盾）不阻断计划，
    # 只如实上报为 persistent findings。
    persistent = payload["persistentDoctorErrorFindings"]
    assert [item["modelRef"] for item in persistent] == ["relay_a/image-model"]


def test_default_mode_is_dry_run(migrator, config_path: Path) -> None:
    original_bytes = config_path.read_bytes()

    code, payload = _run(migrator, "--config", str(config_path), "--json")

    assert code == 0
    assert payload["mode"] == "dry-run"
    assert payload["planCount"] == 2
    assert config_path.read_bytes() == original_bytes


def test_apply_migrates_and_creates_backup(migrator, config_path: Path) -> None:
    original_bytes = config_path.read_bytes()

    code, payload = _run(migrator, "--apply", "--config", str(config_path), "--json")

    assert code == 0
    assert payload["applied"] is True
    assert payload["valid"] is True
    backup_path = Path(payload["backupPath"])
    assert backup_path.is_file()
    assert backup_path.read_bytes() == original_bytes
    assert backup_path.name.startswith("config.toml.bak-")

    import tomllib

    migrated = tomllib.loads(config_path.read_text(encoding="utf-8"))
    models = migrated["llm"]["providers"]["relay_a"]["models"]
    assert models["misfiled-tool"]["model_protocol"] == ""
    assert models["misfiled-tool"]["interaction_contract"] == "tool_chat"
    assert models["misfiled-no-ic"]["model_protocol"] == ""
    assert models["misfiled-no-ic"]["interaction_contract"] == "tool_chat"
    # 非目标条目逐字节不动：deepseek_reasoning 与自造协议名都保留。
    assert models["deepseek-v4"]["model_protocol"] == "deepseek_reasoning"
    assert models["deepseek-v4"]["reasoning_state_field"] == "reasoning_content"
    assert models["qwen-compat"]["model_protocol"] == "qwen_openai_compat"
    # 越权错误条目（image-model）逐字段不动。
    assert models["image-model"]["interaction_contract"] == "tool_chat"
    assert models["image-model"]["defaults"]["tool_calling_mode"] == "disabled"

    for item in payload["plan"]:
        assert item["issuesAfter"]["errors"] == []
    assert [
        item["modelRef"] for item in payload["persistentDoctorErrorFindings"]
    ] == ["relay_a/image-model"]

    # 迁移后再次 dry-run：无计划可迁。
    code, second = _run(migrator, "--dry-run", "--config", str(config_path), "--json")
    assert code == 0
    assert second["planCount"] == 0


def test_apply_rolls_back_to_original_bytes_when_post_gate_fails(
    migrator, config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_bytes = config_path.read_bytes()

    def _boom(config_path: Path, plan: list, baseline_findings: list | None) -> dict:
        raise RuntimeError("boom: post gate failure")

    monkeypatch.setattr(migrator, "_post_apply_gate", _boom)

    import contextlib
    import io

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        code = migrator.main(["--apply", "--config", str(config_path)])

    assert code == 1
    assert "已回滚" in stderr.getvalue()
    # 配置恢复到写前字节；备份仍保留供人工检查。
    assert config_path.read_bytes() == original_bytes
    backups = list(config_path.parent.glob("config.toml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original_bytes
    assert not list(config_path.parent.glob("*.tmp"))


def test_apply_is_noop_when_nothing_to_migrate(migrator, tmp_path: Path) -> None:
    import tomllib

    path = tmp_path / "config.toml"
    # 用已迁移形态的配置（无错层条目）验证 apply 空转。
    migrated_shape = tomllib.loads(FIXTURE_TOML)
    models = migrated_shape["llm"]["providers"]["relay_a"]["models"]
    models["misfiled-tool"]["model_protocol"] = ""
    models["misfiled-no-ic"]["model_protocol"] = ""
    models["misfiled-no-ic"]["interaction_contract"] = "tool_chat"

    import config.toml_writer as toml_writer

    path.write_text(toml_writer.dumps_public_config(migrated_shape), encoding="utf-8")
    before = path.read_bytes()

    code, payload = _run(migrator, "--apply", "--config", str(path), "--json")

    assert code == 0
    assert payload["noop"] is True
    assert payload["applied"] is False
    assert payload["persistentDoctorErrorFindings"] == [
        {"modelRef": "relay_a/image-model", "errors": payload["persistentDoctorErrorFindings"][0]["errors"]}
    ]
    assert path.read_bytes() == before
