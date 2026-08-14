export function createLocalLauncherStatusSnapshot(): Record<string, unknown> {
  return {
    launcher: {
      mode: "standalone_control_plane",
      phase: "steady",
      stableControlPlane: true,
      controlPlane: {
        independent: true,
        adapter: "electron_main",
        nextPhase: "standalone_launcher_frontend",
        url: "",
        port: 0,
        pid: 0
      },
      message: "Electron main is the Launcher control plane."
    },
    projectBundle: {
      schemaVersion: 1,
      id: "main",
      mode: "bundled",
      desiredState: "closed",
      observedState: "closed",
      phase: "steady",
      overallState: "closed",
      lifecycleConsistency: "consistent",
      statusLine: "Launcher control plane is online.",
      url: "",
      lastReason: "electron_local_snapshot",
      failureMessage: "",
      lastOperation: {
        reason: "electron_local_snapshot",
        source: "electron_main",
        transitionAt: ""
      },
      components: [
        { id: "backend", ok: false, state: "closed", requiredForRunning: true, pid: 0, detail: "" },
        { id: "frontend", ok: true, state: "bundled", requiredForRunning: true, pid: 0, detail: "" },
        { id: "browser", ok: false, state: "closed", requiredForRunning: true, pid: 0, detail: "" }
      ],
      backend: {
        pid: 0,
        alive: false,
        healthy: false,
        port: 0,
        portListening: false,
        portOwnerPid: 0,
        portConflict: false
      },
      frontend: {
        mode: "bundled_static_dist",
        distReady: true,
        orphaned: false
      },
      browser: {
        managed: true,
        windowPid: 0,
        alive: false
      }
    },
    runtimeManager: {
      running: false,
      runtimeState: "stopped",
      managerPid: 0,
      stateVersion: 0
    },
    lifecycleProof: {
      overallState: "closed",
      overallLabel: "closed",
      summary: "Launcher control plane is online; workbench is not required for this snapshot.",
      verifiedAt: "",
      desiredState: "closed",
      observedState: "closed",
      phase: "steady",
      browserManaged: true,
      projectRootMatches: true,
      components: [],
      activeWorkRuns: { count: 0, kinds: [], items: [] },
      residualProcesses: { count: 0, items: [] }
    },
    overallState: "closed",
    observedState: "closed",
    phase: "steady"
  };
}
