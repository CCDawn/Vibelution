"""Real isolated child ownership and reconnect; never contacts a model."""

from __future__ import annotations

import ast
import json
import ntpath
import os
import secrets
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

import httpx
import pytest

SOURCE = Path(__file__).resolve().parents[1]


def test_tokenizer_cache_seeds_private_lf_copy_without_mutating_package(tmp_path, monkeypatch):
    import importlib.metadata

    from scripts.assistant_host import _seed_tokenizer_cache
    bundled = tmp_path / "package"
    bundled.mkdir()
    name = "a" * 40
    original = b"a 1\r\nb 2\r\n"
    (bundled / name).write_bytes(original)
    (bundled / "not-a-cache-key").write_bytes(b"ignored")
    class Distribution:
        def locate_file(self, _path):
            return bundled
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: Distribution())
    cache = tmp_path / "profile/cache"
    _seed_tokenizer_cache(cache)
    assert (cache / name).read_bytes() == b"a 1\nb 2\n"
    assert (bundled / name).read_bytes() == original
    assert not (cache / "not-a-cache-key").exists()
    (cache / name).write_bytes(b"existing validated runtime cache")
    _seed_tokenizer_cache(cache)
    assert (cache / name).read_bytes() == b"existing validated runtime cache"


@pytest.mark.parametrize(("operating_system", "isolated"), [("nt", 0), ("posix", 0), ("posix", 1)])
def test_import_path_namespace_preserves_nonisolated_and_nonwindows_processes(monkeypatch, operating_system, isolated):
    from scripts import assistant_host

    paths = [r"C:\install\Lib", "relative", "", r"\\server\share\Lib"]
    original = list(paths)
    monkeypatch.setattr(assistant_host, "os", types.SimpleNamespace(name=operating_system))
    monkeypatch.setattr(assistant_host, "sys", types.SimpleNamespace(path=paths, flags=types.SimpleNamespace(isolated=isolated)))
    assistant_host._namespace_windows_import_paths()
    assert paths == original


def test_import_path_namespace_changes_only_absolute_windows_path_spelling(monkeypatch):
    from scripts import assistant_host

    paths = [r"C:\install\Lib", "C:/install/Lib/../source", r"\\server\share\Lib", "//server/share/Lib",
             r"\\?\C:\already\Lib", r"\\?\UNC\server\share\Lib", r"\\.\pipe\existing",
             "relative", "", r"C:relative", r"\root-relative"]
    original = list(paths)
    fake_sys = types.SimpleNamespace(path=paths, flags=types.SimpleNamespace(isolated=1))
    monkeypatch.setattr(assistant_host, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(assistant_host, "sys", fake_sys)
    assistant_host._namespace_windows_import_paths()
    assert fake_sys.path is paths and len(paths) == len(original)
    assert paths == [r"\\?\C:\install\Lib", r"\\?\C:\install\source", r"\\?\UNC\server\share\Lib",
                     r"\\?\UNC\server\share\Lib", *original[4:]]
    for before, after in zip(original[:4], paths[:4], strict=True):
        ordinary = "\\\\" + after[8:] if after.startswith("\\\\?\\UNC\\") else after[4:]
        assert ntpath.normpath(before) == ordinary
    assistant_host._namespace_windows_import_paths()
    assert fake_sys.path is paths  # Calling again never nests another namespace.
    assert paths == [r"\\?\C:\install\Lib", r"\\?\C:\install\source", r"\\?\UNC\server\share\Lib",
                     r"\\?\UNC\server\share\Lib", *original[4:]]


def test_bootstrap_namespaces_paths_before_runtime_or_sdk_imports():
    tree = ast.parse((SOURCE / "scripts/assistant_host.py").read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    call = next(node for node in main.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "_namespace_windows_import_paths")
    imports = [node.lineno for node in ast.walk(main) if
               (isinstance(node, ast.Import) and any(name.name.startswith("uvicorn") for name in node.names))
               or (isinstance(node, ast.ImportFrom) and str(node.module).startswith("core."))]
    assert imports and call.lineno < min(imports)


@pytest.mark.skipif(os.name != "nt", reason="Win32 long-path import regression")
def test_isolated_bootstrap_imports_existing_package_beyond_max_path(tmp_path):
    entry = (SOURCE / "scripts/assistant_host.py").read_text(encoding="utf-8")
    node = next(item for item in ast.parse(entry).body
                if isinstance(item, ast.FunctionDef) and item.name == "_namespace_windows_import_paths")
    helper = ast.get_source_segment(entry, node)
    site = tmp_path / ("installation-" + "a" * 40) / "Lib/site-packages"
    names = ["sdk", *("module_" + str(index) + "_" * 24 for index in range(5))]
    directory = site
    for name in names:
        directory = directory / name
        internal = Path("\\\\?\\" + os.path.abspath(directory))
        internal.mkdir(parents=True)
        (internal / "__init__.py").write_bytes(b"")
    leaf = directory / "resource.py"
    assert len(str(leaf)) > 260
    Path("\\\\?\\" + os.path.abspath(leaf)).write_bytes(b"VALUE = 17\n")
    code = ("import os, sys, ntpath, importlib, json\n" + helper +
            "\nsys.path.append(sys.argv[1])\n"
            "before = len(sys.path)\n_namespace_windows_import_paths()\n"
            "module = importlib.import_module(sys.argv[2])\n"
            "print(json.dumps({'value': module.VALUE, 'sameCount': len(sys.path) == before, "
            "'namespaced': module.__file__.startswith('\\\\\\\\?\\\\')}))\n")
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", "-c", code, str(site), ".".join([*names, "resource"])],
        stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW, check=False,
    )
    assert result.returncode == 0, result.stderr[-1000:]
    assert json.loads(result.stdout) == {"value": 17, "sameCount": True, "namespaced": True}


def _start(home, *, runtime_name="runtime"):
    runtime = home / runtime_name
    runtime.mkdir(exist_ok=True)
    config = home / "config.toml"
    config.write_text("", encoding="utf-8")
    token = secrets.token_urlsafe(48)
    instance_id = uuid.uuid4().hex
    env = {key: value for key, value in os.environ.items() if not key.startswith("VIBELUTION_")}
    env.update(VIBELUTION_ASSISTANT_TOKEN=token, VIBELUTION_CONFIG_PATH=str(config),
               VIBELUTION_PROJECTS_HOME=str(home / "projects"), PYTHONDONTWRITEBYTECODE="1")
    log = (runtime / "host.log").open("wb")
    process = subprocess.Popen([sys.executable, str(SOURCE / "scripts/assistant_host.py"),
        "--profile-root", str(home / "profile"), "--runtime-dir", str(runtime),
        "--instance-id", instance_id], cwd=SOURCE, env=env, stdout=log, stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return process, log, runtime, token, instance_id


def _connect(child):
    process, _, runtime, token, instance_id = child
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        assert process.poll() is None, "isolated host exited before readiness"
        path = runtime / "ready.json"
        if path.exists():
            ready = json.loads(path.read_text(encoding="utf-8"))
            if ready.get("instanceId") == instance_id:
                client = httpx.Client(base_url=f"http://127.0.0.1:{ready['port']}",
                    headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=5)
                try:
                    if client.get("/health").status_code == 200:
                        return client, ready
                except httpx.TransportError:
                    pass
                client.close()
        time.sleep(.1)
    raise AssertionError("isolated host did not become ready")


def _stop(child, client):
    process, log, _, _, _ = child
    try:
        if process.poll() is None:
            client.post("/api/assistant/shutdown").raise_for_status()
        process.wait(timeout=15)
        assert process.returncode == 0
    finally:
        client.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        log.close()


def test_real_host_locks_profile_and_reconnects_to_same_native_identity(tmp_path):
    first = _start(tmp_path)
    client, ready = _connect(first)
    try:
        assert ready["protocolVersion"] == 1 and ready["role"] == "launcher_assistant"
        assert first[3] not in json.dumps(ready)
        identity = client.get("/api/assistant").json()["assistant"]
        assert client.get("/api/assistant/session").json()["id"] == identity["directSessionId"]
        assert client.get("/health", headers={"Authorization": "Bearer stale-generation"}).status_code == 401
        second = _start(tmp_path, runtime_name="competing-runtime")
        try:
            assert second[0].wait(timeout=20) != 0
            assert not (second[2] / "ready.json").exists()
            assert client.get("/api/assistant").json()["assistant"]["agentId"] == identity["agentId"]
        finally:
            if second[0].poll() is None:
                second[0].terminate()
                second[0].wait(timeout=10)
            second[1].close()
        # Hold a real native SSE connection open while requesting shutdown.
        # Uvicorn must reach native drain, release the profile lock, and exit.
        with client.stream("GET", "/api/assistant/events") as stream:
            stream.raise_for_status()
            assert next(stream.iter_lines()) is not None
            started = time.monotonic()
            _stop(first, client)
            assert time.monotonic() - started < 14
    finally:
        _stop(first, client)
    assert not (first[2] / "ready.json").exists()
    resumed = _start(tmp_path)
    client, new_ready = _connect(resumed)
    try:
        assert new_ready["instanceId"] != ready["instanceId"]
        assert client.get("/health", headers={"Authorization": "Bearer " + first[3]}).status_code == 401
        current = client.get("/api/assistant").json()["assistant"]
        assert current["agentId"] == identity["agentId"]
        assert current["directSessionId"] == identity["directSessionId"]
    finally:
        _stop(resumed, client)
