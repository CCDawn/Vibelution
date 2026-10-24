"""Leaf imports must not initialize optional public package exports."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _cold(source: str, tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        env=dict(
            os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1",
            VIBELUTION_PROJECTS_HOME=str(tmp_path / "projects"),
            VIBELUTION_DATA_HOME=str(tmp_path / "data"),
            VIBELUTION_CONFIG_HOME=str(tmp_path / "config"),
        ),
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("leaf", "blocked"), [
    ("core.research.workflow.contracts.discussion_scope", (
        "core.research.workflow.contracts.workflow_snapshot",
        "core.research.workflow.contracts.anomaly_inbox",
    )),
])
def test_leaf_import_does_not_initialize_optional_exports(leaf, blocked, tmp_path):
    _cold(f"""
        import importlib, importlib.abc, sys
        blocked = set({blocked!r})
        class RejectOptionalImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in blocked:
                    raise AssertionError('Optional import during leaf load: ' + fullname)
        sys.meta_path.insert(0, RejectOptionalImports())
        importlib.import_module({leaf!r})
        assert blocked.isdisjoint(sys.modules)
    """, tmp_path)


# Captured from the pre-change explicit imports; these pin the public owners,
# including names which the old package imported but omitted from __all__.
@pytest.mark.parametrize(("package_name", "owner_digest"), [
    ("core.research.workflow.contracts", "b8297434f6854cf80f46a32f6eb3fa91995bcac3001e03bdde74962550f828b2"),
])
def test_public_exports_keep_original_owners_and_identity(package_name, owner_digest, tmp_path):
    _cold(f"""
        import hashlib, importlib, json
        package = importlib.import_module({package_name!r})
        actual = hashlib.sha256(json.dumps(package._EXPORTS, sort_keys=True).encode()).hexdigest()
        assert actual == {owner_digest!r}, 'Public export owner changed'
        assert set(package._EXPORTS).issubset(dir(package))
        assert set(package.__all__).issubset(package._EXPORTS)
        for name, owner in package._EXPORTS.items():
            module = importlib.import_module(owner, package.__name__)
            assert getattr(package, name) is getattr(module, name), name
            assert package.__dict__[name] is getattr(module, name), name
        namespace = {{}}
        exec('from ' + package.__name__ + ' import *', namespace)
        assert all(namespace[name] is getattr(package, name) for name in package.__all__)
        try:
            getattr(package, 'missing_startup_export')
        except AttributeError:
            pass
        else:
            raise AssertionError('Missing exports must raise AttributeError')
    """, tmp_path)


def test_concurrent_first_access_keeps_canonical_objects(tmp_path):
    _cold("""
        from concurrent.futures import ThreadPoolExecutor
        import importlib, threading
        names = ('ResearchBudgetLedger', 'ContractValidationError', 'ArtifactManifest', 'DiscussionScopeV1')
        package = importlib.import_module('core.research.workflow.contracts')
        barrier = threading.Barrier(len(names))
        def load(name):
            barrier.wait(timeout=10)
            return getattr(package, name)
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            values = list(pool.map(load, names, timeout=30))
        for name, value in zip(names, values):
            owner = importlib.import_module(package._EXPORTS[name], package.__name__)
            assert value is getattr(owner, name)
        from core.research.workflow.contracts import discussion_scope
        assert discussion_scope is importlib.import_module(package.__name__ + '.discussion_scope')
    """, tmp_path)
