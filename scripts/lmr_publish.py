"""LMR publish queue: push local ``main`` to ``origin`` as a publish mirror.

Design authority: ``docs/agents/pr-integration-workflow.md`` §13.3 / §14.2-5.

- Local ``main`` is the only integration authority; ``origin/main`` is a
  storage mirror. This script never forces, rebases or deletes remote state;
  the only remote mutation is ``git push origin main``.
- Trigger modes:
  * batch (default): publish when the merged-pending LMR count reaches
    ``LMR_PUBLISH_BATCH_THRESHOLD`` (default 3) OR the oldest pending record
    is at least ``LMR_PUBLISH_AGE_THRESHOLD_MINUTES`` old (default 30);
    records without a parseable timestamp count as expired (anti-starvation,
    §14.1 — waits are bounded and never silent forever).
  * ``--now``: manual immediate publish, ignoring thresholds.
  * ``--dry-run``: preview only; never pushes and never mutates records.
- Secret hygiene (fail-loud): file names added/modified in the pending range
  ``origin/main..main`` are matched against secret patterns (defaults:
  ``.env``, ``*secret*``, ``*credential*``, ``id_rsa*``, ``*.pem``,
  ``*.key``; extend with ``LMR_PUBLISH_SECRET_PATTERNS`` as comma-separated
  extras). Any hit aborts with a non-zero exit before pushing.
- Push failure: exponential backoff retries (``LMR_PUBLISH_MAX_RETRIES``,
  default 3 retries after the first attempt), then non-zero exit with the
  hint that local integration is unaffected and only the mirror lags
  (§14.2-5: publishing is decoupled from integration and never blocks it).
- LMR ledger contract (interface with the ledger owner; that component
  writes the records, this script only flips ``publishState``):
  * directory ``<git-common-dir>/lmr/`` holding one JSON object per file;
  * critical fields: ``id``, ``branch``, ``state`` (``merged`` marks a
    publish candidate), ``publishState`` (``pending_publish`` ->
    ``published``), ``headSha`` (required for the flip — verified to be an
    ancestor of ``main`` before flipping), plus ISO-8601 UTC timestamps
    (``mergedAt`` preferred for aging, falling back to ``updatedAt`` /
    ``createdAt``); unknown fields are preserved on rewrite;
  * tolerant aliases are accepted for the critical fields (``status`` ~
    ``state``, ``publish_state`` ~ ``publishState``, ``head_sha`` / ``sha``
    / ``head`` ~ ``headSha``) so either spelling integrates;
  * scans are fault tolerant: a missing directory or malformed files are
    skipped and reported, never fatal (§14.2-1: per-record files, atomic
    temp + ``os.replace`` writes, no global lock).
- No visible console: git subprocesses run through
  ``core.infrastructure.no_console_git.run_git`` (CREATE_NO_WINDOW on
  Windows). Structured results go to stdout as a single JSON object; human
  diagnostics go to stderr. Callers decide any further log sink.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.infrastructure.no_console_git import run_git

DEFAULT_SECRET_PATTERNS: tuple[str, ...] = (
    ".env",
    "*secret*",
    "*credential*",
    "id_rsa*",
    "*.pem",
    "*.key",
)

MERGED_STATE = "merged"
PUBLISH_PENDING = "pending_publish"
PUBLISH_PUBLISHED = "published"

STATE_KEYS = ("state", "status")
PUBLISH_STATE_KEYS = ("publishState", "publish_state")
HEAD_SHA_KEYS = ("headSha", "head_sha", "sha", "head")
BRANCH_KEYS = ("branch",)
ID_KEYS = ("id", "lmrId", "lmr_id")
MERGED_AT_KEYS = ("mergedAt", "merged_at")
UPDATED_AT_KEYS = ("updatedAt", "updated_at")
CREATED_AT_KEYS = ("createdAt", "created_at")

ENV_BATCH_THRESHOLD = "LMR_PUBLISH_BATCH_THRESHOLD"
ENV_AGE_THRESHOLD_MINUTES = "LMR_PUBLISH_AGE_THRESHOLD_MINUTES"
ENV_SECRET_PATTERNS = "LMR_PUBLISH_SECRET_PATTERNS"
ENV_MAX_RETRIES = "LMR_PUBLISH_MAX_RETRIES"
ENV_RETRY_BACKOFF_SECONDS = "LMR_PUBLISH_RETRY_BACKOFF_SECONDS"
ENV_PUSH_TIMEOUT_SECONDS = "LMR_PUBLISH_PUSH_TIMEOUT_SECONDS"

DEFAULT_BATCH_THRESHOLD = 3
DEFAULT_AGE_THRESHOLD_MINUTES = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_PUSH_TIMEOUT_SECONDS = 300.0

EXIT_OK = 0
EXIT_SECRETS_DETECTED = 2
EXIT_PUSH_FAILED = 3
EXIT_ERROR = 4

INTEGRATION_UNAFFECTED_HINT = "本地集成不受影响，仅镜像滞后"

_ERROR_EXIT_CODES = {
    "secrets_detected": EXIT_SECRETS_DETECTED,
    "push_failed": EXIT_PUSH_FAILED,
}


class PublishError(RuntimeError):
    """Fail-loud error carrying a machine code, optional secret hits and hint."""

    def __init__(
        self,
        code: str,
        detail: str = "",
        *,
        hits: Sequence[str] | None = None,
        hint: str | None = None,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code
        self.hits = list(hits or ())
        self.hint = hint
        self.extra = dict(extra or {})


@dataclass(frozen=True)
class PublishSettings:
    batch_threshold: int = DEFAULT_BATCH_THRESHOLD
    age_threshold_minutes: float = DEFAULT_AGE_THRESHOLD_MINUTES
    extra_secret_patterns: tuple[str, ...] = ()
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    push_timeout_seconds: float = DEFAULT_PUSH_TIMEOUT_SECONDS

    @property
    def secret_patterns(self) -> tuple[str, ...]:
        return DEFAULT_SECRET_PATTERNS + self.extra_secret_patterns


@dataclass(frozen=True)
class PendingRecord:
    path: Path
    record_id: str
    head_sha: str | None
    branch: str | None
    merged_at: datetime | None


def _env_number(
    environ: Mapping[str, str], key: str, default: float, *, minimum: float
) -> float:
    raw = environ.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError as error:
        raise PublishError(
            "bad_environment",
            detail=f"{key}={raw!r} is not a number",
        ) from error
    if value < minimum:
        raise PublishError(
            "bad_environment",
            detail=f"{key}={raw!r} is below the minimum {minimum}",
        )
    return value


def settings_from_env(environ: Mapping[str, str] | None = None) -> PublishSettings:
    env = os.environ if environ is None else environ
    extra_patterns = tuple(
        pattern.strip()
        for pattern in env.get(ENV_SECRET_PATTERNS, "").split(",")
        if pattern.strip()
    )
    return PublishSettings(
        batch_threshold=int(
            _env_number(env, ENV_BATCH_THRESHOLD, DEFAULT_BATCH_THRESHOLD, minimum=1)
        ),
        age_threshold_minutes=_env_number(
            env, ENV_AGE_THRESHOLD_MINUTES, DEFAULT_AGE_THRESHOLD_MINUTES, minimum=0.0
        ),
        extra_secret_patterns=extra_patterns,
        max_retries=int(
            _env_number(env, ENV_MAX_RETRIES, DEFAULT_MAX_RETRIES, minimum=0)
        ),
        retry_backoff_seconds=_env_number(
            env, ENV_RETRY_BACKOFF_SECONDS, DEFAULT_RETRY_BACKOFF_SECONDS, minimum=0.0
        ),
        push_timeout_seconds=_env_number(
            env, ENV_PUSH_TIMEOUT_SECONDS, DEFAULT_PUSH_TIMEOUT_SECONDS, minimum=1.0
        ),
    )


def _first_str(payload: Mapping[str, object], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def format_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _first_timestamp(payload: Mapping[str, object]) -> datetime | None:
    for keys in (MERGED_AT_KEYS, UPDATED_AT_KEYS, CREATED_AT_KEYS):
        moment = parse_utc(payload.get(keys[0]))
        if moment is not None:
            return moment
    return None


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def _git(
    repo: Path, *arguments: str, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    return run_git(list(arguments), cwd=repo, timeout=timeout)


def _git_out(repo: Path, *arguments: str, timeout: float = 30.0) -> str:
    completed = _git(repo, *arguments, timeout=timeout)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PublishError(
            "git_command_failed", detail=f"git {' '.join(arguments)}: {detail}"
        )
    return completed.stdout


def repository_root(repo_arg: Path) -> Path:
    return Path(_git_out(repo_arg, "rev-parse", "--show-toplevel").strip()).resolve()


def git_common_dir(repo: Path) -> Path:
    return Path(
        _git_out(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    )


def rev_parse(repo: Path, ref: str) -> str | None:
    completed = _git(repo, "rev-parse", "--verify", "--quiet", ref)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def load_pending_records(ledger_dir: Path) -> tuple[list[PendingRecord], list[str]]:
    """Scan the ledger for ``state=merged`` + ``publishState=pending_publish``.

    Fault tolerant: a missing directory yields no records; malformed or
    non-dict files are skipped and reported by name.
    """

    records: list[PendingRecord] = []
    malformed: list[str] = []
    if not ledger_dir.is_dir():
        return records, malformed
    for path in sorted(ledger_dir.glob("*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            malformed.append(path.name)
            continue
        if _first_str(payload, STATE_KEYS) != MERGED_STATE:
            continue
        if _first_str(payload, PUBLISH_STATE_KEYS) != PUBLISH_PENDING:
            continue
        records.append(
            PendingRecord(
                path=path,
                record_id=_first_str(payload, ID_KEYS) or path.stem,
                head_sha=_first_str(payload, HEAD_SHA_KEYS),
                branch=_first_str(payload, BRANCH_KEYS),
                merged_at=_first_timestamp(payload),
            )
        )
    return records, malformed


def changed_file_names(repo: Path, base_sha: str | None) -> list[str]:
    """Names added/modified in ``base..main`` (whole tree when base missing)."""

    if base_sha:
        completed = _git(repo, "diff", "--name-only", "-z", f"{base_sha}..refs/heads/main")
    else:
        completed = _git(repo, "ls-tree", "-r", "--name-only", "-z", "refs/heads/main")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PublishError("git_command_failed", detail=f"git diff/ls-tree: {detail}")
    return [name for name in completed.stdout.split("\0") if name]


def secret_hits(file_names: Sequence[str], patterns: Sequence[str]) -> list[str]:
    lowered_patterns = [pattern.lower() for pattern in patterns]
    hits: list[str] = []
    for name in file_names:
        normalized = name.replace("\\", "/").lower()
        basename = normalized.rsplit("/", 1)[-1]
        if any(
            fnmatch.fnmatchcase(normalized, pattern)
            or fnmatch.fnmatchcase(basename, pattern)
            for pattern in lowered_patterns
        ):
            hits.append(name)
    return sorted(hits)


def _is_ancestor(repo: Path, sha: str, tip: str) -> bool:
    completed = _git(repo, "merge-base", "--is-ancestor", sha, tip)
    return completed.returncode == 0


def evaluate_trigger(
    pending: Sequence[PendingRecord], settings: PublishSettings, *, now_mode: bool
) -> tuple[bool, str]:
    if now_mode:
        return True, "manual"
    if not pending:
        return False, "no_pending"
    if len(pending) >= settings.batch_threshold:
        return True, "batch_count"
    ages = [
        None if record.merged_at is None
        else (datetime.now(timezone.utc) - record.merged_at).total_seconds()
        for record in pending
    ]
    if any(age is None for age in ages):
        return True, "oldest_age_unknown_timestamp"
    oldest = max(age for age in ages if age is not None)
    if oldest >= settings.age_threshold_minutes * 60.0:
        return True, "oldest_age"
    return False, "below_threshold"


def push_main_with_retry(
    repo: Path, settings: PublishSettings
) -> dict[str, object]:
    """Run ``git push origin main`` with bounded exponential-backoff retries.

    Total attempts = 1 initial + ``max_retries`` retries; never force, never
    rebase, never delete remote refs.
    """

    total_attempts = settings.max_retries + 1
    last_error = ""
    for attempt in range(1, total_attempts + 1):
        completed = _git(
            repo, "push", "origin", "main", timeout=settings.push_timeout_seconds
        )
        if completed.returncode == 0:
            return {"ok": True, "attempts": attempt, "error": ""}
        last_error = (completed.stderr or completed.stdout or "").strip()
        if attempt < total_attempts and settings.retry_backoff_seconds > 0:
            time.sleep(settings.retry_backoff_seconds * (2 ** (attempt - 1)))
    return {"ok": False, "attempts": total_attempts, "error": last_error}


def mark_published(
    ledger_dir: Path,
    records: Sequence[PendingRecord],
    repo: Path,
    main_tip: str,
) -> list[str]:
    """Flip still-pending records to ``published`` (atomic, fault tolerant).

    A record is flipped only when its head SHA is verifiably an ancestor of
    the pushed ``main`` tip; re-reads are tolerated to change or vanish
    between scan and write (per-record files, no global lock, §14.2-1).
    """

    published_ids: list[str] = []
    now_iso = format_utc(datetime.now(timezone.utc))
    for record in records:
        fresh = _read_json(record.path)
        if not isinstance(fresh, dict):
            continue
        if _first_str(fresh, PUBLISH_STATE_KEYS) != PUBLISH_PENDING:
            continue
        head_sha = _first_str(fresh, HEAD_SHA_KEYS) or record.head_sha
        if not head_sha or not _is_ancestor(repo, head_sha, main_tip):
            continue
        fresh["publishState"] = PUBLISH_PUBLISHED
        fresh["publishedAt"] = now_iso
        fresh["updatedAt"] = now_iso
        try:
            _write_json_atomic(record.path, fresh)
        except OSError:
            continue
        published_ids.append(_first_str(fresh, ID_KEYS) or record.record_id)
    return published_ids


def _commit_count(repo: Path, base_sha: str | None) -> int:
    spec = (
        f"{base_sha}..refs/heads/main" if base_sha else "refs/heads/main"
    )
    output = _git_out(repo, "rev-list", "--count", spec)
    try:
        return int(output.strip() or "0")
    except ValueError as error:
        raise PublishError(
            "git_command_failed", detail=f"rev-list --count returned {output!r}"
        ) from error


def run_publish(
    repo_arg: Path,
    *,
    now_mode: bool,
    dry_run: bool,
    settings: PublishSettings,
) -> tuple[dict[str, object], int]:
    started = time.monotonic()
    repo = repository_root(repo_arg)
    ledger_dir = git_common_dir(repo) / "lmr"
    main_tip = rev_parse(repo, "refs/heads/main")
    if not main_tip:
        raise PublishError("main_missing", detail="local branch main not found")
    origin_main = rev_parse(repo, "refs/remotes/origin/main")
    pending, malformed = load_pending_records(ledger_dir)
    commit_count = _commit_count(repo, origin_main)
    hits = secret_hits(changed_file_names(repo, origin_main), settings.secret_patterns)
    proceed, trigger = evaluate_trigger(pending, settings, now_mode=now_mode)

    def base_result(action: str) -> dict[str, object]:
        return {
            "ok": True,
            "action": action,
            "trigger": trigger,
            "repo": str(repo),
            "ledgerDir": str(ledger_dir),
            "pendingCount": len(pending),
            "malformedRecordFiles": malformed,
            "rangeBase": origin_main,
            "rangeTip": main_tip,
            "commitCount": commit_count,
            "hygiene": {
                "passed": not hits,
                "patterns": list(settings.secret_patterns),
                "hits": hits,
            },
        }

    if dry_run:
        result = base_result("dry-run")
        result["wouldPush"] = bool(hits == [] and (now_mode or proceed))
        result["wouldPublishRecordIds"] = [record.record_id for record in pending]
        result["durationMs"] = int((time.monotonic() - started) * 1000)
        return result, EXIT_OK

    if not proceed:
        result = base_result("skip")
        result["reason"] = trigger
        result["durationMs"] = int((time.monotonic() - started) * 1000)
        return result, EXIT_OK

    if hits:
        raise PublishError(
            "secrets_detected",
            detail="secret-pattern hits in pending push range; refusing to push",
            hits=hits,
        )

    push_result = push_main_with_retry(repo, settings)
    if not push_result["ok"]:
        raise PublishError(
            "push_failed",
            detail=str(push_result["error"]),
            hint=INTEGRATION_UNAFFECTED_HINT,
            extra={"attempts": push_result["attempts"]},
        )

    published_ids = mark_published(ledger_dir, pending, repo, main_tip)
    result = base_result("publish")
    result["pushed"] = True
    result["push"] = {
        "attempts": push_result["attempts"],
        "remote": "origin",
        "refspec": "main",
        "forced": False,
    }
    result["publishedRecordIds"] = published_ids
    result["durationMs"] = int((time.monotonic() - started) * 1000)
    return result, EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish local main to origin (LMR publish queue)."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Repository to publish (default: current directory).",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Push immediately, ignoring batch/age thresholds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be pushed without pushing or mutating records.",
    )
    return parser


def _emit(payload: Mapping[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _emit_failure(error: PublishError) -> None:
    payload: dict[str, object] = {
        "ok": False,
        "error": error.code,
        "detail": error.detail,
        "hits": error.hits,
        "hint": error.hint,
    }
    payload.update(error.extra)
    _emit(payload)
    print(f"[lmr-publish] {error.code}: {error.detail}", file=sys.stderr)
    for hit in error.hits:
        print(f"[lmr-publish] secret hit: {hit}", file=sys.stderr)
    if error.hint:
        print(f"[lmr-publish] {error.hint}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = settings_from_env()
        result, exit_code = run_publish(
            args.repo, now_mode=args.now, dry_run=args.dry_run, settings=settings
        )
    except PublishError as error:
        _emit_failure(error)
        return _ERROR_EXIT_CODES.get(error.code, EXIT_ERROR)
    _emit(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
