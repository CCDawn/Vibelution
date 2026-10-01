from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident

import pytest

from core.infrastructure import developer_sandbox


@pytest.fixture
def formal_roots(tmp_path, monkeypatch):
    first = (tmp_path / "first").resolve()
    second = (tmp_path / "second").resolve()
    roots = {first: tmp_path / "first-data", second: tmp_path / "second-data"}
    calls = []
    monkeypatch.setattr(developer_sandbox, "load_project_identity", lambda root: {})

    def resolve(root):
        calls.append(root)
        return roots[root]

    monkeypatch.setattr(developer_sandbox, "resolve_project_workspace_home", resolve)
    return first, second, roots, calls


def test_formal_snapshot_is_per_read_and_per_project(formal_roots, tmp_path):
    first, second, roots, calls = formal_roots
    old_root = roots[first]
    with developer_sandbox.snapshot_formal_workspace_paths():
        assert developer_sandbox.formal_workspace_path(first, "agents", "one") == old_root / "agents/one"
        roots[first] = tmp_path / "new-data"
        assert developer_sandbox.formal_workspace_path(first, "agents", "two") == old_root / "agents/two"
        assert developer_sandbox.formal_workspace_path(second) == roots[second]
    assert calls == [first, second]
    with developer_sandbox.snapshot_formal_workspace_paths():
        assert developer_sandbox.formal_workspace_path(first) == roots[first]
    assert calls == [first, second, first]
    developer_sandbox.formal_workspace_path(first)
    developer_sandbox.formal_workspace_path(first)
    assert calls == [first, second, first, first, first]


def test_nested_snapshot_restores_outer_even_after_failure(formal_roots, tmp_path):
    first, _, roots, calls = formal_roots
    original = roots[first]
    with developer_sandbox.snapshot_formal_workspace_paths():
        assert developer_sandbox.formal_workspace_path(first) == original
        roots[first] = tmp_path / "inner-data"
        with pytest.raises(RuntimeError), developer_sandbox.snapshot_formal_workspace_paths():
            assert developer_sandbox.formal_workspace_path(first) == roots[first]
            raise RuntimeError("read failed")
        assert developer_sandbox.formal_workspace_path(first) == original
    assert developer_sandbox.formal_workspace_path(first) == roots[first]
    assert calls == [first, first, first]


def test_concurrent_read_snapshots_do_not_share_cached_roots(formal_roots, monkeypatch, tmp_path):
    first, _, _, _ = formal_roots
    barrier = Barrier(2)
    monkeypatch.setattr(
        developer_sandbox, "resolve_project_workspace_home", lambda root: tmp_path / str(get_ident())
    )

    def read():
        with developer_sandbox.snapshot_formal_workspace_paths():
            root = developer_sandbox.formal_workspace_path(first)
            barrier.wait(timeout=5)
            assert developer_sandbox.formal_workspace_path(first) == root
            return root

    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(read)
        two = executor.submit(read)
        assert one.result() != two.result()


def test_snapshot_keeps_lazy_seeding_and_new_file_visibility(formal_roots, monkeypatch, tmp_path):
    first, _, roots, calls = formal_roots
    formal = roots[first]
    formal.mkdir()
    sandbox = tmp_path / "sandbox"
    routed_parts = []

    def sandbox_path(root, *parts):
        routed_parts.append(parts)
        return sandbox.joinpath(*parts)

    monkeypatch.setattr(developer_sandbox, "sandbox_workspace_path", sandbox_path)
    (formal / "one.txt").write_text("one", encoding="utf-8")
    with developer_sandbox.snapshot_formal_workspace_paths():
        assert developer_sandbox.seeded_sandbox_workspace_path(first, "one.txt").read_text() == "one"
        (formal / "two.txt").write_text("two", encoding="utf-8")
        assert developer_sandbox.seeded_sandbox_workspace_path(first, "two.txt").read_text() == "two"
    assert routed_parts == [("one.txt",), ("two.txt",)]
    assert calls == [first]
