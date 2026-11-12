"""Settle a version when ``main`` advances with a declared change.

``main`` stays read-only: the settler never commits, never rewrites ``VERSION``
and never touches ``CHANGELOG.md``. It only appends to the out-of-tree ledger and
broadcasts the new position, so an explicitly requested sync remains the only
writer of the two projection files.

Settlement is event-driven rather than calendar-driven. A ``main`` advance with
an empty ``## Unreleased`` section produces no version, which is how tests,
docs-only edits and pure refactors stay unnumbered without a policy guesser.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from core.infrastructure.no_console_git import run_git
from core.platform_version.ledger import (
    VersionLedger,
    extract_unreleased,
    read_changelog,
    snapshot,
)

logger = logging.getLogger("uvicorn.error")

DEFAULT_INTERVAL_SECONDS = 5.0
HEARTBEAT_SECONDS = 15.0
_BRANCH = "main"


def _resolve_head(project_root: Path) -> tuple[str, str] | None:
    result = run_git(["rev-parse", "--verify", f"{_BRANCH}^{{commit}}"], cwd=project_root)
    if result.returncode != 0:
        return None
    sha = (result.stdout or "").strip()
    if not sha:
        return None
    subject = run_git(["log", "-1", "--format=%s", sha], cwd=project_root)
    return sha, (subject.stdout or "").strip() if subject.returncode == 0 else ""


def _commit_count(project_root: Path) -> int:
    result = run_git(["rev-list", "--count", _BRANCH], cwd=project_root)
    if result.returncode != 0:
        return 0
    try:
        return int((result.stdout or "0").strip() or 0)
    except ValueError:
        return 0


class VersionWatcher:
    """Single-workspace watcher. One instance per project root."""

    def __init__(
        self,
        project_root: Path | str,
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        ledger_path: Path | str | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve(strict=False)
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.ledger = VersionLedger(self.project_root, ledger_path=ledger_path)
        self._task: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._tick_lock = asyncio.Lock()
        self._last_error = ""
        self._baseline_ready = False

    # -- lifecycle ---------------------------------------------------------

    def ensure_started(self) -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run(), name="platform-version-watcher")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("platform-version watcher cancelled at shutdown")
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.warning("platform-version watcher stopped with error: %s", exc)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a watcher must survive one bad tick
                self._last_error = str(exc)
                logger.warning("platform-version watcher tick failed: %s", exc)
            await asyncio.sleep(self.interval_seconds)

    # -- settlement --------------------------------------------------------

    async def tick(self) -> bool:
        """Settle at most one version. Returns ``True`` when a version settled."""

        async with self._tick_lock:
            head = await asyncio.to_thread(_resolve_head, self.project_root)
            if head is None:
                return False
            head_sha, head_subject = head
            if not self._baseline_ready:
                count = await asyncio.to_thread(_commit_count, self.project_root)
                await asyncio.to_thread(self.ledger.ensure_baseline, build_hint=count)
                self._baseline_ready = True
            unreleased = extract_unreleased(read_changelog(self.project_root))
            if unreleased is None:
                return False
            if any(entry.head_sha == head_sha for entry in self.ledger.read()):
                return False
            settled = await asyncio.to_thread(
                self.ledger.settle,
                head_sha=head_sha,
                head_subject=head_subject,
                unreleased=unreleased,
            )
            if settled is None:
                return False
            self._publish({"type": "version.settled", "entry": settled.to_json()})
            return True

    def current_snapshot(self) -> dict[str, Any]:
        payload = snapshot(self.project_root, ledger_path=self.ledger.path)
        payload["lastError"] = self._last_error
        return payload

    # -- subscriptions -----------------------------------------------------

    def _publish(self, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                continue

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        self.ensure_started()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.add(queue)
        try:
            yield {"type": "version.snapshot", "snapshot": self.current_snapshot()}
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield {"type": "version.ping"}
                    continue
                yield event
        finally:
            self._subscribers.discard(queue)


_WATCHERS: dict[str, VersionWatcher] = {}
_WATCHERS_LOCK = asyncio.Lock()


async def get_watcher(project_root: Path | str) -> VersionWatcher:
    """Return the workspace watcher, creating it inside the running loop."""

    key = str(Path(project_root).expanduser().resolve(strict=False))
    async with _WATCHERS_LOCK:
        watcher = _WATCHERS.get(key)
        if watcher is None:
            watcher = VersionWatcher(project_root)
            _WATCHERS[key] = watcher
        return watcher


def reset_watchers_for_tests() -> None:
    _WATCHERS.clear()
