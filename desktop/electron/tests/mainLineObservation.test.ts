import { describe, expect, it } from "vitest";

import { observeMainLineWorkbench } from "../src/lifecycle/mainLine/observation.js";

describe("observeMainLineWorkbench", () => {
  it("projects running when known pid is alive, TCP connect succeeds, and the window is open", async () => {
    const observation = await observeMainLineWorkbench({
      port: 8002,
      knownPids: [4242],
      windowOpen: true,
      desiredState: "open",
      frontendReady: true,
      connect: async () => true,
      pidAlive: (pid) => pid === 4242,
    });
    expect(observation).toMatchObject({
      backendAlive: true,
      backendListening: true,
      backendHealthy: true,
      livePids: [4242],
      lifecycleState: "running",
    });
  });

  it("projects closed when the known pid is dead and TCP connect fails", async () => {
    const observation = await observeMainLineWorkbench({
      port: 8002,
      knownPids: [9],
      windowOpen: false,
      desiredState: "closed",
      connect: async () => false,
      pidAlive: () => false,
    });
    expect(observation.lifecycleState).toBe("closed");
    expect(observation.backendAlive).toBe(false);
    expect(observation.backendListening).toBe(false);
    expect(observation.livePids).toEqual([]);
  });

  it("projects partial when the backend is listening but the window is closed", async () => {
    const observation = await observeMainLineWorkbench({
      port: 8002,
      knownPids: [11],
      windowOpen: false,
      desiredState: "open",
      frontendReady: true,
      connect: async () => true,
      pidAlive: () => true,
    });
    expect(observation.lifecycleState).toBe("partial");
    expect(observation.backendHealthy).toBe(true);
  });

  it("does not treat a dead pid as alive just because a port number is present", async () => {
    const observation = await observeMainLineWorkbench({
      port: 8002,
      knownPids: [0, -1],
      windowOpen: false,
      desiredState: "open",
      connect: async () => false,
      pidAlive: () => {
        throw new Error("pidAlive should not run for invalid pids");
      },
    });
    expect(observation.backendAlive).toBe(false);
    expect(observation.lifecycleState).toBe("closed");
  });
});
