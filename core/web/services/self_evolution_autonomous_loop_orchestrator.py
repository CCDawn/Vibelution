"""Production composition for asynchronous autonomous self-evolution."""

from __future__ import annotations

import threading
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
from .supervised_candidate_integration_service import integrate_candidate


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

    def reject(
        self,
        run_id: str,
        *,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        return self._service.reject(run_id, decision=decision)

    def retry_cleanup(self, run_id: str) -> dict[str, Any]:
        return self._service.retry_cleanup(run_id)

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
        candidate = context.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("candidate is required.")
        changed_files = candidate.get("changedFiles")
        if not isinstance(changed_files, list):
            raise ValueError("candidate.changedFiles is required.")
        return integrate_candidate(
            project_root=root,
            candidate_root=Path(
                str(candidate.get("worktreePath") or "")
            ),
            changed_files=changed_files,
            expected_head=str(candidate.get("baseCommit") or ""),
            expected_variant_id=str(candidate.get("variantId") or ""),
            run_id=str(context.get("runId") or ""),
            manifest_root=manifests,
        )

    def cleanup(context: dict[str, Any]) -> dict[str, Any]:
        candidate = context.get("candidate")
        integration = context.get("integration")
        if not isinstance(candidate, dict) or not isinstance(integration, dict):
            raise ValueError("candidate and integration are required for cleanup.")
        return cleanup_candidate_workspace(
            root,
            candidate,
            integration=integration,
        )

    return AutonomousLoopRuntimeDependencies(
        load_bindings=bindings_loader,
        run_role_turn=role_turn_runner,
        create_candidate=create_candidate,
        inspect_candidate=inspect_candidate,
        integrate_candidate=integrate,
        cleanup_candidate=cleanup,
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
    dependencies = build_runtime_dependencies(
        project_root=root,
        manifest_root=workspace_root / "integration_manifests",
        bindings_loader=self_evolution_control_service.self_evolution_agent_bindings,
        role_turn_runner=(
            self_evolution_control_service._run_self_evolution_agent_role_turn
        ),
    )
    service = SelfEvolutionAutonomousLoopService(
        store=WorkRunStore(root=workspace_root / "work_runs"),
        hooks=build_autonomous_loop_hooks(dependencies),
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


def retry_autonomous_self_evolution_cleanup(
    run_id: str,
) -> dict[str, Any]:
    return default_orchestrator().retry_cleanup(run_id)
