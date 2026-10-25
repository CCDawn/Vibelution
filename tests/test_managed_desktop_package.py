"""Small sealed packages; every publication stays under an explicit Temp root."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_assistant_runtime_package import package_fixture  # reuse the offline payload owner
from scripts.build_assistant_runtime import build_launcher_assistant_payload
from core.launcher import managed_desktop_package as owner


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def package(tmp_path, package_fixture):
    project, python, site, _output = package_fixture
    root = tmp_path / "build"
    payload = root / "resources/launcher-assistant"
    result = build_launcher_assistant_payload(project, payload, python_root=python,
        site_packages=site, python_version="3.12.10")
    (root / "Vibelution.exe").write_bytes(b"MZfixture")
    (root / "resources/app.asar").write_bytes(b"sealed app")
    provenance = root / "resources/app.asar.unpacked/package-provenance.json"
    provenance.parent.mkdir()
    evidence = {key: result[key] for key in ("manifestSha256",)}
    manifest = result["manifest"]
    evidence.update({key: manifest[key] for key in (
        "sourceContentSha256", "runtimeContentSha256", "requirementsSha256", "pythonVersion")})
    evidence["contentSha256"] = owner._directory_content_hash(payload)
    provenance.write_text(json.dumps({"schemaVersion": 1, "protocolVersion": 1,
        "sourceCommit": "a" * 40, "electronTreeHash": "b" * 40,
        "frontendTreeHash": "c" * 40, "frontendSourceCommit": "a" * 40,
        "frontendContentSha256": "d" * 64, "frontendBuildKey": "e" * 64,
        "mainBundleSha256": "f" * 64, "preloadBundleSha256": "a" * 64,
        "builtAt": "2026-10-25T00:00:00Z",
        "capabilities": ["desktop_actions.claim", "workbench_close.transaction.v1"],
        "assistant": evidence}), encoding="utf-8")
    return root


def test_install_is_content_addressed_idempotent_and_keeps_previous(package, tmp_path):
    root = tmp_path / "managed"
    prepared = owner.prepare_managed_desktop_package(package)
    assert prepared.active["packageId"] == _sha(prepared.catalog_bytes)
    assert not (package / owner.CATALOG_NAME).exists()
    first = owner.install_managed_desktop_package(package, managed_root=root)
    assert set(first) == {"schemaVersion", "protocolVersion", "packageId", "exeSha256", "provenanceSha256"}
    installed = root / "packages" / first["packageId"]
    assert owner.inspect_active_managed_desktop_package(managed_root=root) == first
    before = (installed / "Vibelution.exe").stat().st_mtime_ns
    assert owner.install_managed_desktop_package(package, managed_root=root) == first
    assert (installed / "Vibelution.exe").stat().st_mtime_ns == before
    (package / "Vibelution.exe").write_bytes(b"MZanother version")
    second = owner.install_managed_desktop_package(package, managed_root=root)
    assert second["packageId"] != first["packageId"]
    assert owner.inspect_managed_desktop_package(installed, expected_package_id=first["packageId"]) == first


@pytest.mark.parametrize("failure", ["copy", "verify", "replace"])
def test_failed_publication_preserves_old_pointer_and_version(package, tmp_path, monkeypatch, failure):
    root = tmp_path / "managed"
    first = owner.install_managed_desktop_package(package, managed_root=root)
    previous = (root / "active.json").read_bytes()
    (package / "Vibelution.exe").write_bytes(b"MZnext")
    if failure == "copy":
        monkeypatch.setattr(owner, "_copy_file", lambda *args: (_ for _ in ()).throw(OSError("copy blocked")))
    elif failure == "verify":
        original = owner.inspect_managed_desktop_package
        def inspect(path, **kwargs):
            if ".staging" in Path(path).parts:
                raise ValueError("staged corruption")
            return original(path, **kwargs)
        monkeypatch.setattr(owner, "inspect_managed_desktop_package", inspect)
    else:
        def fail(path, data, **kwargs):
            assert kwargs["strict_replace"] is True
            raise OSError("replace blocked")
        monkeypatch.setattr(owner, "atomic_write_json", fail)
    with pytest.raises((OSError, ValueError)):
        owner.install_managed_desktop_package(package, managed_root=root)
    assert (root / "active.json").read_bytes() == previous
    assert owner.inspect_managed_desktop_package(root / "packages" / first["packageId"]) == first


def test_source_mutation_during_copy_is_rejected(package, tmp_path, monkeypatch):
    root = tmp_path / "managed"
    first = owner.install_managed_desktop_package(package, managed_root=root)
    (package / "Vibelution.exe").write_bytes(b"MZnext")
    previous = (root / "active.json").read_bytes()
    copy = owner._copy_file
    def mutate(*args):
        copy(*args)
        p = package / "resources/app.asar"
        p.write_bytes(b"concurrent mutation")
    monkeypatch.setattr(owner, "_copy_file", mutate)
    with pytest.raises(ValueError):
        owner.install_managed_desktop_package(package, managed_root=root)
    assert (root / "active.json").read_bytes() == previous


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(extra=True),
    lambda x: x.update(schemaVersion=True),
    lambda x: x["files"][0].update(size=True),
    lambda x: x["files"][0].update(sha256="0" * 64),
    lambda x: x["files"].append(dict(x["files"][0])),
    lambda x: x["files"].append({**x["files"][0], "path": x["files"][0]["path"].upper()}),
])
def test_catalog_schema_and_integrity_are_closed(package, tmp_path, mutate):
    root = tmp_path / "managed"
    active = owner.install_managed_desktop_package(package, managed_root=root)
    installed = root / "packages" / active["packageId"]
    p = installed / owner.CATALOG_NAME
    catalog = json.loads(p.read_bytes())
    mutate(catalog)
    p.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError):
        owner.inspect_managed_desktop_package(installed)


@pytest.mark.parametrize("path", ["/bad", "../bad", "a//b", "a/./b", "a\\b", "x:ads", "CON.txt", "a/Lpt1", "a.", "a ", "a/\x01bad"])
def test_unsafe_catalog_paths_rejected(package, tmp_path, path):
    root = tmp_path / "managed"
    active = owner.install_managed_desktop_package(package, managed_root=root)
    p = root / "packages" / active["packageId"] / owner.CATALOG_NAME
    catalog = json.loads(p.read_bytes())
    catalog["files"][0]["path"] = path
    p.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError):
        owner.inspect_managed_desktop_package(p.parent)


def test_extra_files_corrupt_seal_and_existing_id_are_not_overwritten(package, tmp_path):
    root = tmp_path / "managed"
    active = owner.install_managed_desktop_package(package, managed_root=root)
    installed = root / "packages" / active["packageId"]
    (installed / "Vibelution.exe").write_bytes(b"MZcorrupted")
    with pytest.raises(ValueError):
        owner.install_managed_desktop_package(package, managed_root=root)
    assert (installed / "Vibelution.exe").read_bytes() == b"MZcorrupted"
    (package / "resources/launcher-assistant/source/agent.py").write_bytes(b"changed after seal")
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)


def test_bounds_and_duplicate_json_keys_fail_closed(package, tmp_path, monkeypatch):
    monkeypatch.setattr(owner, "MAX_FILE_BYTES", 8)
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)
    monkeypatch.undo()
    monkeypatch.setattr(owner, "MAX_TOTAL_BYTES", 20)
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)
    monkeypatch.undo()
    monkeypatch.setattr(owner, "MAX_FILES", 2)
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)
    monkeypatch.undo()
    active = owner.install_managed_desktop_package(package, managed_root=tmp_path / "m")
    p = tmp_path / "m/packages" / active["packageId"] / owner.CATALOG_NAME
    p.write_bytes(b'{"schemaVersion":1,"schemaVersion":1,"files":[]}')
    with pytest.raises(ValueError):
        owner.inspect_managed_desktop_package(p.parent)
    monkeypatch.setattr(owner, "MAX_CATALOG_BYTES", 8)
    with pytest.raises(ValueError):
        owner.inspect_managed_desktop_package(p.parent)


def test_symlinks_and_same_parent_reparse_are_refused(package, tmp_path, monkeypatch):
    link = package / "resources/redirect"
    try:
        link.symlink_to(package / "Vibelution.exe")
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)
    link.unlink()
    original = owner.os.lstat
    class Reparse:
        def __init__(self, info):
            self.__dict__.update({k: getattr(info, k) for k in dir(info) if k.startswith("st_")})
            self.st_file_attributes = 0x400
    monkeypatch.setattr(owner.os, "lstat", lambda p: Reparse(original(p)) if Path(p) == owner._io_path(package / "resources") else original(p))
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)


def test_active_pointer_is_closed(package, tmp_path):
    root = tmp_path / "managed"
    active = owner.install_managed_desktop_package(package, managed_root=root)
    for update in ({"extra": True}, {"packageId": "../elsewhere"}, {"schemaVersion": True}, {"exeSha256": "0" * 64}):
        (root / "active.json").write_text(json.dumps({**active, **update}), encoding="utf-8")
        with pytest.raises(ValueError):
            owner.inspect_active_managed_desktop_package(managed_root=root)


def test_import_and_explicit_root_never_bootstrap_config(tmp_path):
    script = """import sys\nfrom core.launcher import managed_desktop_package as m\nassert not any(k.startswith('config.') for k in sys.modules)\nassert 'core.launcher.desktop_shell' not in sys.modules\n"""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[1],
        env=env, capture_output=True, text=True, timeout=20)
    assert p.returncode == 0, p.stderr


def test_publisher_lock_serializes_processes(package, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import time
    root = tmp_path / "managed"
    root.mkdir()
    script = """import sys\nfrom pathlib import Path\nfrom core.infrastructure.file_lock import cross_process_file_lock\nwith cross_process_file_lock(Path(sys.argv[1])/'publisher',timeout=10):\n print('LOCKED',flush=True)\n sys.stdin.readline()\n"""
    child = subprocess.Popen([sys.executable, "-B", "-c", script, str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=Path(__file__).resolve().parents[1],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        assert child.stdout.readline().strip() == "LOCKED"
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(owner.install_managed_desktop_package, package, managed_root=root)
            time.sleep(.2)
            assert not pending.done()
            assert not (root / "active.json").exists()
            child.stdin.write("release\n")
            child.stdin.flush()
            active = pending.result(timeout=20)
        assert owner.inspect_active_managed_desktop_package(managed_root=root) == active
    finally:
        child.communicate("release\n", timeout=10)
        assert child.returncode == 0


def test_file_identity_change_and_additional_byte_are_rejected(package, monkeypatch):
    path = package / "Vibelution.exe"
    original_open = Path.open
    class ChangingRead:
        def __init__(self, handle):
            self.handle = handle
            self.changed = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.handle.close()
        def fileno(self):
            return self.handle.fileno()
        def read(self, count):
            data = self.handle.read(count)
            if not self.changed:
                self.changed = True
                with original_open(path, "ab") as writer:
                    writer.write(b"unexpected byte")
            return data
    def open_file(p, *args, **kwargs):
        handle = original_open(p, *args, **kwargs)
        if p == owner._io_path(path) and args == ("rb",):
            return ChangingRead(handle)
        return handle
    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(ValueError):
        owner._stream(path, limit=path.stat().st_size)


def test_bad_provenance_and_missing_required_file_are_refused(package):
    provenance = package / "resources/app.asar.unpacked/package-provenance.json"
    data = json.loads(provenance.read_bytes())
    data["assistant"]["manifestSha256"] = "0" * 64
    provenance.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)
    (package / "resources/app.asar").unlink()
    with pytest.raises(ValueError):
        owner.prepare_managed_desktop_package(package)


@pytest.mark.parametrize("changed_field", ["st_size", "st_ino", "st_mtime_ns", "st_file_attributes"])
def test_directory_enumeration_ignores_allocation_size_only(tmp_path, monkeypatch, changed_field):
    from contextlib import contextmanager
    from types import SimpleNamespace

    root = tmp_path / "stable-members"
    root.mkdir()
    (root / "member.txt").write_bytes(b"unchanged")
    target = owner._io_path(root)
    original_lstat, original_scandir = owner.os.lstat, owner.os.scandir
    enumerated = False

    def lstat(path):
        info = original_lstat(path)
        if Path(path) != target:
            return info
        values = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
        # Windows can expose its directory index allocation only after listing.
        # No file or membership change occurs during this injected observation.
        values["st_size"] = 0
        if enumerated:
            values[changed_field] = (49152 if changed_field == "st_size" else
                                     values.get(changed_field, 0) + (0x400 if changed_field == "st_file_attributes" else 1))
        return SimpleNamespace(**values)

    @contextmanager
    def scandir(path):
        nonlocal enumerated
        with original_scandir(path) as entries:
            yield entries
        if Path(path) == target:
            enumerated = True

    monkeypatch.setattr(owner.os, "lstat", lstat)
    monkeypatch.setattr(owner.os, "scandir", scandir)
    if changed_field == "st_size":
        first = owner._inventory(root)
        assert first == owner._inventory(root)
        assert set(first) == {"member.txt"}
        assert first["member.txt"][2] == len(b"unchanged")
    else:
        with pytest.raises(ValueError):
            owner._inventory(root)


@pytest.mark.parametrize("relative", [
    ".", "resources/native-runtime", "/".join(["segment-" + "x" * 32] * 5),
    "/".join(["🧪" * 32] * 5),
])
@pytest.mark.parametrize("changed_field, diagnostic_field", [
    ("st_dev", "st_dev"), ("st_ino", "st_ino"),
    ("st_mtime_ns", "st_mtime_ns"), ("st_mode", "type"),
    ("st_file_attributes", "attrs"),
])
def test_directory_change_error_is_relative_bounded_and_fail_closed(
        tmp_path, monkeypatch, relative, changed_field, diagnostic_field):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import stat

    root = tmp_path / "private-package-location"
    target = owner._io_path(root if relative == "." else root / relative)
    target.mkdir(parents=True)
    (target / "member.txt").write_bytes(b"unchanged")
    original_lstat, original_scandir = owner.os.lstat, owner.os.scandir
    enumerated = False

    def lstat(path):
        info = original_lstat(path)
        if Path(path) != target or not enumerated:
            return info
        values = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
        if changed_field == "st_mode":
            values["st_mode"] = stat.S_IFREG | stat.S_IMODE(info.st_mode)
            values["st_size"] = 0
        elif changed_field == "st_file_attributes":
            values[changed_field] = values.get(changed_field, 0) ^ 0x20
        else:
            values[changed_field] += 1
        return SimpleNamespace(**values)

    @contextmanager
    def scandir(path):
        nonlocal enumerated
        with original_scandir(path) as entries:
            yield entries
        if Path(path) == target:
            enumerated = True

    monkeypatch.setattr(owner.os, "lstat", lstat)
    monkeypatch.setattr(owner.os, "scandir", scandir)
    with pytest.raises(ValueError) as caught:
        owner._inventory(root)
    message = str(caught.value)
    assert message.startswith("Package directory changed during enumeration")
    assert message.endswith("; fields=" + diagnostic_field)
    assert str(root) not in message and root.name not in message
    assert "\\\\?\\" not in message
    assert not root.drive or root.drive + "\\" not in message
    if len(relative) <= 128:
        assert "directory=" + json.dumps(relative) in message
    else:
        assert "...\"; fields=" in message
    assert len(message) <= 2048
    assert message.isascii()
