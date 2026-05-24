import { describe, expect, it } from "vitest";

import {
  backendSystemTone,
  deriveActiveWorkIndicator,
  deriveBackendSystemState,
  deriveFrontendSystemState,
  deriveRuntimeControllerState,
  frontendSystemTone,
  lifecycleStateLabel,
  lifecycleStateTone,
  runtimeControllerTone,
} from "./systemStatus";

const runtimeWorkbenchBase = {
  backendAlive: true,
  backendHealthy: true,
  backendObserved: true,
  backendPort: 8000,
  backendPortListening: true,
  backendPortOwnerPid: 222,
  backendPortOwnerTrusted: true,
  backendPortConflict: false,
  backendMissing: false,
  browserWindowAlive: true,
  frontendOrphaned: false,
  lifecycleConsistency: "consistent",
};

function runtimeWithActiveWork(active: {
  chat_turn?: Record<string, unknown> | null;
  self_evolution_run?: Record<string, unknown> | null;
  supervised_evolution_run?: Record<string, unknown> | null;
}, extras: Record<string, unknown> = {}) {
  return {
    workRuns: {
      active: {
        chat_turn: null,
        self_evolution_run: null,
        supervised_evolution_run: null,
        ...active,
      },
    },
    taskSummary: "",
    sessionTitle: "",
    currentPhase: "",
    ...extras,
  };
}

describe("systemStatus", () => {
  it("derives frontend state from browser visibility and connectivity", () => {
    expect(deriveFrontendSystemState({ online: true, visible: true })).toBe("connected");
    expect(deriveFrontendSystemState({ online: true, visible: false })).toBe("background");
    expect(deriveFrontendSystemState({ online: false, visible: true })).toBe("offline");
  });

  it("derives backend state from the health query snapshot", () => {
    expect(
      deriveBackendSystemState({
        isPending: true,
        hasData: false,
        isError: false,
        health: null,
      }),
    ).toBe("checking");

    expect(
      deriveBackendSystemState({
        isPending: false,
        hasData: true,
        isError: false,
        health: { status: "ok" },
      }),
    ).toBe("healthy");

    expect(
      deriveBackendSystemState({
        isPending: false,
        hasData: false,
        isError: true,
        health: null,
      }),
    ).toBe("offline");

    expect(
      deriveBackendSystemState({
        isPending: false,
        hasData: true,
        isError: false,
        health: { status: "degraded" },
      }),
    ).toBe("unhealthy");
  });

  it("derives runtime controller state from runtime manager and workbench snapshots", () => {
    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: true,
          runtimeState: "running",
          managerPid: 1001,
          stateVersion: 3,
        },
        workbench: {
          ...runtimeWorkbenchBase,
          desiredState: "open",
          observedState: "open",
          phase: "steady",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: true,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Workbench is open.",
          failureMessage: "",
        },
      }),
    ).toBe("managed");

    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: true,
          runtimeState: "running",
          managerPid: 1001,
          stateVersion: 3,
        },
        workbench: {
          ...runtimeWorkbenchBase,
          desiredState: "closed",
          observedState: "open",
          phase: "closing",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: true,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Closing workbench.",
          failureMessage: "",
        },
      }),
    ).toBe("closing");

    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: true,
          runtimeState: "running",
          managerPid: 1001,
          stateVersion: 3,
        },
        workbench: {
          ...runtimeWorkbenchBase,
          desiredState: "open",
          observedState: "open",
          phase: "failed",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: true,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Failed.",
          failureMessage: "boom",
        },
      }),
    ).toBe("failed");

    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: true,
          runtimeState: "running",
          managerPid: 1001,
          stateVersion: 3,
        },
        workbench: {
          ...runtimeWorkbenchBase,
          backendAlive: false,
          backendHealthy: false,
          backendObserved: false,
          backendPortListening: false,
          backendPortOwnerPid: 0,
          backendPortOwnerTrusted: false,
          desiredState: "closed",
          observedState: "open",
          phase: "steady",
          backendPid: 0,
          browserWindowPid: 333,
          browserManaged: true,
          backendMissing: true,
          frontendOrphaned: true,
          lifecycleConsistency: "orphaned_browser",
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Frontend is orphaned.",
          failureMessage: "",
        },
      }),
    ).toBe("failed");

    expect(
      deriveRuntimeControllerState({
        runtimeManager: {
          running: false,
          runtimeState: "idle",
          managerPid: 0,
          stateVersion: 3,
        },
        workbench: {
          ...runtimeWorkbenchBase,
          desiredState: "open",
          observedState: "open",
          phase: "steady",
          backendPid: 222,
          browserWindowPid: 333,
          browserManaged: false,
          url: "http://127.0.0.1:8000",
          lastReason: "",
          statusLine: "Workbench is open.",
          failureMessage: "",
        },
      }),
    ).toBe("unmanaged");
  });

  it("maps system states to stable visual tones", () => {
    expect(frontendSystemTone("connected")).toBe("running");
    expect(frontendSystemTone("background")).toBe("idle");
    expect(frontendSystemTone("offline")).toBe("failed");

    expect(backendSystemTone("healthy")).toBe("running");
    expect(backendSystemTone("checking")).toBe("idle");
    expect(backendSystemTone("offline")).toBe("failed");

    expect(runtimeControllerTone("managed")).toBe("running");
    expect(runtimeControllerTone("unmanaged")).toBe("idle");
    expect(runtimeControllerTone("failed")).toBe("failed");
  });

  it("maps lifecycle proof states to stable visual tones and labels", () => {
    expect(lifecycleStateTone("ready")).toBe("running");
    expect(lifecycleStateTone("running")).toBe("running");
    expect(lifecycleStateTone("closed")).toBe("idle");
    expect(lifecycleStateTone("failed")).toBe("failed");
    expect(lifecycleStateTone("partial")).toBe("caution");

    expect(lifecycleStateLabel("ready", "zh")).toBe("已开启");
    expect(lifecycleStateLabel("running", "zh")).toBe("运行中");
    expect(lifecycleStateLabel("closed", "en")).toBe("Closed");
    expect(lifecycleStateLabel("partial", "en")).toBe("Partial");
    expect(lifecycleStateLabel("custom-state", "en")).toBe("custom-state");
  });

  it("does not show an active work indicator when no active run exists", () => {
    expect(deriveActiveWorkIndicator(runtimeWithActiveWork({}))).toBeNull();
  });

  it("prioritizes supervised evolution over self-evolution and chat work", () => {
    const indicator = deriveActiveWorkIndicator(
      runtimeWithActiveWork({
        supervised_evolution_run: {
          runId: "supervised-1",
          runKind: "supervised_evolution_run",
          status: "running",
          currentTask: "review proposal safety",
        },
        self_evolution_run: {
          runId: "self-1",
          runKind: "self_evolution_run",
          status: "running",
          currentGoal: "tighten tests",
        },
        chat_turn: {
          runId: "chat-1",
          runKind: "chat_turn",
          status: "answering",
          userMessage: "继续",
        },
      }),
    );

    expect(indicator).toMatchObject({
      kind: "supervised",
      label: "监督进化",
      summary: "review proposal safety",
      status: "running",
      runId: "supervised-1",
      count: 3,
      overflowCount: 2,
      tone: "running",
    });
  });

  it("uses self-evolution goals as summaries and marks queued work as caution", () => {
    const indicator = deriveActiveWorkIndicator(
      runtimeWithActiveWork({
        self_evolution_run: {
          runId: "self-queued",
          runKind: "self_evolution_run",
          status: "queued",
          currentGoal: "improve lifecycle recovery",
        },
      }),
    );

    expect(indicator).toMatchObject({
      kind: "self",
      label: "自进化",
      summary: "improve lifecycle recovery",
      status: "queued",
      tone: "caution",
    });
  });

  it("falls back to the runtime task summary for chat work", () => {
    const indicator = deriveActiveWorkIndicator(
      runtimeWithActiveWork(
        {
          chat_turn: {
            runId: "chat-2",
            runKind: "chat_turn",
            status: "tooling",
          },
        },
        { taskSummary: "audit launcher shutdown" },
      ),
      "en",
    );

    expect(indicator).toMatchObject({
      kind: "chat",
      label: "Chat",
      summary: "audit launcher shutdown",
      status: "tooling",
    });
  });

  it("ignores terminal active work snapshots", () => {
    expect(
      deriveActiveWorkIndicator(
        runtimeWithActiveWork({
          supervised_evolution_run: {
            runId: "supervised-done",
            runKind: "supervised_evolution_run",
            status: "completed",
            currentTask: "finished already",
          },
        }),
      ),
    ).toBeNull();
  });

  it.each(["stopped", "closed", "terminated"])(
    "ignores %s active work snapshots left behind by shutdown",
    (status) => {
      expect(
        deriveActiveWorkIndicator(
          runtimeWithActiveWork({
            chat_turn: {
              runId: `chat-${status}`,
              runKind: "chat_turn",
              status,
              userMessage: "continue after shutdown",
            },
          }),
        ),
      ).toBeNull();
    },
  );
});
