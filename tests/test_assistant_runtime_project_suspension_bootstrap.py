"""Launcher bootstrap retains the complete main-supplied project envelope."""

import json
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(("suspended", "aliased"), [(False, False), (True, False), (True, True)])
def test_bootstrap_installs_complete_snapshot_without_reopening_gate(tmp_path, monkeypatch, suspended, aliased):
    import uvicorn
    from core.assistant_runtime import host
    from scripts import assistant_host

    snapshot = {"schemaVersion": 1, "revision": 17,
                "projects": {"existing-id": str(tmp_path / "existing"), "missing-id": str(tmp_path / "missing")}}
    if aliased:
        target = tmp_path / "rebound-target"
        target.mkdir()
        try:
            (tmp_path / "existing").symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("Directory symlinks are unavailable on this test platform")
    else:
        (tmp_path / "existing").mkdir()
    projects_file = tmp_path / "projects.json"
    projects_file.write_text(json.dumps(snapshot), encoding="utf-8")
    captured = {}
    def create_app(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()
    class Server:
        def __init__(self, config):
            pass
        def run(self, *, sockets):
            assert len(sockets) == 1
    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(host, "create_app", create_app)
    monkeypatch.setattr(host, "NativeFacade", lambda root: SimpleNamespace(root=root))
    monkeypatch.setattr(assistant_host, "_seed_tokenizer_cache", lambda cache: None)
    monkeypatch.setenv("VIBELUTION_ASSISTANT_TOKEN", "private-test-token-that-is-long-enough")
    monkeypatch.delenv("VIBELUTION_ASSISTANT_MAIN_CONTROL", raising=False)
    monkeypatch.delenv("VIBELUTION_ASSISTANT_APPEARANCE_CONTROL", raising=False)
    monkeypatch.setattr("sys.argv", ["assistant_host.py", "--profile-root", str(tmp_path / "profile"),
        "--runtime-dir", str(tmp_path / "runtime"), "--instance-id", "local-test",
        "--projects-file", str(projects_file), *(["--projects-suspended"] if suspended else [])])
    assistant_host.main()
    dispatch = captured["dispatch"]
    assert dispatch._registry_revision == snapshot["revision"]
    assert {key: str(value) for key, value in dispatch._projects.items()} == snapshot["projects"]
    assert dispatch._projects_suspended.is_set() is suspended
    assert captured["native"].root == tmp_path / "profile"
    assert projects_file.read_text(encoding="utf-8") == json.dumps(snapshot)
