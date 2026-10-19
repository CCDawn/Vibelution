function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function closedComponents(value: unknown, proof = false): unknown {
  if (!Array.isArray(value)) return value;
  return value.map((component) => {
    const item = record(component);
    return item.id === "backend" || item.id === "browser" || item.id === "workbench_window"
      ? { ...item, ok: proof, state: "stopped", pid: 0, detail: "" }
      : component;
  });
}

/** A verified backend retirement updates presentation only; it never retires a peer. */
export function projectVerifiedMainClosedStatus(value: unknown): unknown {
  const status = record(value);
  const bundle = record(status.projectBundle);
  const evidence = record(status.controlPlaneEvidence);
  const state = record(evidence.state);
  const recovery = record(evidence.recovery);
  const lifecycle = { desiredState: "closed", observedState: "closed", phase: "steady" };
  return {
    ...status,
    ...lifecycle,
    overallState: "closed",
    lifecycleConsistency: "consistent",
    failureMessage: "",
    projectBundle: {
      ...bundle,
      ...lifecycle,
      overallState: "closed",
      lifecycleConsistency: "consistent",
      statusLine: "",
      failureMessage: "",
      windowId: 0,
      rendererProcessId: 0,
      backend: {
        ...record(bundle.backend), pid: 0, alive: false, healthy: false,
        portListening: false, portOwnerPid: 0, portConflict: false,
      },
      browser: { ...record(bundle.browser), alive: false, windowPid: 0 },
      components: closedComponents(bundle.components),
    },
    lifecycleProof: {
      ...record(status.lifecycleProof),
      ...lifecycle,
      overallState: "closed",
      overallLabel: "closed",
      summary: "",
      components: closedComponents(record(status.lifecycleProof).components, true),
    },
    controlPlaneEvidence: {
      ...evidence,
      state: { ...state, activeCommand: null },
      recovery: { ...recovery, active: false },
    },
  };
}

export function projectVerifiedMainClosedBranches(value: unknown): unknown {
  const payload = record(value);
  if (!Array.isArray(payload.items)) return value;
  return {
    ...payload,
    items: payload.items.map((raw) => {
      const item = record(raw);
      if (item.current !== true) return raw;
      const runtime = record(item.runtime);
      return {
        ...item,
        alive: false,
        startable: true,
        startBlockReason: "",
        desiredState: "closed",
        observedState: "closed",
        phase: "steady",
        pids: { ...record(item.pids), backend: 0, window: 0 },
        runtime: {
          ...runtime,
          lifecycleState: "closed",
          desiredState: "closed",
          observedState: "closed",
          phase: "steady",
          registryStatus: "closed",
          error: undefined,
          backend: {
            ...record(runtime.backend), pid: 0, alive: false, healthy: false,
            listening: false, portConflict: false,
          },
          window: { ...record(runtime.window), open: false, pid: 0 },
        },
      };
    }),
  };
}

/** Keep main's newer observation while still admitting independently observed peers. */
export function retainCurrentMainBranch(previous: unknown, incoming: unknown): unknown {
  const payload = record(incoming);
  if (!Array.isArray(payload.items)) return previous;
  const current = (Array.isArray(record(previous).items) ? record(previous).items as unknown[] : [])
    .find((item) => record(item).current === true);
  const items = payload.items.filter((item) => record(item).current !== true);
  if (current !== undefined) {
    const index = payload.items.findIndex((item) => record(item).current === true);
    items.splice(index < 0 ? 0 : index, 0, current);
  }
  return { ...payload, items };
}
