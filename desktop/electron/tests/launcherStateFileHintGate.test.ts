import { describe, expect, it, vi } from "vitest";

import {
  LAUNCHER_STATE_NULL_EVENT_QUIET_MS,
  createLauncherStateFileHintGate,
  createLauncherStateHintBackoff,
} from "../src/state/launcherStateFileHintGate.js";

function makeGate(signatures: Map<string, string>, options?: { now?: () => number; quietMs?: number }) {
  return createLauncherStateFileHintGate({
    observedPaths: ["C:/runtime/launcher/state.json", "C:/runtime/launcher/ports.json"],
    statSignature: (path) => signatures.get(path) ?? "missing",
    ...options,
  });
}

describe("launcherStateFileHintGate", () => {
  it("ignores null-filename events when no observed state/port signature changed", () => {
    const signatures = new Map<string, string>([["C:/runtime/launcher/state.json", "1:10"]]);
    const gate = makeGate(signatures);
    // Log churn elsewhere in the directory changes nothing the gate observes.
    expect(gate.consumeNullFilenameEvent()).toBe(false);
    expect(gate.consumeNullFilenameEvent()).toBe(false);
    signatures.set("C:/runtime/launcher/ports.json", "2:20");
    expect(gate.consumeNullFilenameEvent()).toBe(true);
  });

  it("consumes a signature change once so it cannot resurface from the stat poll", () => {
    const signatures = new Map<string, string>();
    const gate = makeGate(signatures);
    signatures.set("C:/runtime/launcher/state.json", "5:100");
    expect(gate.consumeNullFilenameEvent()).toBe(true);
    // The change was already sampled; the 30s stat poll must not re-fire it.
    expect(gate.consumeStatPoll()).toBe(false);
    expect(gate.consumeNullFilenameEvent()).toBe(false);
  });

  it("merges null events inside the refresh quiet window even when signatures changed", () => {
    let nowMs = 1_000;
    const signatures = new Map<string, string>();
    const gate = makeGate(signatures, { now: () => nowMs });
    gate.markRefreshStarted();
    signatures.set("C:/runtime/launcher/state.json", "6:100");
    expect(gate.consumeNullFilenameEvent()).toBe(false);
    nowMs += LAUNCHER_STATE_NULL_EVENT_QUIET_MS - 1;
    expect(gate.consumeNullFilenameEvent()).toBe(false);
    // After the quiet window the sampled change is gone (already consumed);
    // a brand-new change triggers again.
    nowMs += 2;
    signatures.set("C:/runtime/launcher/state.json", "7:120");
    expect(gate.consumeNullFilenameEvent()).toBe(true);
  });

  it("treats a missing observed file as a signature and notices its recreation", () => {
    const signatures = new Map<string, string>();
    const gate = makeGate(signatures);
    expect(gate.consumeNullFilenameEvent()).toBe(false);
    signatures.set("C:/runtime/launcher/ports.json", "9:1");
    expect(gate.consumeNullFilenameEvent()).toBe(true);
  });

  it("reports stat-poll changes and clears them for later null events", () => {
    const signatures = new Map<string, string>();
    const gate = makeGate(signatures);
    signatures.set("C:/runtime/launcher/state.json", "11:5");
    expect(gate.consumeStatPoll()).toBe(true);
    expect(gate.consumeStatPoll()).toBe(false);
    expect(gate.consumeNullFilenameEvent()).toBe(false);
  });
});

describe("launcherStateHintBackoff", () => {
  function makeBackoff(now: { value: number }, overrides?: { limit?: number; maxDelayMs?: number }) {
    const onEscalate = vi.fn();
    const backoff = createLauncherStateHintBackoff({
      now: () => now.value,
      limit: overrides?.limit ?? 3,
      maxDelayMs: overrides?.maxDelayMs ?? 30_000,
      onEscalate,
    });
    return { backoff, onEscalate };
  }

  it("keeps the base debounce until the sliding window breaches, then doubles", () => {
    const clock = { value: 1_000 };
    const { backoff, onEscalate } = makeBackoff(clock);
    for (let index = 0; index < 3; index += 1) {
      backoff.recordFire();
    }
    expect(backoff.currentDelayMs()).toBe(200);
    expect(backoff.isEscalated()).toBe(false);
    expect(onEscalate).not.toHaveBeenCalled();

    backoff.recordFire();
    expect(backoff.currentDelayMs()).toBe(400);
    expect(backoff.isEscalated()).toBe(true);
    expect(onEscalate).toHaveBeenCalledTimes(1);
    expect(onEscalate).toHaveBeenCalledWith(4, 400);

    backoff.recordFire();
    expect(backoff.currentDelayMs()).toBe(800);
    // Warn once per episode: the later doublings stay silent.
    expect(onEscalate).toHaveBeenCalledTimes(1);
  });

  it("caps the backoff at the max delay", () => {
    const clock = { value: 1_000 };
    const { backoff } = makeBackoff(clock, { maxDelayMs: 1_000 });
    for (let index = 0; index < 10; index += 1) {
      backoff.recordFire();
    }
    expect(backoff.currentDelayMs()).toBe(1_000);
  });

  it("resets to the base debounce after the window goes quiet and can warn again", () => {
    const clock = { value: 1_000 };
    const { backoff, onEscalate } = makeBackoff(clock);
    for (let index = 0; index < 5; index += 1) {
      backoff.recordFire();
    }
    expect(backoff.isEscalated()).toBe(true);

    clock.value = 1_000 + 60_000 + 1;
    expect(backoff.currentDelayMs()).toBe(200);
    expect(backoff.isEscalated()).toBe(false);

    for (let index = 0; index < 4; index += 1) {
      backoff.recordFire();
    }
    expect(backoff.currentDelayMs()).toBe(400);
    expect(onEscalate).toHaveBeenCalledTimes(2);
  });

  it("does not reset while fires keep arriving inside the window", () => {
    const clock = { value: 1_000 };
    const { backoff } = makeBackoff(clock);
    for (let index = 0; index < 4; index += 1) {
      backoff.recordFire();
    }
    clock.value += 50_000;
    expect(backoff.currentDelayMs()).toBe(400);
    clock.value += 9_999;
    expect(backoff.currentDelayMs()).toBe(400);
    clock.value += 1;
    expect(backoff.currentDelayMs()).toBe(200);
  });
});
