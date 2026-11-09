import { beforeEach, describe, expect, it } from "vitest";

import type { SessionSummary } from "../api/types";
import {
  applyAgentSessionTabOrder,
  persistAgentSessionTabOrder,
  reorderSessionIds,
  storedAgentSessionTabOrder,
} from "./agentSessionTabOrder";

function session(id: string): SessionSummary {
  return { id, title: id } as SessionSummary;
}

describe("agentSessionTabOrder", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => {
          store.set(key, value);
        },
        removeItem: (key: string) => {
          store.delete(key);
        },
        clear: () => {
          store.clear();
        },
        key: () => null,
        get length() {
          return store.size;
        },
      },
    });
  });

  it("keeps server order until a manual order exists", () => {
    const sessions = [session("a"), session("b")];
    expect(applyAgentSessionTabOrder(sessions, "agent-1").map((item) => item.id)).toEqual(["a", "b"]);
    expect(storedAgentSessionTabOrder("agent-1")).toEqual([]);
  });

  it("applies the stored order and appends unknown sessions in incoming order", () => {
    persistAgentSessionTabOrder("agent-1", ["c", "a"]);
    const ordered = applyAgentSessionTabOrder(
      [session("a"), session("b"), session("c")],
      "agent-1",
    );
    expect(ordered.map((item) => item.id)).toEqual(["c", "a", "b"]);
  });

  it("scopes the order per Agent", () => {
    persistAgentSessionTabOrder("agent-1", ["b", "a"]);
    expect(applyAgentSessionTabOrder([session("a"), session("b")], "agent-2").map((i) => i.id))
      .toEqual(["a", "b"]);
  });

  it("drops the stored order when the list becomes empty", () => {
    persistAgentSessionTabOrder("agent-1", ["b", "a"]);
    persistAgentSessionTabOrder("agent-1", []);
    expect(storedAgentSessionTabOrder("agent-1")).toEqual([]);
  });

  it("moves a dragged id before or after a target", () => {
    const ids = ["a", "b", "c"];
    expect(reorderSessionIds(ids, "c", "a", "before")).toEqual(["c", "a", "b"]);
    expect(reorderSessionIds(ids, "a", "c", "after")).toEqual(["b", "c", "a"]);
    expect(reorderSessionIds(ids, "b", "b", "before")).toEqual(["a", "b", "c"]);
    expect(reorderSessionIds(ids, "missing", "a", "before")).toEqual(["a", "b", "c"]);
  });

  it("survives malformed storage without throwing", () => {
    localStorage.setItem("vibelution.agentSessionTabOrder.v1", "{not json");
    expect(storedAgentSessionTabOrder("agent-1")).toEqual([]);
    expect(applyAgentSessionTabOrder([session("a")], "agent-1").map((i) => i.id)).toEqual(["a"]);
  });
});
