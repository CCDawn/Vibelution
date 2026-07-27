"""Profile the current in-memory session query contract on synthetic summaries."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from contextlib import ExitStack, contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.web.services import session_service  # noqa: E402
from scripts import session_benchmark_isolation as isolation  # noqa: E402
from tests.session_catalog_fixtures import build_session_conversations  # noqa: E402


SCENARIOS: dict[str, dict[str, Any]] = {
    "cold_projection_empty_ledger": {"limit": 50},
    "warm_default_page": {"limit": 50},
    "filtered_text_page": {"limit": 50, "q": "needle"},
    "filtered_agent_page": {"limit": 50, "agent_id": "agent-03"},
    "filtered_state_page": {"limit": 50, "state": "running"},
    "title_sort_page": {"limit": 50, "sort": "title_asc"},
}
BENCHMARK_WARM_CACHE_TTL_SECONDS = 3600.0
BenchmarkIsolationError = isolation.BenchmarkIsolationError
DATA_ROOT_SENTINEL = isolation.DATA_ROOT_SENTINEL
initialize_benchmark_data_root = isolation.initialize_benchmark_data_root


def _dry_run_manifest(
    *,
    data_root: Path,
    sizes: list[int],
    warmups: int,
    samples: int,
    allocation_max_sessions: int,
    cold_process_threshold: int,
    cold_warmups: int,
    cold_samples: int,
    operator_snapshot: dict[str, Any],
) -> dict[str, Any]:
    manifest_body = {
        "schemaVersion": 1,
        "operation": "session_query_benchmark",
        "targetPath": str(data_root),
        "atomicApply": True,
        "sessionCountPerRun": sizes,
        "maxSessionCount": max(sizes, default=0),
        "idPatterns": {
            "session": "session-NNNNN",
            "agent": "agent-NN",
            "createdBy": [],
        },
        "warmups": warmups,
        "samples": samples,
        "allocationMaxSessions": allocation_max_sessions,
        "coldProcessThreshold": cold_process_threshold,
        "coldWarmups": cold_warmups,
        "coldSamples": cold_samples,
        "warmCacheTtlSeconds": BENCHMARK_WARM_CACHE_TTL_SECONDS,
        "expectedOperatorStateHash": isolation.canonical_sha256(operator_snapshot),
    }
    return {
        **manifest_body,
        "manifestHash": isolation.canonical_sha256(manifest_body),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


def _scenario_call(
    *,
    scenario: str,
    params: dict[str, Any],
) -> Callable[[], dict[str, Any]]:
    cold_projection = scenario == "cold_projection_empty_ledger"

    def call() -> dict[str, Any]:
        if cold_projection:
            session_service._invalidate_session_list_cache()
        return session_service.query_sessions(**params)

    return call


@contextmanager
def _isolated_legacy_service(
    project_root: Path,
    *,
    session_count: int,
    state_path: Path,
):
    signature = ("synthetic-session-query", session_count)
    agent_by_id = {
        f"agent-{index:02d}": {
            "agentId": f"agent-{index:02d}",
            "agentCode": f"A{index:03d}",
            "displayName": f"Agent {index:02d}",
            "status": "active",
            "metadata": {},
        }
        for index in range(16)
    }
    ledger_probe = {"calls": 0}

    def empty_ledger(_session_id: str) -> list[dict[str, Any]]:
        ledger_probe["calls"] += 1
        return []

    def load_synthetic_state(_project_root: Path) -> dict[str, Any]:
        return json.loads(state_path.read_text(encoding="utf-8"))

    with ExitStack() as stack:
        stack.enter_context(patch.object(session_service, "PROJECT_ROOT", project_root))
        stack.enter_context(
            patch.object(
                session_service,
                "_SESSION_LIST_CACHE_TTL_SECONDS",
                BENCHMARK_WARM_CACHE_TTL_SECONDS,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "chat_state_transaction",
                side_effect=lambda _project_root: nullcontext(),
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "load_chat_state",
                side_effect=load_synthetic_state,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_sync_agent_directory_project_root",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "save_chat_state",
                side_effect=BenchmarkIsolationError(
                    "benchmark attempted to persist chat state"
                ),
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_session_list_source_signature",
                return_value=signature,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_repair_agent_direct_session_collisions",
                return_value=False,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_agent_lookup_for_conversations",
                return_value=agent_by_id,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_agent_directory_stub_hidden_team_member_ids",
                return_value=set(),
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_ledger_visible_messages_for_session",
                side_effect=empty_ledger,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_agent_inbox_pending_count_for_summary",
                return_value=0,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_record_session_list_loaded_event",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_record_session_agent_missing_index_batch_event",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                session_service,
                "_record_session_list_query_event",
                return_value=None,
            )
        )
        session_service._invalidate_session_list_cache()
        try:
            yield ledger_probe
        finally:
            session_service._invalidate_session_list_cache()


def _measure(
    call: Callable[[], dict[str, Any]],
    *,
    warmups: int,
    samples: int,
    ledger_probe: dict[str, int],
    allocation_probe: bool,
) -> dict[str, Any]:
    for _ in range(warmups):
        call()

    ledger_probe["calls"] = 0
    durations_ms: list[float] = []
    last_payload: dict[str, Any] = {}
    for _ in range(samples):
        started_at = time.perf_counter()
        last_payload = call()
        durations_ms.append((time.perf_counter() - started_at) * 1000)
    measured_ledger_calls = int(ledger_probe["calls"])

    peak_bytes: int | None = None
    if allocation_probe:
        tracemalloc.start()
        try:
            call()
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    return {
        "p50Ms": round(statistics.median(durations_ms), 3),
        "p95Ms": round(_percentile(durations_ms, 0.95), 3),
        "meanMs": round(statistics.fmean(durations_ms), 3),
        "stdevMs": round(statistics.pstdev(durations_ms), 3),
        "minMs": round(min(durations_ms), 3),
        "maxMs": round(max(durations_ms), 3),
        "peakAllocatedBytes": peak_bytes,
        "allocationProbe": "measured" if allocation_probe else "skipped_above_limit",
        "ledgerPreviewCallsPerSample": round(
            measured_ledger_calls / samples,
            3,
        ),
        "resultCount": len(last_payload.get("items") or []),
        "matchedCount": int(last_payload.get("totalEstimate") or 0),
    }


def _run_single_cold_worker(*, data_root: Path, session_count: int) -> dict[str, Any]:
    resolved_data_root = isolation.validate_data_root(data_root)
    protected_before = isolation.operator_state_snapshot()
    try:
        conversations = build_session_conversations(session_count)
        with tempfile.TemporaryDirectory(
            prefix="vibelution-session-query-worker-",
            dir=resolved_data_root,
        ) as raw_root:
            project_root = Path(raw_root).resolve(strict=True)
            if not isolation.is_within(project_root, resolved_data_root):
                raise BenchmarkIsolationError(
                    "cold worker root escaped the explicit data root"
                )
            state_path = project_root / "chat_state.json"
            isolation.write_json_atomic(
                state_path,
                {
                    "version": 1,
                    "active_conversation_id": (
                        conversations[-1]["conversation_id"]
                        if conversations
                        else ""
                    ),
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "conversations": conversations,
                },
            )
            with _isolated_legacy_service(
                project_root,
                session_count=session_count,
                state_path=state_path,
            ) as ledger_probe:
                session_service._invalidate_session_list_cache()
                started_at = time.perf_counter()
                payload = _scenario_call(
                    scenario="cold_projection_empty_ledger",
                    params=SCENARIOS["cold_projection_empty_ledger"],
                )()
                duration_ms = (time.perf_counter() - started_at) * 1000
                return {
                    "durationMs": duration_ms,
                    "ledgerPreviewCalls": int(ledger_probe["calls"]),
                    "resultCount": len(payload.get("items") or []),
                    "matchedCount": int(payload.get("totalEstimate") or 0),
                }
    finally:
        protected_after = isolation.operator_state_snapshot()
        isolation.assert_operator_state_unchanged(protected_before, protected_after)


def _cold_worker_command(*, data_root: Path, session_count: int) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--data-root",
        str(data_root),
        "--worker-single-cold",
        "--worker-size",
        str(session_count),
    ]


def _measure_cold_in_subprocesses(
    *,
    data_root: Path,
    session_count: int,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def invoke() -> dict[str, Any]:
        completed = subprocess.run(
            _cold_worker_command(
                data_root=data_root,
                session_count=session_count,
            ),
            check=True,
            capture_output=True,
            text=True,
            creationflags=creationflags,
        )
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise BenchmarkIsolationError("cold worker returned an invalid payload")
        return payload

    for _ in range(warmups):
        invoke()
    measured = [invoke() for _ in range(samples)]
    durations_ms = [float(item["durationMs"]) for item in measured]
    return {
        "p50Ms": round(statistics.median(durations_ms), 3),
        "p95Ms": round(_percentile(durations_ms, 0.95), 3),
        "meanMs": round(statistics.fmean(durations_ms), 3),
        "stdevMs": round(statistics.pstdev(durations_ms), 3),
        "minMs": round(min(durations_ms), 3),
        "maxMs": round(max(durations_ms), 3),
        "peakAllocatedBytes": None,
        "allocationProbe": "skipped_process_isolated_cold",
        "ledgerPreviewCallsPerSample": round(
            statistics.fmean(
                int(item["ledgerPreviewCalls"]) for item in measured
            ),
            3,
        ),
        "resultCount": int(measured[-1]["resultCount"]),
        "matchedCount": int(measured[-1]["matchedCount"]),
        "processIsolation": "one_process_per_cold_sample",
        "warmups": warmups,
        "samples": samples,
    }


def run_benchmark(
    *,
    data_root: Path,
    sizes: list[int],
    warmups: int,
    samples: int,
    dry_run: bool = False,
    approved_manifest_hash: str = "",
    allocation_max_sessions: int = 1000,
    cold_process_threshold: int = 10000,
    cold_warmups: int = 1,
    cold_samples: int = 5,
) -> dict[str, Any]:
    resolved_data_root = isolation.validate_data_root(data_root)
    protected_before = isolation.operator_state_snapshot()
    manifest = _dry_run_manifest(
        data_root=resolved_data_root,
        sizes=sizes,
        warmups=warmups,
        samples=samples,
        allocation_max_sessions=allocation_max_sessions,
        cold_process_threshold=cold_process_threshold,
        cold_warmups=cold_warmups,
        cold_samples=cold_samples,
        operator_snapshot=protected_before,
    )
    if not dry_run and approved_manifest_hash != manifest["manifestHash"]:
        raise BenchmarkIsolationError(
            "normal benchmark requires the matching dry-run manifest hash"
        )
    results: list[dict[str, Any]] = []
    try:
        if not dry_run:
            for size in sizes:
                conversations = build_session_conversations(size)
                with tempfile.TemporaryDirectory(
                    prefix="vibelution-session-query-",
                    dir=resolved_data_root,
                ) as raw_root:
                    project_root = Path(raw_root).resolve(strict=True)
                    if not isolation.is_within(project_root, resolved_data_root):
                        raise BenchmarkIsolationError(
                            "generated benchmark root escaped the explicit data root"
                        )
                    if isolation.paths_overlap(
                        project_root,
                        isolation.formal_operator_workspace(),
                    ):
                        raise BenchmarkIsolationError(
                            "generated benchmark root overlaps operator storage"
                        )
                    state_path = project_root / "chat_state.json"
                    isolation.write_json_atomic(
                        state_path,
                        {
                            "version": 1,
                            "active_conversation_id": (
                                conversations[-1]["conversation_id"]
                                if conversations
                                else ""
                            ),
                            "updated_at": "2026-01-01T00:00:00+00:00",
                            "conversations": conversations,
                        },
                    )
                    with _isolated_legacy_service(
                        project_root,
                        session_count=size,
                        state_path=state_path,
                    ) as ledger_probe:
                        for scenario, params in SCENARIOS.items():
                            if (
                                scenario == "cold_projection_empty_ledger"
                                and size >= cold_process_threshold
                            ):
                                results.append(
                                    {
                                        "sessionCount": size,
                                        "scenario": scenario,
                                        **_measure_cold_in_subprocesses(
                                            data_root=resolved_data_root,
                                            session_count=size,
                                            warmups=cold_warmups,
                                            samples=cold_samples,
                                        ),
                                    }
                                )
                                continue
                            session_service._invalidate_session_list_cache()
                            if scenario != "cold_projection_empty_ledger":
                                session_service.list_sessions()
                            call = _scenario_call(
                                scenario=scenario,
                                params=params,
                            )
                            results.append(
                                {
                                    "sessionCount": size,
                                    "scenario": scenario,
                                    **_measure(
                                        call,
                                        warmups=warmups,
                                        samples=samples,
                                        ledger_probe=ledger_probe,
                                        allocation_probe=(
                                            size <= allocation_max_sessions
                                        ),
                                    ),
                                }
                            )
    finally:
        protected_after = isolation.operator_state_snapshot()
        isolation.assert_operator_state_unchanged(protected_before, protected_after)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "implementation": "legacy_python_session_query",
        "workload": "temporary_chat_state_with_counted_empty_ledger_reads",
        "dryRun": bool(dry_run),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "warmups": warmups,
        "samples": samples,
        "manifest": manifest,
        "isolation": {
            "dataRootKind": "explicit_system_temp_child",
            "lifecycleMode": "offline_in_process_no_launcher",
            "operatorStateUnchanged": True,
            "protectedBefore": protected_before,
            "protectedAfter": protected_after,
        },
        "results": results,
    }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure the current Python session query path without reading operator data."
    )
    parser.add_argument(
        "--data-root",
        required=True,
        type=Path,
        help="Existing child directory of the system temp root used for all synthetic files.",
    )
    parser.add_argument(
        "--initialize-data-root",
        action="store_true",
        help="Atomically create the required benchmark sentinel before validation.",
    )
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=_positive_int,
        default=[100, 1000, 10000],
        help="Synthetic session counts.",
    )
    parser.add_argument("--warmups", type=_positive_int, default=5)
    parser.add_argument("--samples", type=_positive_int, default=30)
    parser.add_argument(
        "--allocation-max-sessions",
        type=_positive_int,
        default=1000,
        help=(
            "Run tracemalloc only at or below this session count; "
            "latency sampling still covers every requested size."
        ),
    )
    parser.add_argument(
        "--cold-process-threshold",
        type=_positive_int,
        default=10000,
        help="Use one fresh process per cold sample at or above this size.",
    )
    parser.add_argument("--cold-warmups", type=_positive_int, default=1)
    parser.add_argument("--cold-samples", type=_positive_int, default=5)
    parser.add_argument(
        "--worker-single-cold",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--worker-size",
        type=_positive_int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate paths and protected hashes without creating synthetic files.",
    )
    parser.add_argument(
        "--approved-manifest-hash",
        default="",
        help="Exact manifestHash emitted by a preceding dry-run with identical inputs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Parent directory must already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.initialize_data_root:
        initialize_benchmark_data_root(args.data_root)
    if args.worker_single_cold:
        if args.worker_size is None:
            raise SystemExit("--worker-size is required for --worker-single-cold")
        print(
            json.dumps(
                _run_single_cold_worker(
                    data_root=args.data_root,
                    session_count=args.worker_size,
                ),
                ensure_ascii=False,
            )
        )
        return 0
    payload = run_benchmark(
        data_root=args.data_root,
        sizes=list(dict.fromkeys(args.sizes)),
        warmups=args.warmups,
        samples=args.samples,
        dry_run=args.dry_run,
        approved_manifest_hash=args.approved_manifest_hash,
        allocation_max_sessions=args.allocation_max_sessions,
        cold_process_threshold=args.cold_process_threshold,
        cold_warmups=args.cold_warmups,
        cold_samples=args.cold_samples,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        output_path = isolation.validate_output_path(
            args.output,
            data_root=args.data_root,
        )
        output_path.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
