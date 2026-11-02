import type { BranchLifecycleCommandOwner } from "../lifecycle/branchLifecycleCommands.js";
import { createAssistantProjectLifecycle, normalizeAssistantProjectLifecycleRequest, type AssistantProjectLifecycleOptions,
  type AssistantProjectLifecycleExecution, type AssistantProjectLifecycleResult } from "./projectLifecycle.js";
import type { ProjectAdmissionTicket } from "../lifecycle/projectAdmission.js";

/** Same permission/physical-root gate; branch writes never create a main queue. */
export function createAssistantBranchLifecycle(options: {
  getPermissionSnapshot: AssistantProjectLifecycleOptions["getPermissionSnapshot"];
  owner: BranchLifecycleCommandOwner;
  admission?: AssistantProjectLifecycleOptions["admission"];
  integrationRootFor(projectId: string): string | undefined;
}) {
  const permission = createAssistantProjectLifecycle({ getPermissionSnapshot: options.getPermissionSnapshot,
    resolveRuntimeContext: async () => null,
    readStatus: async target => {
      const current = await options.owner.resolveTarget(target.workspaceRoot, options.integrationRootFor(target.projectId));
      if (!current) throw new Error("BRANCH_INSTANCE_UNAVAILABLE");
      return { state: current.state };
    } });
  return {
    bindingFor: permission.bindingFor,
    async dispatch(input: unknown, execution: AssistantProjectLifecycleExecution = {}): Promise<AssistantProjectLifecycleResult> {
      let captured;
      try { captured = normalizeAssistantProjectLifecycleRequest(input); }
      catch { return { schemaVersion: 1, accepted: false, code: "invalid_request" }; }
      if (captured.operation === "status") return permission.dispatch(captured, execution);
      const base = { schemaVersion: 1 as const, ...captured };
      let ticket: ProjectAdmissionTicket | undefined;
      try {
        const recheckPermission = permission.capturePermission(captured.projectId);
        const binding = permission.bindingFor(captured.projectId), target = await options.owner.resolveTarget(binding.workspaceRoot, options.integrationRootFor(captured.projectId));
        if (!target) return { ...base, accepted: false, code: "prerequisite_required" };
        if (options.admission) ticket = options.admission.enter(binding.workspaceRoot);
        const check = () => {
          execution.signal?.throwIfAborted(); ticket?.check();
          recheckPermission();
          if (JSON.stringify(permission.bindingFor(captured.projectId)) !== JSON.stringify(binding)) throw new Error("BRANCH_REGISTRATION_CHANGED");
        };
        const result = await options.owner.execute({ target, operation: captured.operation, signal: execution.signal, check,
          onCommand: async command => { check(); await execution.onCommand?.(binding, command); check(); } });
        check();
        const code = result.code === "backend_retire_incomplete" ? "backend_retire_incomplete"
          : result.code === "active_work_blocked" ? "active_work_blocked" : result.accepted ? "accepted" : "rejected";
        return { ...base, accepted: result.accepted, code };
      } catch {
        return { ...base, accepted: false, code: execution.signal?.aborted ? "cancelled" : "lifecycle_failed" };
      } finally { ticket?.finish(); }
    },
  };
}
