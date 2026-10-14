from pathlib import Path

import pytest

from core.agent_plugins.virtual_human_life import storage


@pytest.mark.parametrize("json_lines", [False, True])
def test_long_receipt_name_does_not_extend_the_temporary_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_lines: bool
) -> None:
    # The observed Windows instance has a 180-character commands directory:
    # its 250-character receipt fits MAX_PATH, but the old temporary name does
    # not. Emulate that limit on every platform, keeping the destination intact.
    padding = 171 - len(str(tmp_path)) - 1
    if padding < 1:
        pytest.skip("Test temp root is already longer than the observed instance")
    plugin_root = tmp_path / ("r" * padding)
    directory = plugin_root / "commands"
    assert len(str(directory)) == 180
    store = storage.VirtualHumanLifeStore(tmp_path, plugin_root_resolver=lambda _: plugin_root)
    relative = "commands/" + "a" * 64 + (".jsonl" if json_lines else ".json")
    destination = plugin_root / relative
    assert len(str(destination)) < 260
    native_mkstemp = storage.tempfile.mkstemp

    def windows_mkstemp(*args, **kwargs):
        candidate = Path(kwargs["dir"]) / (kwargs.get("prefix", "") + "12345678")
        if len(str(candidate)) >= 260:
            raise FileNotFoundError(2, "Windows MAX_PATH exceeded", str(candidate))
        return native_mkstemp(*args, **kwargs)

    monkeypatch.setattr(storage.tempfile, "mkstemp", windows_mkstemp)
    receipt = {"stateVersion": 2, "result": {"paused": True}}
    if json_lines:
        store.write_jsonl("agent-test", relative, [receipt])
        assert store.read_jsonl("agent-test", relative) == [receipt]
    else:
        store.write_json("agent-test", relative, receipt)
        assert store.read_json("agent-test", relative) == receipt
    assert list(directory.iterdir()) == [destination]
