from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = PROJECT_ROOT / "experiments" / "challenge_cup_spike_coding"
SCRIPT = EXPERIMENT_DIR / "sci096_dandi000121_multisession.py"


def _load_module():
    sys.path.insert(0, str(EXPERIMENT_DIR))
    spec = importlib.util.spec_from_file_location(
        "sci096_dandi000121_multisession",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _passing_record(asset_id: str, expected: dict) -> dict:
    return {
        "assetId": asset_id,
        "subject": expected["subject"],
        "path": expected["path"],
        "contentSize": expected["contentSize"],
        "sha256": expected["sha256"],
        "passed": True,
        "observedOctants": list(range(8)),
        "usableTrialCount": 120,
        "nonemptyUnitCount": 4,
        "splitCounts": {"train": 90, "validation": 30},
    }


def _write_manifest(path: Path, module) -> Path:
    asset_ids = list(module.FROZEN_ASSETS)
    payload = {
        "schemaVersion": module.QUALIFICATION_SCHEMA,
        "dandiset": module.DANDISET_ID,
        "dandisetVersion": module.DANDISET_VERSION,
        "decision": "qualified_for_bounded_download_and_runner_design",
        "formalExperimentAuthorized": False,
        "qualifiedSessionAssetIds": asset_ids,
        "carriedForwardSessions": [
            _passing_record(asset_id, module.FROZEN_ASSETS[asset_id])
            for asset_id in asset_ids[:2]
        ],
        "newSessionsScanned": [
            _passing_record(asset_ids[2], module.FROZEN_ASSETS[asset_ids[2]])
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    module.FROZEN_QUALIFICATION_SHA256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return path


def _session_result(
    subject: str,
    *,
    interaction: float,
    all_gates: bool,
) -> dict:
    gates = {
        "transition_temporal_vs_rate": all_gates,
        "transition_temporal_vs_shuffle": all_gates,
        "transition_vs_stationary_interaction": all_gates,
        "interaction_ci_excludes_zero": all_gates,
        "stationary_temporal_gain_below_threshold": all_gates,
    }
    return {
        "subject": subject,
        "decision": {
            "gates": gates,
            "transition_vs_stationary_balanced_accuracy_interaction_delta": interaction,
        },
    }


def test_manifest_freezes_three_assets_and_bounded_download_plan(
    tmp_path: Path,
) -> None:
    module = _load_module()
    manifest = _write_manifest(tmp_path / "manifest.json", module)

    bundle = module.load_qualification_manifest(manifest)
    plan = module.build_download_plan(bundle, tmp_path / "source")

    assert len(bundle.sessions) == 3
    assert {session.subject for session in bundle.sessions} == {
        "Reggie",
        "JenkinsC",
    }
    assert bundle.total_source_bytes == 8_215_216_301
    assert bundle.total_source_bytes <= module.MAX_SOURCE_BYTES
    assert plan["formalExecutionAuthorized"] is False
    assert {asset["localStatus"] for asset in plan["assets"]} == {"missing"}
    assert [asset["assetId"] for asset in plan["assets"]] == list(
        module.FROZEN_ASSETS
    )


def test_manifest_rejects_frozen_asset_metadata_drift(tmp_path: Path) -> None:
    module = _load_module()
    manifest = _write_manifest(tmp_path / "manifest.json", module)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["carriedForwardSessions"][0]["contentSize"] += 1
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    module.FROZEN_QUALIFICATION_SHA256 = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="metadata drifted"):
        module.load_qualification_manifest(manifest)


def test_manifest_rejects_path_traversal_before_local_file_access(
    tmp_path: Path,
) -> None:
    module = _load_module()
    manifest = _write_manifest(tmp_path / "manifest.json", module)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["carriedForwardSessions"][0]["path"] = "../session.nwb"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    module.FROZEN_QUALIFICATION_SHA256 = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="unsafe or non-NWB"):
        module.load_qualification_manifest(manifest)


def test_manifest_rejects_rewritten_evidence_even_when_semantics_match(
    tmp_path: Path,
) -> None:
    module = _load_module()
    manifest = _write_manifest(tmp_path / "manifest.json", module)
    module.FROZEN_QUALIFICATION_SHA256 = "0" * 64

    with pytest.raises(ValueError, match="does not match the frozen evidence"):
        module.load_qualification_manifest(manifest)


def test_downloaded_asset_requires_size_and_sha256_integrity(
    tmp_path: Path,
) -> None:
    module = _load_module()
    source = tmp_path / "session.nwb"
    source.write_bytes(b"fixture")

    module.validate_downloaded_asset(
        source,
        expected_size=7,
        expected_sha256="expected",
        hash_reader=lambda _: "expected",
    )
    with pytest.raises(ValueError, match="size mismatch"):
        module.validate_downloaded_asset(
            source,
            expected_size=8,
            expected_sha256="expected",
            hash_reader=lambda _: "expected",
        )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        module.validate_downloaded_asset(
            source,
            expected_size=7,
            expected_sha256="expected",
            hash_reader=lambda _: "different",
        )


def test_formal_run_requires_independent_manifest_bound_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    manifest = _write_manifest(tmp_path / "manifest.json", module)
    bundle = module.load_qualification_manifest(manifest)
    authorization = tmp_path / "authorization.json"
    authorization.write_text(
        json.dumps(
            {
                "schemaVersion": module.AUTHORIZATION_SCHEMA,
                "experimentId": module.EXPERIMENT_ID,
                "qualificationManifestSha256": bundle.manifest_sha256,
                "formalExperimentAuthorized": False,
                "qualifiedSessionAssetIds": [
                    session.asset_id for session in bundle.sessions
                ],
                "authorizedBy": "reviewer",
                "authorizedAt": "2026-07-23T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "validate_local_assets",
        lambda *_: pytest.fail("local assets must not be read before authorization"),
    )

    with pytest.raises(PermissionError, match="has not been authorized"):
        module.run_multisession(
            qualification_manifest=manifest,
            source_root=tmp_path / "source",
            execution_authorization=authorization,
        )


def test_runner_excludes_empty_unit_rows_and_binds_count_to_qualification() -> None:
    module = _load_module()
    expected = next(iter(module.FROZEN_ASSETS.items()))
    session = module.QualifiedSession(
        asset_id=expected[0],
        subject=expected[1]["subject"],
        relative_path=expected[1]["path"],
        content_size=expected[1]["contentSize"],
        sha256=expected[1]["sha256"],
        usable_trial_count=120,
        nonempty_unit_count=2,
        train_trial_count=90,
        validation_trial_count=30,
    )
    dataset = {
        "unit_spikes": [[0.1, 0.2], [], [0.3]],
        "retained_unit_count": 3,
    }

    prepared = module.retain_qualified_nonempty_units(dataset, session)

    assert prepared["unit_spikes"] == [[0.1, 0.2], [0.3]]
    assert prepared["retained_unit_count"] == 2
    assert prepared["excluded_empty_unit_count"] == 1
    assert dataset["retained_unit_count"] == 3


def test_cross_subject_support_requires_replication_and_positive_sessions() -> None:
    module = _load_module()
    supported = module.classify_multisession_results(
        [
            _session_result("Reggie", interaction=0.12, all_gates=True),
            _session_result("JenkinsC", interaction=0.10, all_gates=True),
            _session_result("Reggie", interaction=0.04, all_gates=False),
        ],
        minimum_supported_delta=0.08,
    )
    contradicted = module.classify_multisession_results(
        [
            _session_result("Reggie", interaction=0.12, all_gates=True),
            _session_result("JenkinsC", interaction=0.10, all_gates=True),
            _session_result("Reggie", interaction=0.0, all_gates=False),
        ],
        minimum_supported_delta=0.08,
    )

    assert supported["status"] == (
        "supports_cross_subject_state_conditioned_temporal_utility"
    )
    assert supported["decision"] == "CONTINUE"
    assert contradicted["status"] == "inconclusive_cross_subject_replication"
    assert contradicted["gates"]["no_session_has_nonpositive_interaction"] is False


def test_cross_subject_result_rejects_missing_jenkins_replication() -> None:
    module = _load_module()
    result = module.classify_multisession_results(
        [
            _session_result("Reggie", interaction=0.12, all_gates=True),
            _session_result("JenkinsC", interaction=-0.02, all_gates=False),
            _session_result("Reggie", interaction=0.10, all_gates=True),
        ],
        minimum_supported_delta=0.08,
    )

    assert result["status"] == "does_not_support_cross_subject_replication"
    assert result["decision"] == "BRANCH"
    assert result["gates"]["both_subjects_have_a_supporting_session"] is False
