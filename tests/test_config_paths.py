import json
from pathlib import Path

from config.paths import (
    CONFIG_META_SCHEMA_VERSION,
    DATA_HOME_ENV,
    CONFIG_HOME_ENV,
    CONFIG_PATH_ENV,
    ensure_global_config_initialized,
    resolve_config_backup_dir,
    resolve_config_home,
    resolve_config_meta_path,
    resolve_config_path,
    resolve_data_backup_dir,
    resolve_data_home,
    resolve_workspace_home,
)
from config.runtime_capabilities import MODEL_CAPABILITY_CACHE_ENV, get_model_capability_cache_path
from scripts import deploy_auto_advance_policy as policy_deploy


def test_resolve_config_path_defaults_to_user_documents(monkeypatch, tmp_path):
    user_root = tmp_path / "user"
    monkeypatch.setenv("USERPROFILE", str(user_root))
    monkeypatch.delenv("VIBELUTION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("VIBELUTION_CONFIG_HOME", raising=False)

    assert resolve_config_home() == user_root / "Documents" / "Vibelution" / "config"
    assert resolve_config_path() == user_root / "Documents" / "Vibelution" / "config" / "config.toml"


def test_resolve_data_home_defaults_to_user_documents(monkeypatch, tmp_path):
    user_root = tmp_path / "user"
    monkeypatch.setenv("USERPROFILE", str(user_root))
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)
    monkeypatch.delenv(CONFIG_HOME_ENV, raising=False)

    assert resolve_data_home() == user_root / "Documents" / "Vibelution" / "data"
    assert resolve_workspace_home() == user_root / "Documents" / "Vibelution" / "data" / "workspace"
    assert resolve_data_backup_dir() == user_root / "Documents" / "Vibelution" / "data" / "backups"


def test_resolve_config_path_prefers_explicit_config_path(monkeypatch, tmp_path):
    explicit_path = tmp_path / "custom" / "operator.toml"
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(explicit_path))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(tmp_path / "ignored-home"))

    assert resolve_config_path() == explicit_path
    assert resolve_config_meta_path() == explicit_path.with_name("config.meta.json")
    assert resolve_config_backup_dir() == explicit_path.parent / "backups"


def test_resolve_config_path_uses_config_home_when_no_path_override(monkeypatch, tmp_path):
    config_home = tmp_path / "global-config"
    monkeypatch.delenv("VIBELUTION_CONFIG_PATH", raising=False)
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(config_home))

    assert resolve_config_path() == config_home / "config.toml"


def test_resolve_data_home_prefers_env_override(monkeypatch, tmp_path):
    data_home = tmp_path / "operator-data"
    monkeypatch.setenv(DATA_HOME_ENV, str(data_home))

    assert resolve_data_home() == data_home
    assert resolve_workspace_home() == data_home / "workspace"


def test_resolve_data_home_uses_storage_config_when_no_env(monkeypatch, tmp_path):
    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("[storage]\ndata_home = \"../operator-data\"\n", encoding="utf-8")
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))

    assert resolve_data_home() == tmp_path / "operator-data"
    assert resolve_workspace_home() == tmp_path / "operator-data" / "workspace"


def test_resolve_data_home_caches_storage_config_until_file_changes(monkeypatch, tmp_path):
    from config import paths

    config_path = tmp_path / "config" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("[storage]\ndata_home = \"../operator-data\"\n", encoding="utf-8")
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))
    paths._CONFIGURED_DATA_HOME_CACHE.clear()
    original_read_text = Path.read_text
    reads = []

    def counting_read_text(self, *args, **kwargs):
        if self == config_path:
            reads.append(str(self))
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    assert resolve_data_home() == tmp_path / "operator-data"
    assert resolve_data_home() == tmp_path / "operator-data"
    assert len(reads) == 1

    config_path.write_text("[storage]\ndata_home = \"../operator-data-v2\"\n", encoding="utf-8")

    assert resolve_data_home() == tmp_path / "operator-data-v2"
    assert len(reads) == 2


def test_model_capability_cache_defaults_next_to_external_config(monkeypatch, tmp_path):
    config_path = tmp_path / "operator-config" / "operator.toml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(config_path))
    monkeypatch.setenv(CONFIG_HOME_ENV, str(tmp_path / "ignored-home"))
    monkeypatch.delenv(MODEL_CAPABILITY_CACHE_ENV, raising=False)

    assert get_model_capability_cache_path() == config_path.parent / "model-capabilities.json"


def test_model_capability_cache_env_override_stays_explicit(monkeypatch, tmp_path):
    cache_path = tmp_path / "runtime-cache" / "custom-model-capabilities.json"
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(cache_path))

    assert get_model_capability_cache_path() == cache_path


def test_global_config_initialization_creates_external_starter_without_project_migration(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    legacy_config = project_root / "config.toml"
    legacy_example = project_root / "config.example.toml"
    legacy_config.write_text("[workbench]\nbackend_port = 9101\n", encoding="utf-8")
    legacy_example.write_text("[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    external_config = tmp_path / "external" / "config.toml"
    monkeypatch.delenv("VIBELUTION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("VIBELUTION_CONFIG_HOME", raising=False)

    meta = ensure_global_config_initialized(external_config, project_root=project_root)

    assert "operator config" in external_config.read_text(encoding="utf-8")
    assert "backend_port = 9101" not in external_config.read_text(encoding="utf-8")
    assert "example operator config" in external_config.with_name("config.example.toml").read_text(encoding="utf-8")
    assert "backend_port = 8000" not in external_config.with_name("config.example.toml").read_text(encoding="utf-8")
    assert Path(meta["configPath"]) == external_config
    assert Path(meta["backupDir"]) == external_config.parent / "backups"
    assert Path(meta["lockPath"]) == external_config.parent / "config-edit.lock"
    assert meta["createdConfig"] is True
    assert meta["configSource"] == "external_starter"
    assert meta["exampleConfigSource"] == "external_example_starter"
    assert external_config.with_name("config.meta.json").exists()
    assert (external_config.parent / "backups").is_dir()

    external_config.write_text("[workbench]\nbackend_port = 9201\n", encoding="utf-8")
    legacy_config.write_text("[workbench]\nbackend_port = 9301\n", encoding="utf-8")

    ensure_global_config_initialized(external_config, project_root=project_root)

    assert external_config.read_text(encoding="utf-8") == "[workbench]\nbackend_port = 9201\n"


def test_global_config_initialization_upgrades_existing_meta_without_overwriting_config_origin(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config.example.toml").write_text("[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    external_config = tmp_path / "external" / "config.toml"
    external_config.parent.mkdir(parents=True)
    external_config.write_text("[workbench]\nbackend_port = 8000\n", encoding="utf-8")
    meta_path = external_config.with_name("config.meta.json")
    meta_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "configHome": str(external_config.parent),
                "configPath": str(external_config),
                "exampleConfigPath": str(external_config.with_name("config.example.toml")),
                "createdAt": "2026-06-11T09:20:00+00:00",
                "createdConfig": True,
                "createdExampleConfig": True,
                "configSource": "project_config",
                "exampleConfigSource": "project_example",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    ensure_global_config_initialized(external_config, project_root=project_root)

    upgraded = json.loads(meta_path.read_text(encoding="utf-8"))
    assert upgraded["schemaVersion"] == CONFIG_META_SCHEMA_VERSION
    assert upgraded["configSource"] == "project_config"
    assert upgraded["exampleConfigSource"] == "external_example_starter"
    assert upgraded["createdAt"] == "2026-06-11T09:20:00+00:00"
    assert Path(upgraded["backupDir"]) == external_config.parent / "backups"
    assert Path(upgraded["lockPath"]) == external_config.parent / "config-edit.lock"


# ---------------------------------------------------------------------------
# Approved auto-advance policy: tracked template vs deployed copy
#
# The template is the governance authority, but the runtime reads the
# operator's deployed copy, and both readers fail silent.  Commit 3859bbc79
# added the sixth capability switch to the template while the deployed copy
# stayed behind, which silently disabled the automation chain; these tests pin
# both halves of that boundary.


def _template_payload() -> dict:
    return json.loads(policy_deploy.template_path().read_text(encoding="utf-8"))


def test_tracked_auto_advance_template_satisfies_the_activation_contract(tmp_path):
    """A contract change must not leave the repo authority unloadable."""

    template = policy_deploy.template_path()
    assert template.is_file(), f"tracked template is missing: {template}"

    report = policy_deploy.inspect(template=template, deployed=tmp_path / "absent.json")

    assert report["templateErrors"] == []
    assert report["state"] == "deployed_missing"


def test_policy_deploy_check_reports_drift_for_a_stale_deployed_copy(tmp_path):
    template = tmp_path / "template.json"
    deployed = tmp_path / "deployed.json"
    payload = _template_payload()
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    template.write_text(encoded, encoding="utf-8")
    deployed.write_text(encoded, encoding="utf-8")

    in_sync = policy_deploy.inspect(template=template, deployed=deployed)
    assert in_sync["state"] == "in_sync"
    assert in_sync["inSync"] is True
    assert policy_deploy._exit_code(in_sync) == policy_deploy.EXIT_OK

    # The exact incident shape: the deployed copy predates a capability that
    # the contract now requires, so it is drift *and* invalid.
    stale = json.loads(json.dumps(payload))
    stale["capabilities"].pop("autoAdjudicateQuestionReview")
    deployed.write_text(
        json.dumps(stale, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    drift = policy_deploy.inspect(template=template, deployed=deployed)
    assert drift["state"] == "drift"
    assert drift["inSync"] is False
    assert any("missing_capability" in item for item in drift["deployedErrors"])
    assert policy_deploy._exit_code(drift) == policy_deploy.EXIT_DRIFT


def test_policy_deploy_write_syncs_the_copy_and_backs_up_the_previous_one(tmp_path):
    template = tmp_path / "template.json"
    deployed = tmp_path / "deployed.json"
    encoded = json.dumps(_template_payload(), ensure_ascii=False, indent=2) + "\n"
    template.write_text(encoded, encoding="utf-8")
    deployed.write_text('{"policyId": "stale"}\n', encoding="utf-8")

    report = policy_deploy.deploy(template=template, deployed=deployed)

    assert report["written"] is True
    assert report["state"] == "deployed"
    assert deployed.read_text(encoding="utf-8") == encoded
    backup = Path(report["backupPath"])
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == '{"policyId": "stale"}\n'
    assert policy_deploy._exit_code(report) == policy_deploy.EXIT_OK

    # Deploying again is a no-op; the runtime source already matches.
    again = policy_deploy.deploy(template=template, deployed=deployed)
    assert again["written"] is False
    assert again["state"] == "in_sync"


def test_policy_deploy_refuses_to_deploy_an_invalid_template(tmp_path):
    template = tmp_path / "template.json"
    deployed = tmp_path / "deployed.json"
    template.write_text('{"policyId": "broken"}\n', encoding="utf-8")
    deployed.write_text('{"policyId": "broken"}\n', encoding="utf-8")

    report = policy_deploy.deploy(template=template, deployed=deployed)

    assert report["written"] is False
    assert report["state"] == "template_invalid"
    assert policy_deploy._exit_code(report) == policy_deploy.EXIT_TEMPLATE_PROBLEM
