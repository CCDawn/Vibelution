/**
 * In-process frontend build markers for Launcher lifecycle orchestration.
 *
 * `ensureFrontendRelease` runs synchronously inside a start/restart intent
 * before the lifecycle supervisor claims the operation, so the registry and
 * supervisor cannot report anything in flight while tsc/vite build runs.
 * These markers close that visibility gap: the orchestrator marks the
 * instance as building before awaiting the build and clears the marker in a
 * `finally`, so status/branch-instances projections can surface
 * `lifecycleState: "building"` through the same projection channel as
 * `starting` (see launcherWindowTruthOverlay + instanceLifecycleProjection).
 */

export type FrontendBuildMarker = {
  instanceId: string;
  operation: string;
  startedAt: string;
};

const markers = new Map<string, FrontendBuildMarker>();

function normalizeInstanceId(instanceId: string): string {
  return String(instanceId || "").trim();
}

export function beginFrontendBuild(instanceId: string, operation = ""): FrontendBuildMarker {
  const id = normalizeInstanceId(instanceId);
  const existing = markers.get(id);
  if (existing) {
    return existing;
  }
  const marker: FrontendBuildMarker = {
    instanceId: id,
    operation: String(operation || "").trim(),
    startedAt: new Date().toISOString()
  };
  markers.set(id, marker);
  return marker;
}

export function endFrontendBuild(instanceId: string): void {
  markers.delete(normalizeInstanceId(instanceId));
}

export function peekFrontendBuild(instanceId: string): boolean {
  return markers.has(normalizeInstanceId(instanceId));
}

export function frontendBuildMarker(instanceId: string): FrontendBuildMarker | null {
  return markers.get(normalizeInstanceId(instanceId)) ?? null;
}

export function frontendBuildInstanceIds(): string[] {
  return [...markers.keys()];
}

export function resetFrontendBuildStateForTests(): void {
  markers.clear();
}

/**
 * Marks the instance as building, notifies once before the first await (so
 * the renderer can observe `building` while the build blocks the intent),
 * and always clears the marker afterwards — including on abort or failure —
 * so the row falls back to the underlying lifecycle instead of sticking in
 * building.
 */
export async function runWithFrontendBuildGate<T>(
  instanceId: string,
  options: { operation?: string; notify?: () => void },
  run: () => Promise<T>
): Promise<T> {
  beginFrontendBuild(instanceId, options.operation);
  options.notify?.();
  try {
    return await run();
  } finally {
    endFrontendBuild(instanceId);
    options.notify?.();
  }
}
