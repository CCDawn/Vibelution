"""Production composition for asynchronous autonomous self-evolution."""

from __future__ import annotations

import threading
from dataclasses import replace
from concurrent.futures import Executor, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from core.infrastructure import developer_sandbox
from core.runtime_manager.work_run_store import WorkRunStore

from .self_evolution_autonomous_loop_runtime import (
    AutonomousLoopRuntimeDependencies,
    build_autonomous_loop_hooks,
)
from .self_evolution_autonomous_loop_service import (
    SelfEvolutionAutonomousLoopService,
)
from .self_evolution_candidate_workspace import (
    cleanup_candidate_workspace,
    create_candidate_workspace,
    inspect_candidate_workspace,
)
from .supervised_candidate_integration_service import (
    finish_candidate_integration_governance,
    integrate_candidate,
    recover_candidate_integration,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="self-evolution-autonomous-loop",
)
_ORCHESTRATOR_LOCK = threading.Lock()
_DEFAULT_ORCHESTRATOR: SelfEvolutionAutonomousLoopOrchestrator | None = None


class SelfEvolutionAutonomousLoopOrchestrator:
    """Expose non-blocking start and explicit user-decision actions."""

    def __init__(
        self,
        *,
        service: SelfEvolutionAutonomousLoopService,
        executor: Executor,
    ) -> None:
        self._service = service
        self._executor = executor
        self._recovery_lock = threading.Lock()
        self._recovery_futures: dict[str, Any] = {}

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        queued = self._service.queue(payload)
        self._executor.submit(
            self._service.run_until_review,
            str(queued["runId"]),
        )
        return queued

    def approve(
        self,
        run_id: str,
        *,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        return self._service.approve(run_id, decision=decision)

    def start_recovery(self, payload: dict, *, source: dict, run_id: str) -> dict:
        with self._recovery_lock:
            self._recovery_futures = {key: future for key, future in self._recovery_futures.items() if not future.done()}
            queued = self._service.queue_recovery(payload, source=source, run_id=run_id)
            previous = self._recovery_futures.get(run_id)
            if queued.get("status") == "queued" and (previous is None or previous.done()):
                self._recovery_futures[run_id] = self._executor.submit(self._service.run_until_review, run_id)
            return queued

    def cancel_recovery(self, run_id: str, *, source: dict) -> dict | None:
        return self._service.cancel_recovery(run_id, source=source)

    def get_recovery(self, run_id: str, *, source: dict) -> dict | None:
        return self._service.get_recovery(run_id, source=source)

    def reject(
        self,
        run_id: str,
        *,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        return self._service.reject(run_id, decision=decision)

    def revoke_local_integration(self, run_id: str) -> dict[str, Any]:
        return self._service.revoke_local_integration(run_id)

    def retry_cleanup(self, run_id: str) -> dict[str, Any]:
        return self._service.retry_cleanup(run_id)

    def interrupt_active_for_restart(self, reason: str) -> list[dict[str, Any]]:
        return self._service.interrupt_active_for_restart(reason)

    def get(self, run_id: str) -> dict[str, Any]:
        return self._service.load(run_id)

    def get_active(self) -> dict[str, Any] | None:
        return self._service.load_active()

    def get_latest(self) -> dict[str, Any] | None:
        return self._service.load_latest()


def build_runtime_dependencies(
    *,
    project_root: Path,
    manifest_root: Path,
    bindings_loader: Callable[[], dict[str, dict[str, Any]]],
    role_turn_runner: Callable[..., dict[str, Any]],
    worktree_root: Path | None = None,
    integration_guard: Callable | None = None,
    authorized_bindings_loader: Callable | None = None,
) -> AutonomousLoopRuntimeDependencies:
    """Compose Agent execution with owned worktree and exact Git integration."""

    root = Path(project_root).resolve()
    manifests = Path(manifest_root).resolve()
    candidates_root = Path(worktree_root).resolve() if worktree_root else None

    def create_candidate(context: dict[str, Any]) -> dict[str, Any]:
        return create_candidate_workspace(
            root,
            run_id=str(context.get("runId") or ""),
            worktree_root=candidates_root,
        )

    def inspect_candidate(context: dict[str, Any]) -> dict[str, Any]:
        workspace = context.get("candidateWorkspace")
        if not isinstance(workspace, dict):
            raise ValueError("candidateWorkspace is required.")
        return inspect_candidate_workspace(root, workspace)

    def integrate(context: dict[str, Any]) -> dict[str, Any]:
        delegated = bool(context.get("localIntegrationAuthorization"))
        if delegated and integration_guard is None:
            raise ValueError("Authorized integration requires a final admission guard.")
        candidate = context.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("candidate is required.")
        changed_files = candidate.get("changedFiles")
        if not isinstance(changed_files, list):
            raise ValueError("candidate.changedFiles is required.")
        arguments = dict(
            project_root=root,
            candidate_root=Path(
                str(candidate.get("worktreePath") or "")
            ),
            changed_files=changed_files,
            expected_head=str(candidate.get("baseCommit") or ""),
            expected_variant_id=str(candidate.get("variantId") or ""),
            run_id=str(context.get("runId") or ""),
            manifest_root=manifests,
            **({"expected_candidate_commit": str(candidate.get("headCommit") or ""),
                "admission_guard": lambda: integration_guard(context)}
               if delegated else {}),
        )
        try:
            return integrate_candidate(**arguments)
        except Exception:
            # The irreversible ref update may have succeeded before its response
            # was lost. Recover only a proven completion; never retry a merge here.
            recovery_arguments = {key: value for key, value in arguments.items() if key != "admission_guard"}
            try:
                recovered = recover_candidate_integration(**recovery_arguments)
            except Exception:
                recovered = None
            if recovered is not None:
                return recovered
            raise

    def cleanup(context: dict[str, Any]) -> dict[str, Any]:
        candidate = context.get("candidate")
        integration = context.get("integration")
        if not isinstance(candidate, dict) or not isinstance(integration, dict):
            raise ValueError("candidate and integration are required for cleanup.")
        if (integration.get("governanceCleanup") or {}).get("status") == "pending":
            finish_candidate_integration_governance(project_root=root,
                candidate_root=Path(str(candidate.get("worktreePath") or "")),
                changed_files=candidate.get("changedFiles") or [],
                expected_head=str(candidate.get("baseCommit") or ""),
                expected_variant_id=str(candidate.get("variantId") or ""),
                run_id=str(context.get("runId") or ""), manifest_root=manifests,
                expected_candidate_commit=str(integration.get("commitSha") or ""))
        return cleanup_candidate_workspace(
            root,
            candidate,
            integration=integration,
        )

    def recover_integration(context: dict[str, Any]) -> dict[str, Any] | None:
        candidate = context.get("candidate")
        if not isinstance(candidate, dict):
            return None
        return recover_candidate_integration(project_root=root,
            candidate_root=Path(str(candidate.get("worktreePath") or "")),
            changed_files=candidate.get("changedFiles") or [],
            expected_head=str(candidate.get("baseCommit") or ""),
            expected_variant_id=str(candidate.get("variantId") or ""),
            run_id=str(context.get("runId") or ""), manifest_root=manifests,
            expected_candidate_commit=(str(candidate.get("headCommit") or "")
                                       if context.get("localIntegrationAuthorization") else ""))

    return AutonomousLoopRuntimeDependencies(
        load_bindings=bindings_loader,
        run_role_turn=role_turn_runner,
        create_candidate=create_candidate,
        inspect_candidate=inspect_candidate,
        integrate_candidate=integrate,
        cleanup_candidate=cleanup,
        load_authorized_bindings=authorized_bindings_loader,
        recover_integration=recover_integration,
    )


def build_default_orchestrator(
    *,
    project_root: Path = PROJECT_ROOT,
    executor: Executor = _EXECUTOR,
) -> SelfEvolutionAutonomousLoopOrchestrator:
    """Build the formal Vibelution self-evolution autonomous-loop owner."""

    root = Path(project_root).resolve()
    from . import self_evolution_control_service

    workspace_root = developer_sandbox.formal_workspace_path(
        root,
        "self_evolution",
        "autonomous_loops",
    )
    from .self_evolution_local_integration import AuthorizedLocalIntegration, load_existing_bindings
    store = WorkRunStore(root=workspace_root / "work_runs")
    promotion = AuthorizedLocalIntegration(store=store, project_root=root, load_bindings=load_existing_bindings)
    dependencies = build_runtime_dependencies(
        project_root=root,
        manifest_root=workspace_root / "integration_manifests",
        bindings_loader=self_evolution_control_service.self_evolution_agent_bindings,
        authorized_bindings_loader=load_existing_bindings,
        integration_guard=promotion.guard,
        role_turn_runner=(
            self_evolution_control_service._run_self_evolution_agent_role_turn
        ),
    )
    service = SelfEvolutionAutonomousLoopService(
        store=store,
        hooks=replace(build_autonomous_loop_hooks(dependencies), authorize=promotion.authorize,
                      review=promotion.review, check_authorization=promotion.check),
    )
    service.reconcile_interrupted_on_startup()
    return SelfEvolutionAutonomousLoopOrchestrator(
        service=service,
        executor=executor,
    )


def default_orchestrator() -> SelfEvolutionAutonomousLoopOrchestrator:
    global _DEFAULT_ORCHESTRATOR
    with _ORCHESTRATOR_LOCK:
        if _DEFAULT_ORCHESTRATOR is None:
            _DEFAULT_ORCHESTRATOR = build_default_orchestrator()
        return _DEFAULT_ORCHESTRATOR


def start_autonomous_self_evolution(payload: dict[str, Any]) -> dict[str, Any]:
    return default_orchestrator().start(payload)


def interrupt_active_autonomous_self_evolution_for_restart(
    reason: str,
) -> list[dict[str, Any]]:
    return default_orchestrator().interrupt_active_for_restart(reason)


def get_autonomous_self_evolution_run(run_id: str) -> dict[str, Any]:
    return default_orchestrator().get(run_id)


def get_active_autonomous_self_evolution_run() -> dict[str, Any] | None:
    return default_orchestrator().get_active()


def get_latest_autonomous_self_evolution_run() -> dict[str, Any] | None:
    return default_orchestrator().get_latest()


def approve_autonomous_self_evolution(
    run_id: str,
    *,
    decision: dict[str, Any],
) -> dict[str, Any]:
    return default_orchestrator().approve(run_id, decision=decision)


def reject_autonomous_self_evolution(
    run_id: str,
    *,
    decision: dict[str, Any],
) -> dict[str, Any]:
    return default_orchestrator().reject(run_id, decision=decision)


def revoke_autonomous_local_integration(run_id: str) -> dict[str, Any]:
    return default_orchestrator().revoke_local_integration(run_id)


def retry_autonomous_self_evolution_cleanup(
    run_id: str,
) -> dict[str, Any]:
    return default_orchestrator().retry_cleanup(run_id)
