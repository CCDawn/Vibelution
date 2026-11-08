import { describe, expect, it } from "vitest";
import { launcherAssistantActivity } from "./launcherAssistantModel";

describe("Launcher pet activity", () => {
  it.each([
    ["thinking", "thinking"], ["planning", "thinking"],
    ["reading", "reading"], ["tooling", "tooling"], ["editing", "tooling"],
    ["verifying", "verifying"], ["answering", "answering"],
    ["tool", "tooling"], ["streaming", "answering"], ["checking", "verifying"],
  ])("preserves the native %s phase as %s", (currentPhase, animationState) => {
    expect(launcherAssistantActivity({ status: "running", currentPhase })).toEqual({ tone: "running", animationState });
  });

  it.each(["queued", "stopping", "force_stopping"])("shows %s as waiting rather than active thought", status => {
    expect(launcherAssistantActivity({ status, currentPhase: "reading" })).toEqual({ tone: "running", animationState: "waiting" });
  });

  it.each(["needs_continue", "paused_limit"])("keeps %s visible as waiting for the user", terminalReason => {
    expect(launcherAssistantActivity({ status: "ready", terminalReason })).toEqual({ tone: "approval", animationState: "waiting" });
  });

  it("does not turn unknown or unavailable state into idle or failure", () => {
    expect(launcherAssistantActivity({})).toEqual({ tone: "idle", animationState: "waiting" });
    expect(launcherAssistantActivity({ status: "running" }, { unavailable: true })).toEqual({ tone: "idle", animationState: "waiting" });
  });

  it("gives explicit attention precedence over ongoing work and celebration", () => {
    expect(launcherAssistantActivity({ status: "running", currentPhase: "answering" }, { needsAttention: true }))
      .toEqual({ tone: "approval", animationState: "waiting" });
    expect(launcherAssistantActivity({ status: "ready", terminalReason: "success" }, { needsAttention: true, celebrating: true }))
      .toEqual({ tone: "approval", animationState: "waiting" });
  });

  it("requires an explicit successful terminal and a current completion pulse", () => {
    expect(launcherAssistantActivity({ status: "ready" }, { celebrating: true })).toEqual({ tone: "idle", animationState: "idle" });
    expect(launcherAssistantActivity({ status: "ready", terminalReason: "success" })).toEqual({ tone: "idle", animationState: "idle" });
    expect(launcherAssistantActivity({ status: "ready", terminalReason: "success" }, { celebrating: true }))
      .toEqual({ tone: "completed", animationState: "celebrating" });
    expect(launcherAssistantActivity({ status: "running", currentPhase: "reading", terminalReason: "success" }, { celebrating: true }))
      .toEqual({ tone: "running", animationState: "reading" });
    expect(launcherAssistantActivity({ status: "ready", terminalReason: "failed_runtime" }, { celebrating: true }))
      .toEqual({ tone: "error", animationState: "alert" });
  });
});
