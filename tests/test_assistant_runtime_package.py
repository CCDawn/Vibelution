"""Small offline package fixtures; never copy the operator's Python runtime."""

from __future__ import annotations

import base64
import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_assistant_runtime import (
    build_launcher_assistant_payload,
    verify_launcher_assistant_payload,
)


def _write(root, name, content=b"fixture"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _distribution(site, name, *, version="1.0", requires=(), files=None, records=()):
    info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    metadata += "".join(f"Requires-Dist: {value}\n" for value in requires)
    payload = {f"{name.replace('-', '_')}/__init__.py": b"", **(files or {}),
               f"{info}/METADATA": metadata.encode(), f"{info}/licenses/LICENSE": b"license"}
    rows = []
    for relative, content in payload.items():
        _write(site, relative, content)
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
        rows.append((relative, f"sha256={digest}", len(content)))
    rows.extend(records)
    record = _write(site, f"{info}/RECORD", b"")
    with record.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows([*rows, (f"{info}/RECORD", "", "")])
    return info


@pytest.fixture
def package_fixture(tmp_path):
    project, python, site = (tmp_path / name for name in ("project", "base-python", "site"))
    for name in ("agent.py", "vibelution_storage.py", "VERSION", "AGENTS.md",
                 "scripts/assistant_host.py", "scripts/windowless_subprocess.py",
                 "core/__init__.py", "core/external_agent/contracts.py",
                 "core/core_prompt/COMMON.md", "core/core_prompt/SOUL.md",
                 "config/__init__.py", "tools/__init__.py", "schemas/example.json",
                 "assets/theme_backgrounds/default.png", "assets/agent-avatars/default.png"):
        _write(project, name)
    _write(project, "requirements.txt", b'root[feature]>=1; platform_system == "Windows"\n'
           b'absent; platform_system == "Linux"\n# \xe5\xbc\x80\xe5\x8f\x91/\xe6\xb5\x8b\xe8\xaf\x95\xe4\xbe\x9d\xe8\xb5\x96\npytest>=7\n')
    for name in ("python.exe", "pythonw.exe", "python3.dll", "python312.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt", "DLLs/_ssl.pyd",
                 "Lib/encodings/__init__.py", "Lib/site.py", "tcl/tcl8.6/init.tcl"):
        _write(python, name)
    _distribution(site, "root", requires=('child>=1; extra == "feature"',),
                  files={"root/data.json": b"data", "root/native.pyd": b"native", "root.libs/a.dll": b"dll"},
                  records=(("../../Scripts/root.exe", "", ""),))
    _distribution(site, "child")
    _distribution(site, "torch", files={"torch/unused.dll": b"do not copy"})
    return project, python, site, tmp_path / "payload"


def _build(fixture):
    project, python, site, output = fixture
    return build_launcher_assistant_payload(project, output, python_root=python,
                                            site_packages=site, python_version="3.12.10")


def test_builds_offline_closure_and_complete_product_files(package_fixture):
    project, python, _site, output = package_fixture
    for root, name in ((project, "config/config.toml"), (project, "config/private.json"),
                       (project, "core/__pycache__/bad.pyc"),
                       (project, "core/workspace/private.json"), (project, "core/logs/private.txt"),
                       (project, "scripts/private.ps1"), (python, "Lib/site-packages/foreign.py"),
                       (python, "Lib/__pycache__/site.pyc")):
        _write(root, name, b"private")
    result = _build(package_fixture)
    manifest = verify_launcher_assistant_payload(output, expected_manifest_sha256=result["manifestSha256"])
    assert manifest["schemaVersion"] == 1
    assert manifest["pythonAbi"] == "cp312"
    # The wire-contract identity is sealed into the manifest against the exact
    # packaged bytes of the snapshot's contracts module.
    contracts = next(entry for entry in manifest["files"]
                     if entry["path"] == "source/core/external_agent/contracts.py")
    assert manifest["contractsSha256"] == contracts["sha256"]
    assert [d["name"] for d in manifest["dependencies"]] == ["child", "root"]
    assert manifest["excludedFiles"] == [{"distribution": "root", "path": "../../Scripts/root.exe",
                                          "reason": "console_entrypoint"}]
    paths = {entry["path"] for entry in manifest["files"]}
    assert {"source/assets/theme_backgrounds/default.png", "source/assets/agent-avatars/default.png",
            "source/core/core_prompt/COMMON.md", "source/AGENTS.md", "python/LICENSE.txt",
            "python/Lib/site-packages/root/native.pyd", "python/Lib/site-packages/root.libs/a.dll",
            "python/Lib/site-packages/root-1.0.dist-info/licenses/LICENSE"} <= paths
    assert not any("torch" in path or "private" in path or "__pycache__" in path for path in paths)
    assert not (output / "python/Lib/site-packages/foreign.py").exists()
    assert result["sourceRoot"] == str(output / "source")
    assert result["pythonRoot"] == str(output / "python")
    assert (output / "python/python312._pth").read_text().splitlines() == [
        "Lib", "DLLs", "Lib/site-packages", "../source", "import site"]


@pytest.mark.parametrize("fault,match", [
    ("missing", "not installed"), ("version", "does not satisfy"),
    ("escape", "RECORD path"), ("absolute", "RECORD path"),
    ("missing_record", "RECORD"), ("missing_file", "missing"),
    ("modified", "RECORD"), ("conflict", "conflict"),
])
def test_dependency_fault_retains_incomplete_output_without_manifest(package_fixture, fault, match):
    project, _python, site, output = package_fixture
    info = site / "root-1.0.dist-info"
    if fault == "missing":
        (info / "METADATA").write_text("Name: root\nVersion: 1.0\nRequires-Dist: missing-package\n")
    elif fault == "version":
        (project / "requirements.txt").write_text("root>=2\n# 开发/测试依赖\n", encoding="utf-8")
    elif fault in {"escape", "absolute"}:
        with (info / "RECORD").open("a") as handle:
            handle.write(("../../private.txt" if fault == "escape" else "C:/private.txt") + ",,\n")
    elif fault == "missing_record":
        (info / "RECORD").unlink()
    elif fault == "missing_file":
        (site / "root/data.json").unlink()
    elif fault == "modified":
        (site / "root/data.json").write_bytes(b"tampered")
    else:
        with (site / "child-1.0.dist-info/RECORD").open("a") as handle:
            handle.write("root/data.json,,\n")
    with pytest.raises(ValueError, match=match):
        _build(package_fixture)
    assert output.is_dir()
    assert not (output / "manifest.json").exists()


def test_never_overwrites_or_deletes_existing_output(package_fixture):
    output = package_fixture[-1]
    marker = _write(output, "keep.txt", b"untouched")
    with pytest.raises(FileExistsError):
        _build(package_fixture)
    assert marker.read_bytes() == b"untouched"


@pytest.mark.parametrize("fault", ["hash", "tamper", "missing", "extra", "bytecode", "path", "entrypoint", "dependencies"])
def test_verifier_rejects_corrupt_or_unbound_payload(package_fixture, fault):
    result = _build(package_fixture)
    output = package_fixture[-1]
    expected = result["manifestSha256"]
    if fault == "hash":
        expected = "0" * 64
    elif fault == "tamper":
        (output / "python/pythonw.exe").write_bytes(b"changed")
    elif fault == "missing":
        (output / "source/tools/__init__.py").unlink()
    elif fault == "extra":
        _write(output, "python/Lib/site-packages/injected.py")
    elif fault == "bytecode":
        _write(output, "python/Lib/__pycache__/injected.pyc")
    else:
        path = output / "manifest.json"
        manifest = json.loads(path.read_text())
        if fault == "path":
            manifest["files"][0]["path"] = "../escape"
        elif fault == "entrypoint":
            manifest["entrypoint"] = "source/agent.py"
        else:
            manifest["dependencies"] = []
        path.write_text(json.dumps(manifest))
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        verify_launcher_assistant_payload(output, expected_manifest_sha256=expected)


def test_snapshot_without_contracts_module_fails_the_build(package_fixture):
    project, python, site, output = package_fixture
    (project / "core/external_agent/contracts.py").unlink()
    # The contracts module is a required product file: a snapshot missing it
    # never produces a manifest, let alone a sealed contract identity.
    with pytest.raises(ValueError, match="required product file missing: core/external_agent/contracts.py"):
        _build(package_fixture)


def test_verifier_rejects_manifest_whose_contracts_identity_disagrees(package_fixture):
    _build(package_fixture)
    output = package_fixture[-1]
    # Simulates a manifest rewritten (or a pre-guard manifest) whose sealed
    # contracts identity no longer matches its own per-file hashes: the file
    # checks pass, but the wire-contract identity is not the packaged bytes.
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["contractsSha256"] != "0" * 64
    manifest["contractsSha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    expected = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="contracts identity mismatch"):
        verify_launcher_assistant_payload(output, expected_manifest_sha256=expected)
    # An old manifest without the field fails closed the same way.
    del manifest["contractsSha256"]
    manifest_path.write_text(json.dumps(manifest))
    expected = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="contracts identity mismatch"):
        verify_launcher_assistant_payload(output, expected_manifest_sha256=expected)


def test_missing_product_entrypoint_prevents_manifest(package_fixture):
    project, _, _, output = package_fixture
    (project / "scripts/assistant_host.py").unlink()
    with pytest.raises(ValueError, match="required"):
        _build(package_fixture)
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("link_kind", ["source", "dependency"])
def test_rejects_source_and_dependency_symlinks(package_fixture, link_kind):
    project, _, site, output = package_fixture
    target = site / "root/data.json"
    link = project / "core/linked.json" if link_kind == "source" else site / "root/native.pyd"
    if link.exists():
        link.unlink()
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation requires OS permission")
    with pytest.raises(ValueError, match="link"):
        _build(package_fixture)
    assert not (output / "manifest.json").exists()


def test_source_changes_do_not_change_stable_runtime_identity(package_fixture, tmp_path):
    first = _build(package_fixture)
    _write(package_fixture[0], "core/new.py", b"new source")
    second = _build((*package_fixture[:3], tmp_path / "another-payload"))
    assert first["manifest"]["sourceContentSha256"] != second["manifest"]["sourceContentSha256"]
    assert first["manifest"]["runtimeContentSha256"] == second["manifest"]["runtimeContentSha256"]


def test_preserves_competition_product_data_without_collecting_live_data(package_fixture):
    project, _, _, output = package_fixture
    resources = ("science_125_questions.json", "legacy_representative_deep_cases.v1.json",
                 "full_catalog_execution_core.v1.json", "competition_program_core.v2.json")
    for name in resources:
        _write(project, "core/research/competition/data/" + name, b'{"static":true}')
    for name in ("data/private.json", "core/other/data/private.json",
                 "core/research/competition/data/workspace/private.json"):
        _write(project, name, b"private")
    result = _build(package_fixture)
    paths = {entry["path"] for entry in result["manifest"]["files"]}
    assert {"source/core/research/competition/data/" + name for name in resources} <= paths
    assert not any("private" in path for path in paths)
    verify_launcher_assistant_payload(output, expected_manifest_sha256=result["manifestSha256"])


def test_records_missing_excluded_files_without_reading_installation_urls(package_fixture):
    site = package_fixture[2]
    with (site / "root-1.0.dist-info/RECORD").open("a", encoding="utf-8") as handle:
        handle.write("root/__pycache__/missing.pyc,,\n")
        handle.write("root-1.0.dist-info/direct_url.json,,\n")
        handle.write("a1_coverage.pth,,\n")
        handle.write("../../Scripts/__pycache__/postinstall.cpython-312.pyc,,\n")
    result = _build(package_fixture)
    excluded = result["manifest"]["excludedFiles"]
    assert {item["reason"] for item in excluded} == {
        "bytecode_cache", "installation_provenance", "development_bootstrap", "console_entrypoint"}
    assert not (package_fixture[-1] / "python/Lib/site-packages/root-1.0.dist-info/direct_url.json").exists()


def test_excludes_only_distribution_owned_standard_venv_build_headers(package_fixture):
    site, output = package_fixture[2:]
    headers = ("../../include/site/python3.12/root/root.h",
               "../../include/site/python3.12/root/detail/helper.hpp")
    with (site / "root-1.0.dist-info/RECORD").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows((name, "", "") for name in headers)
    result = _build(package_fixture)
    assert {item["path"] for item in result["manifest"]["excludedFiles"] if item["reason"] == "build_header"} == set(headers)
    assert not (output / "include").exists()
    verify_launcher_assistant_payload(output, expected_manifest_sha256=result["manifestSha256"])


@pytest.mark.parametrize("relative", [
    "../../include/site/python3.12/root/../private.h",
    "../../include/site/python3.12/root/detail/../../private.hpp",
    "../../../include/site/python3.12/root/root.h",
    "../../include/site/python3.12/another/root.h",
    "../../include/site/python3.11/root/root.h",
    "../../include/site/python3.12/root/root.dll",
    "../../include/site/python3.12/root/./root.h",
])
def test_rejects_escape_paths_disguised_as_build_headers(package_fixture, relative):
    with (package_fixture[2] / "root-1.0.dist-info/RECORD").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow((relative, "", ""))
    with pytest.raises(ValueError, match="unsafe RECORD path for root"):
        _build(package_fixture)
    assert not (package_fixture[-1] / "manifest.json").exists()


@pytest.mark.parametrize("content", [b"C:/private/python\n", b"../outside\n", b"import arbitrary_bootstrap\n"])
def test_rejects_external_pth_paths_and_unknown_executable_bootstraps(package_fixture, content):
    _distribution(package_fixture[2], "root", files={"escape.pth": content})
    with pytest.raises(ValueError, match="unsafe runtime .pth in distribution root"):
        _build(package_fixture)
    assert not (package_fixture[-1] / "manifest.json").exists()


def test_preserves_known_pywin32_bootstrap_and_internal_search_paths(package_fixture):
    project, _, site, output = package_fixture
    _write(project, "requirements.txt", b"pywin32\n# \xe5\xbc\x80\xe5\x8f\x91/\xe6\xb5\x8b\xe8\xaf\x95\xe4\xbe\x9d\xe8\xb5\x96\n")
    content = b"# extensions\nwin32\nwin32\\lib\npythonwin\nimport pywin32_bootstrap\n"
    _distribution(site, "pywin32", files={"pywin32.pth": content, "pywin32_bootstrap.py": b"",
        "win32/a.pyd": b"native", "win32/lib/win32con.py": b"", "pythonwin/a.pyd": b"native"})
    result = _build(package_fixture)
    assert (output / "python/Lib/site-packages/pywin32.pth").read_bytes() == content
    verify_launcher_assistant_payload(output, expected_manifest_sha256=result["manifestSha256"])


def _tokenizer_fixture(fixture, *, record_bytes=b"YQ== 0\r\nYg== 1\r\n", installed_bytes=b"YQ== 0\nYg== 1\n",
                       filename="9b5ad71b2ce5302211f9c61530b329a4922fc6a4", owner="litellm"):
    project, _, site, _ = fixture
    _write(project, "requirements.txt", (owner + "\n# 开发/测试依赖\n").encode())
    relative = "litellm/litellm_core_utils/tokenizers/" + filename
    info = _distribution(site, owner, files={relative: record_bytes})
    _write(site, relative, installed_bytes)
    return relative, site / relative, site / info / "RECORD"


@pytest.mark.parametrize("record_bytes,installed_bytes", [
    (b"YQ== 0\r\nYg== 1\r\n", b"YQ== 0\nYg== 1\n"),
    (b"YQ== 0\nYg== 1\n", b"YQ== 0\r\nYg== 1\r\n"),
])
def test_restores_only_tokenizer_newlines_that_exactly_match_record(package_fixture, record_bytes, installed_bytes):
    relative, source, _ = _tokenizer_fixture(package_fixture, record_bytes=record_bytes, installed_bytes=installed_bytes)
    result = _build(package_fixture)
    path = "python/Lib/site-packages/" + relative
    assert (package_fixture[-1] / path).read_bytes() == record_bytes
    assert source.read_bytes() == installed_bytes
    assert result["restoredFiles"] == [{"distribution": "litellm", "path": path, "reason": "record_line_endings"}]
    verify_launcher_assistant_payload(package_fixture[-1], expected_manifest_sha256=result["manifestSha256"])


@pytest.mark.parametrize("fault", ["content", "binary", "invalid_utf8", "hash", "no_hash", "size", "python_code", "owner"])
def test_tokenizer_newline_recovery_never_accepts_other_record_mismatches(package_fixture, fault):
    options = {}
    if fault == "content":
        options["installed_bytes"] = b"Yw== 0\nYg== 1\n"
    elif fault == "binary":
        options["installed_bytes"] = b"\x00YQ== 0\nYg== 1\n"
    elif fault == "invalid_utf8":
        options["installed_bytes"] = b"\xffYQ== 0\nYg== 1\n"
    elif fault == "python_code":
        options["filename"] = "tokenizer.py"
    elif fault == "owner":
        options["owner"] = "root"
    relative, source, record = _tokenizer_fixture(package_fixture, **options)
    before = source.read_bytes()
    if fault in {"hash", "no_hash", "size"}:
        rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
        for row in rows:
            if row[0] == relative:
                if fault == "size":
                    row[2] = str(int(row[2]) + 1)
                else:
                    row[1] = "" if fault == "no_hash" else "sha256=" + "A" * 43
        with record.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)
    with pytest.raises(ValueError, match="RECORD (size|hash) mismatch"):
        _build(package_fixture)
    assert source.read_bytes() == before
    assert not (package_fixture[-1] / "manifest.json").exists()


def test_build_and_verify_support_windows_extended_length_paths(package_fixture, tmp_path):
    long_output = tmp_path / ("build-" + "a" * 75) / ("snapshot-" + "b" * 75) / ("output-" + "c" * 75)
    assert len(str(long_output)) > 260
    relative = "root/proxy/_experimental/out/cost-optimization/__next.!KGRhc2hib2FyZCk.cost-optimization.__PAGE__.txt"
    _distribution(package_fixture[2], "root", files={relative: b"resource"})
    result = _build((*package_fixture[:3], long_output))
    extended = Path("\\\\?\\" + str(long_output))
    assert (extended / "python/Lib/site-packages" / relative).read_bytes() == b"resource"
    assert result["manifestPath"] == str(long_output / "manifest.json")
    assert result["sourceRoot"] == str(long_output / "source")
    assert result["pythonRoot"] == str(long_output / "python")
    manifest = verify_launcher_assistant_payload(long_output, expected_manifest_sha256=result["manifestSha256"])
    assert all(not entry["path"].startswith("\\\\?\\") for entry in manifest["files"])
    verify_launcher_assistant_payload(extended, expected_manifest_sha256=result["manifestSha256"])
    # An internal I/O namespace never turns a manifest entry into an absolute
    # path, even when the manifest's external SHA is recalculated.
    manifest["files"][0]["path"] = "\\\\?\\C:\\outside.txt"
    content = json.dumps(manifest).encode()
    (extended / "manifest.json").write_bytes(content)
    with pytest.raises(ValueError, match="relative path"):
        verify_launcher_assistant_payload(long_output, expected_manifest_sha256=hashlib.sha256(content).hexdigest())


@pytest.mark.parametrize("root", [r"\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1", r"\\.\C:\private"])
def test_rejects_nonfilesystem_device_namespaces(root):
    with pytest.raises(ValueError, match="namespace"):
        verify_launcher_assistant_payload(root)


def test_deduplicates_only_exact_record_rows_within_one_distribution(package_fixture):
    record = package_fixture[2] / "root-1.0.dist-info/RECORD"
    rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
    repeated = next(row for row in rows if row[0] == "root-1.0.dist-info/METADATA")
    with record.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(repeated)
    result = _build(package_fixture)
    assert {tuple(item.values()) for item in result["manifest"]["excludedFiles"] if item["reason"] == "duplicate_record"} == {
        ("root", "root-1.0.dist-info/METADATA", "duplicate_record")}
    verify_launcher_assistant_payload(package_fixture[-1], expected_manifest_sha256=result["manifestSha256"])


@pytest.mark.parametrize("difference", ["hash", "size", "case", "dot", "traversal", "owner"])
def test_rejects_same_owner_alias_or_nonidentical_record_rows(package_fixture, difference):
    record = package_fixture[2] / "root-1.0.dist-info/RECORD"
    rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
    repeated = next(row for row in rows if row[0] == "root-1.0.dist-info/METADATA")
    if difference == "hash":
        repeated[0] = repeated[0].replace("/", "\\")
        repeated[1] = "sha256=" + "A" * 43
    elif difference == "size":
        repeated[0] = repeated[0].replace("/", "\\")
        repeated[2] = str(int(repeated[2]) + 1)
    elif difference == "case":
        repeated[0] = repeated[0].lower()
    elif difference == "dot":
        repeated[0] = repeated[0].replace("/", "/./")
    elif difference == "traversal":
        repeated[0] = repeated[0].replace("/", "/../")
    else:
        record = package_fixture[2] / "child-1.0.dist-info/RECORD"
    with record.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(repeated)
    with pytest.raises(ValueError, match="conflict|unsafe RECORD path"):
        _build(package_fixture)


@pytest.mark.parametrize("empty_first", [False, True])
def test_merges_separator_aliases_using_strongest_constraints_in_either_order(package_fixture, empty_first):
    record = package_fixture[2] / "root-1.0.dist-info/RECORD"
    rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
    index = next(i for i, row in enumerate(rows) if row[0] == "root-1.0.dist-info/METADATA")
    row = rows[index]
    alias = [row[0].replace("/", "\\"), "", ""]
    rows.insert(index if empty_first else index + 1, alias)
    with record.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    result = _build(package_fixture)
    copied = package_fixture[-1] / "python/Lib/site-packages/root-1.0.dist-info/METADATA"
    assert base64.urlsafe_b64encode(hashlib.sha256(copied.read_bytes()).digest()).decode().rstrip("=") == row[1].split("=", 1)[1]
    assert {"distribution": "root", "path": row[0], "reason": "duplicate_record"} in result["manifest"]["excludedFiles"]
    verify_launcher_assistant_payload(package_fixture[-1], expected_manifest_sha256=result["manifestSha256"])


def test_empty_alias_cannot_bypass_original_hashed_constraint(package_fixture):
    site = package_fixture[2]
    with (site / "root-1.0.dist-info/RECORD").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(["root-1.0.dist-info\\METADATA", "", ""])
    with (site / "root-1.0.dist-info/METADATA").open("a", encoding="utf-8") as handle:
        handle.write("X-Changed: true\n")
    with pytest.raises(ValueError, match="RECORD (size|hash) mismatch"):
        _build(package_fixture)


@pytest.mark.parametrize("relative", ["../../Scripts/__pycache__/../outside.pyc", "../../Scripts/__pycache__/script.py"])
def test_script_bytecode_exclusion_does_not_allow_other_escapes(package_fixture, relative):
    with (package_fixture[2] / "root-1.0.dist-info/RECORD").open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow([relative, "", ""])
    with pytest.raises(ValueError, match="unsafe RECORD path"):
        _build(package_fixture)


def _change_during_legacy_read(monkeypatch, target, change):
    """Intercept the real verifier's open/read, never the managed wrapper."""
    from scripts.build_assistant_runtime import _io_path
    target = _io_path(target).resolve()
    original = Path.open
    observed = {"bytes": 0, "requests": [], "changed": False}
    class Reader:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def fileno(self):
            return self.handle.fileno()
        def readable(self):
            return True
        def seekable(self):
            return True
        def _change(self):
            if not observed["changed"]:
                observed["changed"] = True
                change(target, original)
        def read(self, size=-1):
            self._change()
            observed["requests"].append(size)
            value = self.handle.read(size)
            observed["bytes"] += len(value)
            return value
        def readinto(self, buffer):
            self._change()
            observed["requests"].append(len(buffer))
            size = self.handle.readinto(buffer)
            observed["bytes"] += size
            return size
    def open_file(path, *args, **kwargs):
        handle = original(path, *args, **kwargs)
        if _io_path(path).resolve() == target and args == ("rb",):
            return Reader(handle)
        return handle
    monkeypatch.setattr(Path, "open", open_file)
    return observed


def test_legacy_manifest_read_refuses_growth_after_stat(package_fixture, monkeypatch):
    _build(package_fixture)
    path = package_fixture[-1] / "manifest.json"
    initial_size = path.stat().st_size
    def grow(target, original):
        with original(target, "ab") as writer:
            writer.write(b" " * 1024)  # Still valid JSON: old read_bytes accepted it.
    observed = _change_during_legacy_read(monkeypatch, path, grow)
    with pytest.raises(ValueError):
        verify_launcher_assistant_payload(package_fixture[-1])
    assert observed["changed"]
    assert observed["bytes"] <= initial_size + 1
    assert all(0 < size <= 32 * 1024 * 1024 + 1 for size in observed["requests"])


def test_legacy_file_hash_bounds_read_even_when_file_grows(package_fixture, monkeypatch):
    _build(package_fixture)
    path = package_fixture[-1] / "source/agent.py"
    initial_size = path.stat().st_size
    def grow(target, original):
        with original(target, "ab") as writer:
            writer.write(b"extra" * 1000)
    observed = _change_during_legacy_read(monkeypatch, path, grow)
    with pytest.raises(ValueError):
        verify_launcher_assistant_payload(package_fixture[-1])
    assert observed["changed"]
    assert observed["bytes"] <= initial_size + 1


def test_legacy_file_hash_checks_mtime_after_same_bytes_read(package_fixture, monkeypatch):
    import os
    _build(package_fixture)
    path = package_fixture[-1] / "source/agent.py"
    initial = path.stat()
    def touch(target, _original):
        os.utime(target, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1_000_000_000))
    observed = _change_during_legacy_read(monkeypatch, path, touch)
    with pytest.raises(ValueError):
        verify_launcher_assistant_payload(package_fixture[-1])
    assert observed["changed"]


def test_legacy_hash_checks_opened_file_identity(package_fixture, monkeypatch):
    import os
    from scripts.build_assistant_runtime import _io_path
    _build(package_fixture)
    target = _io_path(package_fixture[-1] / "source/agent.py")
    initial = target.stat()
    content = target.read_bytes()
    original = Path.open
    changed = False
    def open_file(path, *args, **kwargs):
        nonlocal changed
        if not changed and _io_path(path) == target and args == ("rb",):
            changed = True
            replacement = target.with_name("replacement.tmp")
            with original(replacement, "xb") as writer:
                writer.write(content)
            os.utime(replacement, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            os.replace(replacement, target)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(ValueError, match="identity"):
        verify_launcher_assistant_payload(package_fixture[-1])
    assert changed


def test_ordinary_build_copy_has_the_same_growth_bound(package_fixture, monkeypatch):
    source = package_fixture[0] / "agent.py"
    initial_size = source.stat().st_size
    def grow(target, original):
        with original(target, "ab") as writer:
            writer.write(b"changed during ordinary build" * 1000)
    observed = _change_during_legacy_read(monkeypatch, source, grow)
    with pytest.raises(ValueError, match="grew|changed"):
        _build(package_fixture)
    assert observed["changed"]
    assert observed["bytes"] <= initial_size + 1
    assert not (package_fixture[-1] / "manifest.json").exists()
