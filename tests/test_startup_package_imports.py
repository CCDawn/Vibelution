"""Cold-process boundaries for lightweight Launcher and configuration reads."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _cold_process(source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", VIBELUTION_PORT="8000"),
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("leaf", [
    "config.paths",
    "config.workbench",
    "core.launcher.frontend_build",
    "core.launcher.desktop_shell",
    "core.llm.protocols",
    "core.llm.types",
])
def test_startup_leaf_does_not_import_execution_services(leaf: str) -> None:
    _cold_process(f"""
        import importlib, importlib.abc, sys
        blocked = {{
            'core.launcher.service', 'config.models', 'config.public_config',
            'config.settings', 'core.llm.client', 'langchain_core.messages',
        }}
        class BlockExecutionImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in blocked:
                    raise AssertionError('Execution import during startup leaf read: ' + fullname)
        sys.meta_path.insert(0, BlockExecutionImports())
        importlib.import_module({leaf!r})
        assert blocked.isdisjoint(sys.modules)
    """)


@pytest.mark.parametrize("package", ["config", "core.launcher", "core.llm"])
def test_public_exports_keep_canonical_identity_and_submodule_imports(package: str) -> None:
    _cold_process(f"""
        import importlib
        package = importlib.import_module({package!r})
        names = tuple(package.__all__)
        assert names and set(names) == set(package._EXPORTS)
        assert set(names).issubset(dir(package))
        for name in names:
            module = importlib.import_module(package._EXPORTS[name], package.__name__)
            assert getattr(package, name) is getattr(module, name), name
            assert getattr(package, name) is package.__dict__[name], name
        namespace = {{}}
        exec('from ' + package.__name__ + ' import *', namespace)
        assert all(namespace[name] is getattr(package, name) for name in names)
        try:
            getattr(package, 'missing_startup_export')
        except AttributeError:
            pass
        else:
            raise AssertionError('Missing exports must retain AttributeError')
        leaf = {{'config': 'paths', 'core.launcher': 'desktop_shell', 'core.llm': 'protocols'}}[package.__name__]
        namespace = {{}}
        exec('from ' + package.__name__ + ' import ' + leaf, namespace)
        assert namespace[leaf] is importlib.import_module(package.__name__ + '.' + leaf)
    """)
