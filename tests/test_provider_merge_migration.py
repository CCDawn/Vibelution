from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from config.provider_merge_migration import (
    ProviderMergeConflictError,
    ProviderMergeVerificationError,
    apply_provider_merge,
    preview_provider_merge,
    rollback_provider_merge,
)
from core.llm.provider_discovery.types import (
    DiscoveredProviderModel,
    ProviderDiscoveryResult,
)


def _config_text(*, duplicate_url: str = "https://relay.example/v1") -> str:
    return f'''# keep operator note
[llm]
schema_version = 2

[llm.providers.ai-pixel]
label = "Ai-Pixel"
service_class = "relay"
vendor = "multi_model"
driver = "openai"
base_url = "https://relay.example/v1"
auth_kind = "api_key"
credential_ref = "env:VIBELUTION_LLM_PROVIDER_AI_PIXEL_API_KEY"
requires_credential = true

[llm.providers.ai-pixel.protocols]
default = "responses"
allowed = ["responses", "chat_completions"]

[llm.providers.ai-pixel.discovery]
mode = "auto"
adapter = "openai_compatible"
cache_ttl_seconds = 300

[llm.providers.ai-pixel.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
label = "Luna"
enabled = true

[llm.providers.ai-pixel_ad214f09]
label = "Ai-Pixel duplicate"
service_class = "relay"
vendor = "multi_model"
driver = "openai"
base_url = "{duplicate_url}"
auth_kind = "api_key"
credential_ref = "env:VIBELUTION_LLM_PROVIDER_AI_PIXEL_DUPLICATE_API_KEY"
requires_credential = true

[llm.providers.ai-pixel_ad214f09.protocols]
default = "responses"
allowed = ["responses", "chat_completions"]

[llm.providers.ai-pixel_ad214f09.discovery]
mode = "auto"
adapter = "openai_compatible"
cache_ttl_seconds = 300

[llm.providers.ai-pixel_ad214f09.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
label = "Luna duplicate"
enabled = true

[llm.providers.ai-pixel_ad214f09.models."gpt-5.6-sol"]
upstream_id = "gpt-5.6-sol"
label = "Sol"
enabled = true

[llm.providers.ai-pixel_ad214f09.models."gpt-5.6-terra"]
upstream_id = "gpt-5.6-terra"
label = "Terra"
enabled = true

[llm.profiles.primary]
model_ref = "ai-pixel_ad214f09/gpt-5.6-luna"
'''


def _fixture(tmp_path: Path, *, duplicate_url: str = "https://relay.example/v1") -> tuple[Path, Path, Path]:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_config_text(duplicate_url=duplicate_url), encoding="utf-8")
    agent_path = tmp_path / "workspace" / "agents" / "agents.json"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "agentId": "agent-1",
                        "llmBindings": {
                            "dialogue": {
                                "modelId": "ai-pixel_ad214f09/gpt-5.6-luna"
                            }
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path, tmp_path, agent_path


def _discovery() -> ProviderDiscoveryResult:
    return ProviderDiscoveryResult(
        provider_id="ai-pixel",
        adapter_id="openai_compatible",
        attempted_endpoints=("https://relay.example/v1/models",),
        discovered_at=datetime.now(timezone.utc).isoformat(),
        models=tuple(
            DiscoveredProviderModel(upstream_id=name, label=name)
            for name in ("gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra")
        ),
    )


def test_preview_maps_duplicate_models_and_keeps_history_read_only(tmp_path: Path) -> None:
    config_path, project_root, _ = _fixture(tmp_path)

    preview = preview_provider_merge(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=["ai-pixel_ad214f09"],
        credential_decisions={"ai-pixel_ad214f09": "use_canonical"},
        config_path=config_path,
        project_root=project_root,
    )

    assert preview.status == "READY"
    assert preview.model_ref_map["ai-pixel_ad214f09/gpt-5.6-luna"] == (
        "ai-pixel/gpt-5.6-luna"
    )
    assert {item["modelKey"] for item in preview.models_to_add} == {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
    }
    assert preview.required_probe_model_ref == "ai-pixel/gpt-5.6-luna"
    assert all("pinnedModel" not in item for item in preview.to_dict()["modelsToAdd"])
    assert "# keep operator note" in config_path.read_text(encoding="utf-8")


def test_preview_rejects_endpoint_equivalence_guess(tmp_path: Path) -> None:
    config_path, project_root, _ = _fixture(
        tmp_path, duplicate_url="https://relay.example"
    )

    preview = preview_provider_merge(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=["ai-pixel_ad214f09"],
        credential_decisions={"ai-pixel_ad214f09": "use_canonical"},
        config_path=config_path,
        project_root=project_root,
    )

    assert preview.status == "NEEDS_REVIEW"
    assert preview.conflicts[0]["code"] == "provider_contract_mismatch"


def test_merge_rewrites_live_refs_preserves_comments_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path, project_root, agent_path = _fixture(tmp_path)
    before_config = config_path.read_bytes()
    before_agent = agent_path.read_bytes()
    monkeypatch.setattr(
        "config.provider_merge_migration.discover_provider_models",
        lambda *_args, **_kwargs: _discovery(),
    )
    monkeypatch.setattr(
        "config.provider_merge_migration.run_draft_llm_test",
        lambda *_args, **_kwargs: {"ok": True, "status": 200},
    )
    monkeypatch.setattr(
        "config.operator_config_transaction.reload_config",
        lambda *_args, **_kwargs: object(),
    )
    preview = preview_provider_merge(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=["ai-pixel_ad214f09"],
        credential_decisions={"ai-pixel_ad214f09": "use_canonical"},
        config_path=config_path,
        project_root=project_root,
    )

    applied = apply_provider_merge(
        preview.preview_id,
        expected_base_hash=preview.base_hash,
        confirmed=True,
        config_path=config_path,
        project_root=project_root,
    )

    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert "# keep operator note" in config_path.read_text(encoding="utf-8")
    assert "ai-pixel_ad214f09" not in parsed["llm"]["providers"]
    assert parsed["llm"]["profiles"]["primary"]["model_ref"] == (
        "ai-pixel/gpt-5.6-luna"
    )
    agent = json.loads(agent_path.read_text(encoding="utf-8"))["agents"][0]
    assert agent["llmBindings"]["dialogue"]["modelId"] == (
        "ai-pixel/gpt-5.6-luna"
    )

    rolled_back = rollback_provider_merge(
        applied["migrationId"],
        expected_current_hash=applied["hash"],
        config_path=config_path,
        project_root=project_root,
    )

    assert rolled_back["status"] == "rolled_back"
    assert config_path.read_bytes() == before_config
    assert agent_path.read_bytes() == before_agent


def test_failed_probe_leaves_config_and_references_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path, project_root, agent_path = _fixture(tmp_path)
    before_config = config_path.read_bytes()
    before_agent = agent_path.read_bytes()
    monkeypatch.setattr(
        "config.provider_merge_migration.discover_provider_models",
        lambda *_args, **_kwargs: _discovery(),
    )
    monkeypatch.setattr(
        "config.provider_merge_migration.run_draft_llm_test",
        lambda *_args, **_kwargs: {"ok": False, "status": 503},
    )
    preview = preview_provider_merge(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=["ai-pixel_ad214f09"],
        credential_decisions={"ai-pixel_ad214f09": "use_canonical"},
        config_path=config_path,
        project_root=project_root,
    )

    with pytest.raises(ProviderMergeVerificationError, match="status=503"):
        apply_provider_merge(
            preview.preview_id,
            expected_base_hash=preview.base_hash,
            confirmed=True,
            config_path=config_path,
            project_root=project_root,
        )

    assert config_path.read_bytes() == before_config
    assert agent_path.read_bytes() == before_agent


def test_apply_rejects_stale_preview(tmp_path: Path) -> None:
    config_path, project_root, _ = _fixture(tmp_path)
    preview = preview_provider_merge(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=["ai-pixel_ad214f09"],
        credential_decisions={"ai-pixel_ad214f09": "use_canonical"},
        config_path=config_path,
        project_root=project_root,
    )
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n[custom]\nvalue = 1\n",
        encoding="utf-8",
    )

    with pytest.raises(ProviderMergeConflictError, match="changed"):
        apply_provider_merge(
            preview.preview_id,
            expected_base_hash=preview.base_hash,
            confirmed=True,
            config_path=config_path,
            project_root=project_root,
        )
