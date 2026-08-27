"""Agent-scoped durable storage for virtual-human-life."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class VirtualHumanLifeStorageError(RuntimeError):
    """Raised when plugin storage cannot be read safely."""


class VirtualHumanLifeStore:
    def __init__(
        self,
        project_root: Path,
        *,
        plugin_root_resolver: Callable[[str], Path] | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self._plugin_root_resolver = plugin_root_resolver

    def plugin_root(self, agent_id: str) -> Path:
        normalized = self._validated_agent_id(agent_id)
        if self._plugin_root_resolver is not None:
            return Path(self._plugin_root_resolver(normalized)).resolve()
        from core.infrastructure import developer_sandbox

        return developer_sandbox.route_workspace_path(
            self.project_root,
            "agent_directory",
            "agents",
            normalized,
            "plugins",
            "virtual-human-life",
        ).resolve()

    def read_json(self, agent_id: str, relative_path: str) -> dict[str, Any] | None:
        path = self._path(agent_id, relative_path)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VirtualHumanLifeStorageError(
                f"Virtual human storage is corrupt: {path.name}"
            ) from exc
        if not isinstance(payload, dict):
            raise VirtualHumanLifeStorageError(
                f"Virtual human storage must contain an object: {path.name}"
            )
        return payload

    def write_json(self, agent_id: str, relative_path: str, payload: dict[str, Any]) -> Path:
        path = self._path(agent_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass
        return path

    def read_jsonl(self, agent_id: str, relative_path: str) -> list[dict[str, Any]]:
        path = self._path(agent_id, relative_path)
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line)
                if isinstance(payload, dict):
                    rows.append(payload)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VirtualHumanLifeStorageError(
                f"Virtual human ledger is corrupt: {path.name}"
            ) from exc
        return rows

    def append_jsonl(self, agent_id: str, relative_path: str, payload: dict[str, Any]) -> Path:
        rows = self.read_jsonl(agent_id, relative_path)
        rows.append(dict(payload))
        return self.write_jsonl(agent_id, relative_path, rows)

    def write_jsonl(
        self,
        agent_id: str,
        relative_path: str,
        rows: list[dict[str, Any]],
    ) -> Path:
        path = self._path(agent_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass
        return path

    def _path(self, agent_id: str, relative_path: str) -> Path:
        root = self.plugin_root(agent_id)
        relative = Path(str(relative_path or "").replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise VirtualHumanLifeStorageError("Plugin storage path must stay inside the Agent plugin root.")
        resolved = root.joinpath(relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise VirtualHumanLifeStorageError(
                "Plugin storage path must stay inside the Agent plugin root."
            ) from exc
        return resolved

    @staticmethod
    def _validated_agent_id(agent_id: str) -> str:
        normalized = str(agent_id or "").strip()
        if not _AGENT_ID_PATTERN.fullmatch(normalized):
            raise VirtualHumanLifeStorageError("Invalid Agent id for plugin storage.")
        return normalized
