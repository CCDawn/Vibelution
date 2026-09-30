import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AGENT_BROADCAST_READ_STORAGE_KEY,
  agentBroadcastEventTimeMs,
  hasUnseenAgentBroadcast,
  readStoredAgentBroadcastReadAtMs,
  storeAgentBroadcastReadAtMs,
} from "./agentBroadcastBadge";

describe("agentBroadcastBadge unread gate", () => {
  it("marks any real event as unseen when the cursor is empty", () => {
    expect(hasUnseenAgentBroadcast(Date.parse("2026-09-30T08:00:00Z"), 0)).toBe(true);
  });

  it("clears once the cursor reaches the latest event and stays clear for older events", () => {
    const latest = Date.parse("2026-09-30T08:00:00Z");
    expect(hasUnseenAgentBroadcast(latest, latest)).toBe(false);
    expect(hasUnseenAgentBroadcast(latest, latest + 1)).toBe(false);
    expect(hasUnseenAgentBroadcast(latest - 1, latest)).toBe(false);
  });

  it("treats a missing or unparsable latest event as no unread state", () => {
    expect(hasUnseenAgentBroadcast(0, 0)).toBe(false);
  });

  it("prefers updatedAt and falls back through createdAt to zero", () => {
    expect(agentBroadcastEventTimeMs({
      createdAt: "2026-09-30T07:00:00Z",
      updatedAt: "2026-09-30T08:00:00Z",
    } as never)).toBe(Date.parse("2026-09-30T08:00:00Z"));
    expect(agentBroadcastEventTimeMs({
      createdAt: "2026-09-30T07:00:00Z",
      updatedAt: "",
    } as never)).toBe(Date.parse("2026-09-30T07:00:00Z"));
    expect(agentBroadcastEventTimeMs(undefined)).toBe(0);
    expect(agentBroadcastEventTimeMs({ createdAt: "not-a-date", updatedAt: "" } as never)).toBe(0);
  });
});

describe("agentBroadcastBadge read cursor storage", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
    });
    vi.stubGlobal("window", { localStorage: globalThis.localStorage });
  });

  it("advances the cursor under the dedicated key and reads it back", () => {
    expect(readStoredAgentBroadcastReadAtMs()).toBe(0);
    const cursor = Date.parse("2026-09-30T08:00:00Z");
    storeAgentBroadcastReadAtMs(cursor);
    expect(readStoredAgentBroadcastReadAtMs()).toBe(cursor);
    expect(localStorage.getItem(AGENT_BROADCAST_READ_STORAGE_KEY)).toBe(String(cursor));
  });

  it("ignores corrupt cursor values instead of throwing", () => {
    localStorage.setItem(AGENT_BROADCAST_READ_STORAGE_KEY, "not-a-number");
    expect(readStoredAgentBroadcastReadAtMs()).toBe(0);
    localStorage.setItem(AGENT_BROADCAST_READ_STORAGE_KEY, "-5");
    expect(readStoredAgentBroadcastReadAtMs()).toBe(0);
  });

  it("degrades silently when storage throws or window is unavailable", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("storage blocked");
      },
      setItem: () => {
        throw new Error("storage blocked");
      },
    });
    vi.stubGlobal("window", { localStorage: globalThis.localStorage });
    expect(readStoredAgentBroadcastReadAtMs()).toBe(0);
    expect(() => storeAgentBroadcastReadAtMs(123)).not.toThrow();

    vi.stubGlobal("window", undefined);
    expect(readStoredAgentBroadcastReadAtMs()).toBe(0);
    expect(() => storeAgentBroadcastReadAtMs(123)).not.toThrow();
  });
});
