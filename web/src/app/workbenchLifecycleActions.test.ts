import { afterEach, describe, expect, it, vi } from "vitest";

import * as launcher from "../api/launcher";
import {
  formatActiveWorkRunsDetail,
  isActiveWorkRestartBlocked,
  isActiveWorkStopBlocked,
  parseRuntimeControlBlockedDetail,
  requestWorkbenchLifecycleOperation,
  resolveWorkbenchLifecycleTrigger,
} from "./workbenchLifecycleActions";

describe("workbenchLifecycleActions", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves surface-specific stop and force-stop triggers", () => {
    expect(resolveWorkbenchLifecycleTrigger("stop", "app_shell")).toBe("app_shell_shutdown_button");
    expect(resolveWorkbenchLifecycleTrigger("force-stop", "app_shell")).toBe("app_shell_force_shutdown_button");
    expect(resolveWorkbenchLifecycleTrigger("stop", "launcher_route")).toBe("launcher_route_stop_button");
    expect(resolveWorkbenchLifecycleTrigger("force-stop", "launcher_route")).toBe(
      "launcher_route_force_stop_button",
    );
    expect(resolveWorkbenchLifecycleTrigger("start", "launcher_route")).toBeUndefined();
    expect(resolveWorkbenchLifecycleTrigger("restart", "app_shell")).toBeUndefined();
    expect(resolveWorkbenchLifecycleTrigger("stop", "app_shell", "custom_trigger")).toBe("custom_trigger");
  });

  it("routes all lifecycle operations through one request helper", async () => {
    const start = vi.spyOn(launcher, "startLauncherBundle").mockResolvedValue({
      accepted: true,
      commandId: "c-start",
      message: "ok",
      operation: "start",
      launcherMode: "managed",
    } as never);
    const stop = vi.spyOn(launcher, "stopLauncherBundle").mockResolvedValue({
      accepted: true,
      commandId: "c-stop",
      message: "ok",
      operation: "stop",
      launcherMode: "managed",
    } as never);
    const forceStop = vi.spyOn(launcher, "forceStopLauncherBundle").mockResolvedValue({
      accepted: true,
      commandId: "c-force",
      message: "ok",
      operation: "force-stop",
      launcherMode: "managed",
    } as never);
    const restart = vi.spyOn(launcher, "restartLauncherBundle").mockResolvedValue({
      accepted: true,
      commandId: "c-restart",
      message: "ok",
      operation: "restart",
      launcherMode: "managed",
    } as never);

    await requestWorkbenchLifecycleOperation("start", { source: "launcher_route" });
    await requestWorkbenchLifecycleOperation("stop", { source: "app_shell" });
    await requestWorkbenchLifecycleOperation("force-stop", { source: "launcher_route" });
    await requestWorkbenchLifecycleOperation("restart", { source: "app_shell" });

    expect(start).toHaveBeenCalledOnce();
    expect(stop).toHaveBeenCalledWith("app_shell_shutdown_button");
    expect(forceStop).toHaveBeenCalledWith("launcher_route_force_stop_button");
    expect(restart).toHaveBeenCalledOnce();
  });

  it("parses active-work blocked details and formats run summaries", () => {
    const stopBlocked = parseRuntimeControlBlockedDetail(
      new Error(JSON.stringify({
        detail: {
          code: "active_work_stop_blocked",
          activeWorkRuns: [{ kind: "chat", status: "running", runId: "run-1" }],
        },
      })),
    );
    const restartBlocked = parseRuntimeControlBlockedDetail(
      new Error(JSON.stringify({
        detail: {
          code: "active_work_restart_blocked",
          activeWorkRuns: [{ kind: "evolution", status: "running", sessionId: "sess-9" }],
        },
      })),
    );

    expect(isActiveWorkStopBlocked(stopBlocked)).toBe(true);
    expect(isActiveWorkRestartBlocked(restartBlocked)).toBe(true);
    expect(isActiveWorkStopBlocked(restartBlocked)).toBe(false);
    expect(formatActiveWorkRunsDetail(stopBlocked?.activeWorkRuns)).toBe("chat · running · run-1");
    expect(formatActiveWorkRunsDetail(restartBlocked?.activeWorkRuns)).toBe("evolution · running · sess-9");
    expect(parseRuntimeControlBlockedDetail(new Error("not-json"))).toBeNull();
    expect(parseRuntimeControlBlockedDetail("x")).toBeNull();
  });
});
