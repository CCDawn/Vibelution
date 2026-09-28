"""Sandbox child-process environment: credential scrubbing and temp layout.

By default the sandboxed child does NOT inherit provider/API/token/secret/
password/credential/SSH environment entries; PATH, locale and other runtime
variables are preserved, and ``VIBELUTION_CONFIG_PATH`` points at the in-sandbox
config.  On Linux the sandbox temp directory is created with 0700 permissions
and the Windows-only ``sitecustomize.py`` shim is not installed.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from core.infrastructure.codex_sandbox.platform import host_platform
from vibelution_storage import (
    ProjectIdentityError,
    instance_id_for_project,
    resolve_active_project_storage_paths,
)


logger = logging.getLogger(__name__)

CANDIDATE_RUNTIME_ENVIRONMENT_POLICY = "candidate_runtime"
VIBELUTION_DATA_HOME_ENV = "VIBELUTION_DATA_HOME"
VIBELUTION_CONFIG_HOME_ENV = "VIBELUTION_CONFIG_HOME"
VIBELUTION_CONFIG_PATH_ENV = "VIBELUTION_CONFIG_PATH"
VIBELUTION_SANDBOX_TEMP_ENV = "VIBELUTION_CODEX_SANDBOX_TEMP"
VIBELUTION_SANDBOX_HOME_ENV = "VIBELUTION_SANDBOX_HOME"

# Composed child paths (pytest basetemp, data home, business session dirs)
# stack under the sandbox temp root. Windows rejects composed paths over
# MAX_PATH (260) with WinError 206, so the resolved root must leave room for
# those children.
SANDBOX_TEMP_PATH_BUDGET = 200

_CREDENTIAL_ENV_TOKENS = (
    "PROVIDER",
    "API",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "SSH",
)

CANDIDATE_RUNTIME_ENV_ALLOWLIST = {
    "ALLUSERSPROFILE",
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "PROCESSOR_LEVEL",
    "PROCESSOR_REVISION",
    "PROGRAMDATA",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "WINDIR",
}

_PYTHON_SITECUSTOMIZE = """\
import os
from pathlib import Path

_sandbox_temp = Path(os.environ["VIBELUTION_CODEX_SANDBOX_TEMP"]).resolve()
_original_mkdir = os.mkdir
_original_chmod = os.chmod


def _inside_sandbox_temp(path):
    try:
        return Path(path).resolve().is_relative_to(_sandbox_temp)
    except (OSError, TypeError, ValueError):
        return False


def _sandbox_mkdir(path, mode=0o777, *args, **kwargs):
    if _inside_sandbox_temp(path):
        mode = 0o777
    return _original_mkdir(path, mode, *args, **kwargs)


def _sandbox_chmod(path, mode, *args, **kwargs):
    if _inside_sandbox_temp(path):
        return None
    return _original_chmod(path, mode, *args, **kwargs)


os.mkdir = _sandbox_mkdir
os.chmod = _sandbox_chmod
"""


def _looks_like_credential(name: str) -> bool:
    upper = str(name or "").upper()
    return any(token in upper for token in _CREDENTIAL_ENV_TOKENS)


def scrub_credential_environment(environment: dict[str, str]) -> dict[str, str]:
    """Return a copy without provider/API/token/secret/password/credential/SSH entries."""
    return {
        name: value
        for name, value in environment.items()
        if not _looks_like_credential(name)
    }


def sandbox_process_environment(
    workdir: Path,
    command_hash: str,
    *,
    environment_policy: str = "default",
    platform: str | None = None,
) -> tuple[dict[str, str], Path]:
    """Build the sandbox child environment and its private temp directory."""
    system = (platform or host_platform()).lower()
    temp_root = sandbox_temp_root(workdir)
    sandbox_temp = (
        temp_root
        / f"{command_hash[:8]}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    ).resolve()
    if not sandbox_temp.is_relative_to(temp_root):
        raise RuntimeError("Codex CLI 沙盒临时目录解析异常")
    if system == "windows" and len(str(sandbox_temp)) >= SANDBOX_TEMP_PATH_BUDGET:
        logger.warning(
            "Codex CLI sandbox temp path is %d chars (budget %d); composed child "
            "paths may exceed the Windows MAX_PATH limit: %s",
            len(str(sandbox_temp)),
            SANDBOX_TEMP_PATH_BUDGET,
            sandbox_temp,
        )
    if system == "windows":
        sandbox_temp.mkdir(parents=True, exist_ok=False)
    else:
        sandbox_temp.mkdir(parents=True, exist_ok=False, mode=0o700)
    if system == "windows":
        (sandbox_temp / "sitecustomize.py").write_text(
            _PYTHON_SITECUSTOMIZE,
            encoding="utf-8",
        )
    sandbox_data_home = sandbox_temp / "vibelution-data"
    sandbox_config_home = sandbox_temp / "vibelution-config"
    sandbox_data_home.mkdir()
    sandbox_config_home.mkdir()

    if environment_policy == CANDIDATE_RUNTIME_ENVIRONMENT_POLICY:
        environment = {
            name: value
            for name, value in os.environ.items()
            if name.upper() in CANDIDATE_RUNTIME_ENV_ALLOWLIST
        }
        sandbox_user_home = sandbox_temp / "user-home"
        sandbox_appdata = sandbox_user_home / "AppData" / "Roaming"
        sandbox_localappdata = sandbox_user_home / "AppData" / "Local"
        sandbox_appdata.mkdir(parents=True)
        sandbox_localappdata.mkdir(parents=True)
        environment.update(
            {
                "APPDATA": str(sandbox_appdata),
                "HOME": str(sandbox_user_home),
                "LOCALAPPDATA": str(sandbox_localappdata),
                "USERPROFILE": str(sandbox_user_home),
                "PYTHONNOUSERSITE": "1",
            }
        )
    else:
        environment = scrub_credential_environment(os.environ)
    for name in ("TMP", "TEMP", "TMPDIR"):
        environment[name] = str(sandbox_temp)
    try:
        pytest_temp = sandbox_temp.relative_to(workdir).as_posix()
    except ValueError:
        pytest_temp = sandbox_temp.as_posix()
    pytest_options = (
        f"--basetemp={pytest_temp}/pt "
        f"-o cache_dir={pytest_temp}/ptc"
    )
    existing_pytest_options = str(environment.get("PYTEST_ADDOPTS") or "").strip()
    environment["PYTEST_ADDOPTS"] = " ".join(
        part for part in (existing_pytest_options, pytest_options) if part
    )
    existing_python_path = str(environment.get("PYTHONPATH") or "").strip()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(sandbox_temp), existing_python_path) if part
    )
    environment[VIBELUTION_SANDBOX_TEMP_ENV] = str(sandbox_temp)
    environment[VIBELUTION_DATA_HOME_ENV] = str(sandbox_data_home)
    environment[VIBELUTION_CONFIG_HOME_ENV] = str(sandbox_config_home)
    environment[VIBELUTION_CONFIG_PATH_ENV] = str(
        sandbox_config_home / "config.toml"
    )
    return environment, sandbox_temp


def sandbox_temp_root(workdir: Path) -> Path:
    """Resolve the per-run parent directory for Codex CLI sandbox temp files.

    The root stays under the project storage home so cleanup and disk
    accounting keep working, but it no longer nests under
    ``<project_id>/instances/<id>/cache``: that layout pushed composed child
    paths (pytest basetemp, data home, business session dirs) over the
    Windows MAX_PATH limit and produced ``WinError 206``. Setting
    ``VIBELUTION_SANDBOX_HOME`` overrides the base directory for constrained
    hosts; ``<instance_id>`` keeps per-project isolation in both cases.
    """

    root = Path(workdir).resolve()
    override = str(os.environ.get(VIBELUTION_SANDBOX_HOME_ENV) or "").strip()
    if override:
        base = Path(os.path.expandvars(override)).expanduser()
    else:
        try:
            base = resolve_active_project_storage_paths(root).projects_home / "sandbox"
        except ProjectIdentityError:
            return (root / ".runtime" / "codex-cli").resolve()
    return (base / instance_id_for_project(root) / "codex-cli").resolve()
