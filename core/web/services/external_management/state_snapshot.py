"""Bounded existing-only JSON authorities shared by neutral management readers."""
from __future__ import annotations

import json
import os
from pathlib import Path

from config.public_config import read_existing_config_snapshot
from core.infrastructure import developer_sandbox
from core.infrastructure.developer_sandbox import existing_sandboxed_workspace_path


class ExistingStateSnapshot:
    def __init__(self, project_root, directory, *, pin_workspace=False):
        self.project_root = project_root
        self.directory = directory
        self._workspace_root = None
        self._workspace_token = self._routing_token() if pin_workspace else None
        self.config = read_existing_config_snapshot(Path(directory.CONFIG_PATH))
        if pin_workspace:
            self._workspace_root = existing_sandboxed_workspace_path(
                self.project_root, public_config=self.config).resolve()
            self.verify_workspace()

    @staticmethod
    def _path_token(path, *, allow_missing=False):
        path = Path(path)
        try:
            stat = path.stat()
        except FileNotFoundError:
            if allow_missing:
                return (str(path), None)
            raise
        return (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def _routing_token(self):
        config_path = Path(self.directory.CONFIG_PATH)
        return (str(config_path), self._path_token(config_path),
            developer_sandbox.workspace_routing_fingerprint(self.project_root),
            self._path_token(developer_sandbox._active_state_path(self.project_root), allow_missing=True))

    def verify_workspace(self):
        """Reject routing changes, including A -> B -> A replacements, when pinned."""
        if self._workspace_token is None:
            return
        if self._routing_token() != self._workspace_token:
            raise ValueError("Workspace authority changed")
        root = existing_sandboxed_workspace_path(self.project_root, public_config=self.config).resolve()
        if root != self._workspace_root or self._routing_token() != self._workspace_token:
            raise ValueError("Workspace authority changed")

    def path(self, *parts):
        if self._workspace_root is not None:
            target = self._workspace_root.joinpath(*parts).resolve()
            if not target.is_relative_to(self._workspace_root):
                raise ValueError("Path outside pinned workspace")
            return target
        return existing_sandboxed_workspace_path(self.project_root, *parts, public_config=self.config)

    @staticmethod
    def read_json(path, *, strict=False, max_bytes=32 * 1024 * 1024):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Ambiguous archive authority")
                result[key] = value
            return result
        before = path.stat()
        if strict and before.st_size > max_bytes:
            raise ValueError("Authority too large")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno()) if strict else None
            raw = stream.read(max_bytes + 1)
            finished = os.fstat(stream.fileno()) if strict else None
        after = path.stat()
        stamp = lambda info: (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if len(raw) > max_bytes or stamp(before) != stamp(after):
            raise ValueError("Archive authority unavailable")
        if strict:
            handle_stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if (not (handle_stamp(before) == handle_stamp(opened) == handle_stamp(finished) == handle_stamp(after))
                or opened.st_ctime_ns != finished.st_ctime_ns):
                raise ValueError("Archive authority changed")
        def reject_constant(_value):
            raise ValueError("Invalid JSON constant")
        options = {"parse_constant": reject_constant} if strict else {}
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, **options)
        if not isinstance(payload, dict):
            raise ValueError("Invalid archive authority")
        return payload
