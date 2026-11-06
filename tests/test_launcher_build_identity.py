from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from core.launcher import build_identity, desktop_shell, freshness

TREE = "a" * 40
COMMIT = "b" * 40
NATIVE_PREPARE_UNPACKAGED = desktop_shell.prepare_unpackaged_electron


@pytest.fixture(autouse=True)
def forbid_builds(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("build identity inspection must not build, promote, or launch")

    for name in (
        "ensure_unpackaged_electron", "_rebuild_unpackaged_electron",
        "_promote_prepared_unpackaged_electron", "_stage_desktop_shell",
        "launch_packaged_desktop_shell", "prepare_unpackaged_electron",
    ):
        monkeypatch.setattr(desktop_shell, name, forbidden)
    monkeypatch.setattr(
        desktop_shell, "_git_tree_hash",
        lambda _root, spec: TREE if spec == "HEAD:desktop/electron" else COMMIT,
    )
    monkeypatch.setattr(desktop_shell, "_electron_sources_newer_than", lambda *_args: False)
    monkeypatch.setattr(desktop_shell, "_electron_package_sources_clean", lambda _root: True)
    monkeypatch.setattr(desktop_shell, "_usable_active_frontend_release", lambda _root: True)
    monkeypatch.setattr(desktop_shell, "resolve_active_frontend_dist", lambda root: root / "active-frontend")


def unpackaged(root: Path, *, staged: bool = False, main: bytes = b"main") -> Path:
    dist = root / desktop_shell.UNPACKAGED_STAGING_RELATIVE if staged else desktop_shell.unpackaged_main_js(root).parent
    (dist / "native").mkdir(parents=True)
    (dist / "main.js").write_bytes(main)
    (dist / "preload.cjs").write_bytes(b"preload")
    (dist / "native/workbench_job.node").write_bytes(b"native")
    (dist / "unpackaged-provenance.json").write_text(json.dumps({
        "schemaVersion": 1, "electronTreeHash": TREE,
        "sourceCommit": COMMIT, "builtAt": "2026-11-06T00:00:00Z",
    }), encoding="utf-8")
    binary = root / desktop_shell.UNPACKAGED_ELECTRON_EXE_RELATIVE
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"electron")
    return dist


def packaged(root: Path, *, staged: bool = False) -> tuple[Path, dict]:
    package = root / desktop_shell.STAGING_WIN_UNPACKED_RELATIVE if staged else desktop_shell.packaged_desktop_exe(root).parent
    provenance_path = package / "resources/app.asar.unpacked/package-provenance.json"
    provenance_path.parent.mkdir(parents=True)
    (package / "Vibelution.exe").write_bytes(b"exe")
    (package / "resources/app.asar").write_bytes(b"asar")
    assistant = package / "resources/launcher-assistant"
    (assistant / "source/scripts").mkdir(parents=True)
    (assistant / "source/scripts/assistant_host.py").write_bytes(b"host")
    (assistant / "python").mkdir()
    (assistant / "python/pythonw.exe").write_bytes(b"python")
    provenance = {
        "electronTreeHash": TREE, "sourceCommit": COMMIT,
        "mainBundleSha256": "1" * 64, "preloadBundleSha256": "2" * 64,
        "frontendContentSha256": "3" * 64, "assistant": {"contentSha256": "4" * 64},
        "builtAt": "2026-11-06T00:00:00Z",
        "frontendBuildKey": "e" * 64, "frontendSourceCommit": "f" * 40,
    }
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    active = root / "active-frontend"
    active.mkdir(exist_ok=True)
    (active / ".vibelution-build.json").write_text(json.dumps({"buildKey": "e" * 64,
        "frontendTree": "c" * 40, "sourceCommit": "f" * 40}), encoding="utf-8")
    return package, provenance


def write_packaged_provenance(package: Path, provenance: dict) -> None:
    (package / "resources/app.asar.unpacked/package-provenance.json").write_text(json.dumps(provenance), encoding="utf-8")


@pytest.mark.parametrize("kind", ["packaged", "unpackaged"])
def test_no_complete_artifact_is_not_built_without_using_head_as_build(tmp_path, kind):
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind=kind) == {
        "availableBuild": None, "availableBuildState": "not_built",
    }
    assert list(tmp_path.iterdir()) == []


def test_unpackaged_prefers_current_live_even_when_staged_bytes_differ(tmp_path, monkeypatch):
    live = unpackaged(tmp_path, main=b"live")
    stage = unpackaged(tmp_path, staged=True, main=b"staged")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    result = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")

    assert result["availableBuildState"] == "ready"
    assert result["availableBuild"] == {
        "kind": "unpackaged", "id": desktop_shell._frontend_directory_content_sha256(live),
        "electronTree": TREE, "sourceCommit": COMMIT, "builtAt": "2026-11-06T00:00:00Z",
    }
    assert result["availableBuild"]["id"] != desktop_shell._frontend_directory_content_sha256(stage)
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    monkeypatch.setattr(desktop_shell, "_prepared_unpackaged_electron_is_current", lambda _root: pytest.fail("current live must skip staging"))
    assert NATIVE_PREPARE_UNPACKAGED(tmp_path)["rebuilt"] is False


def test_unpackaged_stale_live_uses_current_staging_like_native_prepare(tmp_path):
    live = unpackaged(tmp_path, main=b"live")
    stage = unpackaged(tmp_path, staged=True, main=b"stage")
    (live / "unpackaged-provenance.json").write_text(json.dumps({"electronTreeHash": "c" * 40}), encoding="utf-8")
    result = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")
    assert result["availableBuildState"] == "ready"
    assert result["availableBuild"]["id"] == desktop_shell._frontend_directory_content_sha256(stage)
    assert NATIVE_PREPARE_UNPACKAGED(tmp_path) == {"rebuilt": False, "prepared": True, "reason": "prepared"}


def test_unpackaged_staging_without_electron_binary_cannot_be_available(tmp_path):
    unpackaged(tmp_path, staged=True)
    (tmp_path / desktop_shell.UNPACKAGED_ELECTRON_EXE_RELATIVE).unlink()
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged") == {
        "availableBuild": None, "availableBuildState": "not_built",
    }
    with pytest.raises(RuntimeError, match="binary is missing"):
        NATIVE_PREPARE_UNPACKAGED(tmp_path)


def test_unpackaged_rejects_incomplete_staging_and_uses_complete_live(tmp_path):
    live = unpackaged(tmp_path)
    stage = unpackaged(tmp_path, staged=True)
    (stage / "preload.cjs").unlink()
    result = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")
    assert result["availableBuildState"] == "ready"
    assert result["availableBuild"]["id"] == desktop_shell._frontend_directory_content_sha256(live)


@pytest.mark.parametrize("missing", ["main.js", "preload.cjs", "native/workbench_job.node"])
def test_unpackaged_requires_complete_platform_bundles(tmp_path, monkeypatch, missing):
    dist = unpackaged(tmp_path)
    (dist / missing).unlink()
    # Windows native completeness remains owned by the existing helper.
    monkeypatch.setattr(desktop_shell.os, "name", "nt")
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")["availableBuildState"] == "not_built"


def test_unpackaged_same_commit_different_artifact_bytes_have_different_id(tmp_path):
    dist = unpackaged(tmp_path)
    first = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")["availableBuild"]
    (dist / "native/workbench_job.node").write_bytes(b"new native artifact")
    second = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")["availableBuild"]
    assert first["sourceCommit"] == second["sourceCommit"] == COMMIT
    assert first["id"] != second["id"]


@pytest.mark.parametrize("proof", [{}, {"electronTreeHash": "bad"}, {"electronTreeHash": "c" * 40}, []])
def test_unpackaged_missing_invalid_or_stale_provenance_has_no_build(tmp_path, proof):
    dist = unpackaged(tmp_path)
    (dist / "unpackaged-provenance.json").write_text(json.dumps(proof), encoding="utf-8")
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged") == {
        "availableBuild": None, "availableBuildState": "not_built",
    }


def test_unpackaged_legacy_provenance_does_not_invent_optional_build_metadata(tmp_path):
    dist = unpackaged(tmp_path)
    (dist / "unpackaged-provenance.json").write_text(json.dumps({"electronTreeHash": TREE}), encoding="utf-8")
    build = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")["availableBuild"]
    assert set(build) == {"kind", "id", "electronTree"}


@pytest.mark.parametrize("staged", [False, True])
def test_unpackaged_does_not_accept_unknown_or_stale_source(tmp_path, monkeypatch, staged):
    unpackaged(tmp_path, staged=staged)
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda *_args: "")
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged") == {
        "availableBuild": None, "availableBuildState": "unknown",
    }
    monkeypatch.setattr(desktop_shell, "_git_tree_hash", lambda *_args: "c" * 40)
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="unpackaged")["availableBuildState"] == "not_built"


def test_shared_directory_hash_fixed_fixture(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/app.js").write_bytes(b"export{};\n")
    (tmp_path / "index.html").write_bytes(b"<main>v</main>\n")
    assert desktop_shell._frontend_directory_content_sha256(tmp_path) == "62e27c13de01ec035463d06ba40958d43b95919fcc7927dedab721b91998100b"


def test_packaged_current_live_identity_matches_native_prepare_selection(tmp_path, monkeypatch):
    stage, stage_proof = packaged(tmp_path, staged=True)
    stage_proof["mainBundleSha256"] = "5" * 64
    write_packaged_provenance(stage, stage_proof)
    live, _proof = packaged(tmp_path)
    calls = []

    def inspect(root, package_root=None, *, for_reuse=False):
        assert for_reuse is False, "status reads must not perform full runtime hashing"
        calls.append((root, package_root, for_reuse))
        return {"stale": False, "reason": "current"}

    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", inspect)
    result = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")
    assert result["availableBuildState"] == "ready"
    archive_hash = hashlib.sha256(b"asar").hexdigest()
    expected = ["packaged", TREE, "1" * 64, "2" * 64, "3" * 64, "4" * 64, archive_hash]
    assert result["availableBuild"]["id"] == hashlib.sha256(json.dumps(expected, separators=(",", ":")).encode()).hexdigest()
    assert calls == [(tmp_path, live, False)]
    monkeypatch.setattr(desktop_shell, "_ensure_desktop_shell_build_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(desktop_shell, "_release_desktop_shell_refresh_lock", lambda *_args, **_kwargs: None)
    assert desktop_shell.run_desktop_shell_prebuild(tmp_path)["skipped"] == "current"
    assert calls == [(tmp_path, live, False), (tmp_path, None, False)]


def test_packaged_stale_live_falls_back_to_staging_only_if_native_fast_check_allows_it(tmp_path, monkeypatch):
    stage, _proof = packaged(tmp_path, staged=True)
    live, _proof = packaged(tmp_path)
    calls = []

    def inspect(_root, candidate, *, for_reuse):
        assert for_reuse is False
        calls.append((candidate, for_reuse))
        return {"stale": candidate == live, "reason": "provenance_mismatch" if candidate == live else "current",
            "currentFrontendDist": str(tmp_path / "active-frontend"), "currentFrontendBuildKey": "e" * 64,
            "currentFrontendTree": "c" * 40}

    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", inspect)
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuildState"] == "ready"
    assert calls == [(live, False), (stage, False)]
    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: {"stale": True})
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuildState"] == "not_built"


@pytest.mark.parametrize("field", ["mainBundleSha256", "preloadBundleSha256", "frontendContentSha256", "assistant"])
@pytest.mark.parametrize("invalid", [None, "not-a-hash"])
def test_packaged_missing_or_invalid_hash_is_not_a_build(tmp_path, monkeypatch, field, invalid):
    package, proof = packaged(tmp_path)
    proof[field] = invalid
    write_packaged_provenance(package, proof)
    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: {"stale": False})
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged") == {
        "availableBuild": None, "availableBuildState": "not_built",
    }


def test_packaged_same_commit_different_bundle_hash_changes_identity(tmp_path, monkeypatch):
    package, proof = packaged(tmp_path)
    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: {"stale": False})
    first = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuild"]
    proof["mainBundleSha256"] = "5" * 64
    write_packaged_provenance(package, proof)
    second = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuild"]
    assert first["sourceCommit"] == second["sourceCommit"] == COMMIT
    assert first["id"] != second["id"]


def test_packaged_same_metadata_but_changed_archive_has_different_identity(tmp_path, monkeypatch):
    package, _proof = packaged(tmp_path)
    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: {"stale": False})
    first = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuild"]
    (package / "resources/app.asar").write_bytes(b"different imported module")
    second = build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuild"]
    assert first["sourceCommit"] == second["sourceCommit"]
    assert first["id"] != second["id"]


@pytest.mark.parametrize("missing", ["source/scripts/assistant_host.py", "python/pythonw.exe"])
def test_packaged_missing_runtime_entry_is_not_available(tmp_path, monkeypatch, missing):
    package, _proof = packaged(tmp_path)
    (package / "resources/launcher-assistant" / missing).unlink()
    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: {"stale": False})
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuildState"] == "not_built"


@pytest.mark.parametrize("kind", ["packaged", "unpackaged"])
def test_incomplete_native_current_live_cannot_advertise_an_unselected_stage(tmp_path, monkeypatch, kind):
    if kind == "packaged":
        live, _proof = packaged(tmp_path)
        packaged(tmp_path, staged=True)
        (live / "resources/launcher-assistant/python/pythonw.exe").unlink()
        monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: {"stale": False})
    else:
        live = unpackaged(tmp_path)
        unpackaged(tmp_path, staged=True)
        (live / "preload.cjs").unlink()
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind=kind) == {
        "availableBuild": None, "availableBuildState": "not_built",
    }


@pytest.mark.parametrize("field,invalid", [("buildKey", "0" * 64), ("frontendTree", "0" * 40), ("sourceCommit", "0" * 40)])
def test_staging_retains_native_frontend_metadata_gates(tmp_path, monkeypatch, field, invalid):
    packaged(tmp_path, staged=True)
    active_proof = tmp_path / "active-frontend/.vibelution-build.json"
    proof = json.loads(active_proof.read_text(encoding="utf-8"))
    proof[field] = invalid
    active_proof.write_text(json.dumps(proof), encoding="utf-8")
    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: {
        "stale": False, "currentFrontendDist": str(tmp_path / "active-frontend"),
        "currentFrontendBuildKey": "e" * 64, "currentFrontendTree": "c" * 40,
    })
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuildState"] == "not_built"


def test_packaged_real_native_fast_inspector_does_not_hash_full_assistant_runtime(tmp_path, monkeypatch):
    package, proof = packaged(tmp_path)
    active = tmp_path / "active-frontend"
    embedded = package / "resources/web-dist"
    for dist in (active, embedded):
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_bytes(b"frontend")
    (embedded / ".vibelution-build.json").write_bytes((active / ".vibelution-build.json").read_bytes())
    proof.update({
        "frontendContentSha256": desktop_shell._frontend_directory_content_sha256(embedded),
        "frontendTreeHash": "c" * 40, "frontendBuildKey": "e" * 64,
        "frontendSourceCommit": "f" * 40,
    })
    write_packaged_provenance(package, proof)
    monkeypatch.setattr(desktop_shell, "inspect_frontend_build", lambda _root: {
        "current": True, "dist": str(active), "buildKey": "e" * 64,
        "provenance": {"frontendTree": "c" * 40, "sourceCommit": "f" * 40, "buildKey": "e" * 64},
    })
    monkeypatch.setattr(desktop_shell, "resolve_active_frontend_dist", lambda _root: active)
    monkeypatch.setattr(desktop_shell, "_usable_active_frontend_release", lambda _root: True)
    monkeypatch.setattr(desktop_shell, "_electron_package_sources_clean", lambda _root: True)
    assistant_checks = []

    def assistant(_root, candidate, *, full=False):
        assert full is False, "the update action owns full assistant verification"
        assistant_checks.append((candidate, full))
        return ""

    monkeypatch.setattr(desktop_shell, "_assistant_package_block_reason", assistant)
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuildState"] == "ready"
    assert assistant_checks == [(package, False)]
    proof["sourceCommit"] = "0" * 40
    write_packaged_provenance(package, proof)
    # Native preparation reuses current live bytes even when an unrelated HEAD
    # commit moved forward; the displayed target must stay that same live build.
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuildState"] == "ready"


@pytest.mark.parametrize("kind", ["packaged", "unpackaged"])
def test_inspection_failure_is_unknown(tmp_path, monkeypatch, kind):
    if kind == "packaged":
        packaged(tmp_path)
        method = "_inspect_desktop_shell_package"
    else:
        unpackaged(tmp_path)
        method = "inspect_unpackaged_electron"

    def fail(*_args, **_kwargs):
        raise OSError("artifact cannot be inspected")

    monkeypatch.setattr(desktop_shell, method, fail)
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind=kind) == {
        "availableBuild": None, "availableBuildState": "unknown",
    }


def test_unrelated_shell_or_frontend_is_not_a_candidate(tmp_path, monkeypatch):
    unpackaged(tmp_path)
    frontend = tmp_path / "web/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("frontend", encoding="utf-8")
    monkeypatch.setattr(desktop_shell, "_inspect_desktop_shell_package", lambda *_args, **_kwargs: pytest.fail("no packaged artifact"))
    assert build_identity.inspect_available_launcher_build(tmp_path, shell_kind="packaged")["availableBuildState"] == "not_built"


def test_future_unpackaged_provenance_records_build_time_source_without_self_id(tmp_path):
    dist = tmp_path / "build"
    desktop_shell._write_unpackaged_provenance(tmp_path, TREE, dist=dist)
    proof = json.loads((dist / "unpackaged-provenance.json").read_text(encoding="utf-8"))
    assert proof["schemaVersion"] == 1
    assert proof["electronTreeHash"] == TREE
    assert proof["sourceCommit"] == COMMIT
    assert proof["builtAt"].endswith("Z")
    assert "buildId" not in proof


@pytest.mark.parametrize("kind", [None, "", "invalid"])
def test_old_or_invalid_freshness_kind_keeps_legacy_payload_and_skips_build_inspection(monkeypatch, kind):
    freshness.reset_launcher_start_identity_for_tests()
    monkeypatch.setattr(freshness, "_git_identity", lambda: {"commit": COMMIT, "branch": "main"})
    monkeypatch.setattr(freshness, "_unpackaged_shell_update", lambda: (False, "current"))
    monkeypatch.setattr(build_identity, "inspect_available_launcher_build", lambda *_args, **_kwargs: pytest.fail("legacy read must not inspect build candidates"))
    payload = freshness.get_launcher_freshness() if kind is None else freshness.get_launcher_freshness(shell_kind=kind)
    assert payload["current"] is True
    assert "availableBuild" not in payload
    assert "availableBuildState" not in payload


def test_freshness_projects_available_build_only_for_requested_kind(tmp_path, monkeypatch):
    freshness.reset_launcher_start_identity_for_tests()
    monkeypatch.setattr(freshness, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(freshness, "_git_identity", lambda: {"commit": COMMIT, "branch": "main"})
    monkeypatch.setattr(freshness, "_unpackaged_shell_update", lambda: (False, "current"))
    unpackaged(tmp_path)
    payload = freshness.get_launcher_freshness(shell_kind="unpackaged")
    assert payload["availableBuildState"] == "ready"
    assert payload["availableBuild"]["kind"] == "unpackaged"


def test_freshness_bridge_passes_shell_kind_query_to_owner(monkeypatch):
    from scripts import vibelution_desktop_entry as entry

    calls = []
    monkeypatch.setattr(entry, "_append_log", lambda *_args, **_kwargs: None)

    def get_freshness(*, shell_kind=None):
        calls.append(shell_kind)
        return {"availableBuild": None, "availableBuildState": "not_built"}

    monkeypatch.setattr(freshness, "get_launcher_freshness", get_freshness)
    result = entry._run_launcher_api_bridge(argparse.Namespace(
        launcher_api_path="freshness?shellKind=packaged", launcher_api_method="GET", launcher_api_body="",
    ))
    assert calls == ["packaged"]
    assert result["payload"]["availableBuildState"] == "not_built"
