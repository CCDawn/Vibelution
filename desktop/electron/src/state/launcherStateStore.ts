export type LauncherStateFreshness = "fresh" | "refreshing" | "stale";

export type LauncherWindowState = {
  open: boolean;
  rendererProcessId: number;
};

export type LauncherInstanceState = {
  id: string;
  kind: string;
  current: boolean;
  desiredState: string;
  observedState: string;
  phase: string;
  generation: number;
  commandId: string;
  port: number;
  pid: number;
  window: LauncherWindowState;
};

export type LauncherCleanupSummary = {
  reconciliation: {
    active: boolean;
    reason: string;
    startedAt?: string;
  };
  lastCompletedAt?: string;
  cleanedCount: number;
  skippedCount: number;
  failedCount: number;
};

export type LauncherStateSnapshotV1 = {
  schemaVersion: 1;
  revision: number;
  observedAt: string;
  freshness: LauncherStateFreshness;
  staleReason?: string;
  main: LauncherInstanceState;
  instances: LauncherInstanceState[];
  cleanup: LauncherCleanupSummary;
};

export type LauncherWindowTruth = {
  workbench: LauncherWindowState | null;
  instances: Array<LauncherWindowState & { instanceId: string }>;
};

type LauncherStateSources = {
  status: unknown;
  branchInstances: unknown;
  freshness?: unknown;
};

type LauncherStateLoader = () => Promise<LauncherStateSources>;
type LauncherStateListener = (snapshot: LauncherStateSnapshotV1) => void;

const EMPTY_CLEANUP: LauncherCleanupSummary = {
  reconciliation: { active: false, reason: "" },
  cleanedCount: 0,
  skippedCount: 0,
  failedCount: 0,
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function boolean(value: unknown): boolean {
  return value === true;
}

function mainInstance(statusValue: unknown, truth: LauncherWindowTruth): LauncherInstanceState {
  const status = record(statusValue);
  const bundle = record(status.projectBundle);
  const backend = record(bundle.backend);
  const lastOperation = record(bundle.lastOperation);
  return {
    id: text(bundle.id) || "main",
    kind: "main",
    current: true,
    desiredState: text(bundle.desiredState),
    observedState: text(bundle.observedState) || text(status.observedState),
    phase: text(bundle.phase) || text(status.phase),
    generation: number(bundle.generation),
    commandId: text(lastOperation.commandId),
    port: number(backend.port),
    pid: number(backend.pid),
    window: truth.workbench ?? { open: false, rendererProcessId: 0 },
  };
}

function branchInstance(value: unknown, truth: LauncherWindowTruth): LauncherInstanceState | null {
  const item = record(value);
  const id = text(item.id);
  if (!id) {
    return null;
  }
  const runtime = record(item.runtime);
  const backend = record(runtime.backend);
  const window = truth.instances.find((candidate) => candidate.instanceId === id);
  return {
    id,
    kind: text(item.kind) || "unknown",
    current: boolean(item.current),
    desiredState: text(runtime.desiredState) || text(item.desiredState),
    observedState: text(runtime.observedState) || text(item.observedState),
    phase: text(runtime.phase) || text(item.phase),
    generation: number(runtime.generation) || number(item.generation),
    commandId: text(runtime.commandId) || text(item.commandId),
    port: number(backend.port) || number(item.port),
    pid: number(backend.pid) || number(record(item.pids).backend),
    window: window
      ? { open: window.open, rendererProcessId: window.rendererProcessId }
      : { open: false, rendererProcessId: 0 },
  };
}

function branchItems(payload: unknown): unknown[] {
  const items = record(payload).items;
  return Array.isArray(items) ? items : [];
}

export class LauncherStateStore {
  private revision = 0;
  private freshness: LauncherStateFreshness = "stale";
  private staleReason = "initial_snapshot";
  private observedAt = new Date(0).toISOString();
  private sources: LauncherStateSources;
  private truth: LauncherWindowTruth = { workbench: null, instances: [] };
  private cleanup: LauncherCleanupSummary = EMPTY_CLEANUP;
  private readonly listeners = new Set<LauncherStateListener>();
  private refreshPromise: Promise<LauncherStateSnapshotV1> | null = null;

  constructor(
    private readonly loader: LauncherStateLoader,
    initialSources: LauncherStateSources,
  ) {
    this.sources = initialSources;
  }

  snapshot(): LauncherStateSnapshotV1 {
    const main = mainInstance(this.sources.status, this.truth);
    const instances = branchItems(this.sources.branchInstances)
      .map((item) => branchInstance(item, this.truth))
      .filter((item): item is LauncherInstanceState => item !== null && item.id !== main.id && !item.current);
    return {
      schemaVersion: 1,
      revision: this.revision,
      observedAt: this.observedAt,
      freshness: this.freshness,
      ...(this.staleReason ? { staleReason: this.staleReason } : {}),
      main,
      instances,
      cleanup: this.cleanup,
    };
  }

  projectStatus(): unknown {
    return this.sources.status;
  }

  projectBranchInstances(): unknown {
    return this.sources.branchInstances;
  }

  projectFreshness(): unknown {
    return this.sources.freshness;
  }

  subscribe(listener: LauncherStateListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  updateWindowTruth(truth: LauncherWindowTruth): LauncherStateSnapshotV1 {
    this.truth = truth;
    return this.publish();
  }

  updateCleanup(cleanup: Partial<LauncherCleanupSummary>): LauncherStateSnapshotV1 {
    this.cleanup = {
      ...this.cleanup,
      ...cleanup,
      reconciliation: cleanup.reconciliation ?? this.cleanup.reconciliation,
    };
    return this.publish();
  }

  markReconciliation(reason: string): LauncherStateSnapshotV1 {
    this.cleanup = {
      ...this.cleanup,
      reconciliation: { active: true, reason, startedAt: new Date().toISOString() },
    };
    return this.publish();
  }

  refresh(reason: string): Promise<LauncherStateSnapshotV1> {
    if (this.refreshPromise !== null) {
      return this.refreshPromise;
    }
    this.freshness = "refreshing";
    this.staleReason = "";
    this.cleanup = {
      ...this.cleanup,
      reconciliation: { active: true, reason, startedAt: new Date().toISOString() },
    };
    this.publish();
    const pending = this.loader()
      .then((sources) => {
        this.sources = sources;
        this.freshness = "fresh" as const;
        this.staleReason = "";
        this.cleanup = {
          ...this.cleanup,
          reconciliation: { active: false, reason },
        };
        return this.publish();
      })
      .catch((error: unknown) => {
        this.freshness = "stale" as const;
        this.staleReason = error instanceof Error ? error.message : String(error);
        this.cleanup = {
          ...this.cleanup,
          reconciliation: { active: false, reason },
        };
        return this.publish();
      })
      .finally(() => {
        if (this.refreshPromise === pending) {
          this.refreshPromise = null;
        }
      });
    this.refreshPromise = pending;
    return pending;
  }

  private publish(): LauncherStateSnapshotV1 {
    this.revision += 1;
    this.observedAt = new Date().toISOString();
    const snapshot = this.snapshot();
    for (const listener of this.listeners) {
      listener(snapshot);
    }
    return snapshot;
  }
}
