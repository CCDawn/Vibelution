import { describe, expect, it } from "vitest";

import {
  LAUNCHER_STATE_NULL_EVENT_QUIET_MS,
  createLauncherStateFileHintGate,
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
