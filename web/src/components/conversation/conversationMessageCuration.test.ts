import { describe, expect, it } from "vitest";

import type { SessionMessageCurationItem } from "../../api/types";
import {
  applyOptimisticCuration,
  buildMessageCurationMap,
  resolveMessageCurationState,
  resolveModelCurationTally,
} from "./conversationMessageCuration";

function item(overrides: Partial<SessionMessageCurationItem>): SessionMessageCurationItem {
  return {
    messageId: "message-1",
    action: "include",
    modelId: "ai-pixel/gpt-5.6-luna",
    candidateId: "candidate-1",
    decidedAt: "2026-09-26T00:00:00Z",
    ...overrides,
  };
}

describe("conversationMessageCuration", () => {
  it("indexes decisions by message id with the later item winning", () => {
    const map = buildMessageCurationMap([
      item({ messageId: "message-1", action: "include" }),
      item({ messageId: "message-2", action: "exclude", candidateId: "candidate-2" }),
      item({ messageId: "message-1", action: "exclude", candidateId: "candidate-1b" }),
    ]);

    expect(map.size).toBe(2);
    expect(resolveMessageCurationState(map, "message-1")).toBe("exclude");
    expect(map.get("message-1")?.candidateId).toBe("candidate-1b");
    expect(resolveMessageCurationState(map, "message-2")).toBe("exclude");
  });

  it("resolves undecided messages to null and skips blank ids", () => {
    const map = buildMessageCurationMap([item({ messageId: "" }), item({ messageId: "message-2" })]);
    expect(resolveMessageCurationState(map, "message-1")).toBeNull();
    expect(map.size).toBe(1);
    expect(resolveMessageCurationState(new Map(), "message-1")).toBeNull();
  });

  it("applies optimistic writes immutably and keeps the previous identity fields", () => {
    const server = buildMessageCurationMap([item({ action: "include" })]);
    const optimistic = applyOptimisticCuration(server, "message-1", "exclude");

    expect(optimistic).not.toBe(server);
    expect(resolveMessageCurationState(server, "message-1")).toBe("include");
    expect(resolveMessageCurationState(optimistic, "message-1")).toBe("exclude");
    expect(optimistic.get("message-1")?.modelId).toBe("ai-pixel/gpt-5.6-luna");
    expect(optimistic.get("message-1")?.candidateId).toBe("candidate-1");
    expect(optimistic.get("message-1")?.decidedAt).toBe("");
  });

  it("applies optimistic writes for brand-new decisions", () => {
    const optimistic = applyOptimisticCuration(new Map(), "message-9", "include");
    expect(resolveMessageCurationState(optimistic, "message-9")).toBe("include");
    expect(optimistic.get("message-9")?.modelId).toBe("");
  });

  it("resolves a model tally as plain counts for the component to localize", () => {
    const models = [
      { modelId: "m-1", included: 3, excluded: 1 },
      { modelId: "m-2", included: 0, excluded: 4 },
    ];
    expect(resolveModelCurationTally(models, "m-1")).toEqual({ included: 3, excluded: 1 });
    expect(resolveModelCurationTally(models, "m-2")).toEqual({ included: 0, excluded: 4 });
  });

  it("returns null when the model is unknown, empty, or has nothing counted", () => {
    const models = [
      { modelId: "m-1", included: 3, excluded: 1 },
      { modelId: "m-empty", included: 0, excluded: 0 },
    ];
    expect(resolveModelCurationTally(models, "m-missing")).toBeNull();
    expect(resolveModelCurationTally(models, "m-empty")).toBeNull();
    expect(resolveModelCurationTally(models, "")).toBeNull();
    expect(resolveModelCurationTally([], "m-1")).toBeNull();
  });
});
