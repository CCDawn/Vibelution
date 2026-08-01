import type { RuntimeSummary } from "../api/types";

/**
 * Runtime summary polls every few seconds. Backend heartbeats rewrite
 * lifecycleProof.verifiedAt and runtimeManager.stateVersion even when the
 * workbench UI would not change. React Query's default structural sharing
 * then treats the payload as new and re-renders AppShell (including Outlet).
 *
 * Keep the previous data reference when only those volatile fields move.
 */
export function shareRuntimeSummaryIfOnlyVolatileChanged(
  previous: unknown,
  next: unknown,
): unknown {
  if (next === undefined || next === null) {
    return previous;
  }
  if (previous === undefined || previous === null || previous === next) {
    return next;
  }
  if (
    typeof previous === "object"
    && typeof next === "object"
    && runtimeSummaryEqualIgnoringVolatile(
      previous as RuntimeSummary,
      next as RuntimeSummary,
    )
  ) {
    return previous;
  }
  return next;
}

export function runtimeSummaryEqualIgnoringVolatile(
  left: RuntimeSummary,
  right: RuntimeSummary,
): boolean {
  try {
    return serializeRuntimeSummaryWithoutVolatile(left) === serializeRuntimeSummaryWithoutVolatile(right);
  } catch {
    return false;
  }
}

function serializeRuntimeSummaryWithoutVolatile(summary: RuntimeSummary): string {
  const clone = JSON.parse(JSON.stringify(summary)) as Record<string, unknown>;
  const lifecycleProof = clone.lifecycleProof;
  if (lifecycleProof && typeof lifecycleProof === "object") {
    const proof = lifecycleProof as Record<string, unknown>;
    delete proof.verifiedAt;
    const components = proof.components;
    if (Array.isArray(components)) {
      for (const component of components) {
        if (component && typeof component === "object") {
          delete (component as Record<string, unknown>).verifiedAt;
        }
      }
    }
  }
  const runtimeManager = clone.runtimeManager;
  if (runtimeManager && typeof runtimeManager === "object") {
    delete (runtimeManager as Record<string, unknown>).stateVersion;
  }
  return JSON.stringify(clone);
}
