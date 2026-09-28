import { describe, expect, it } from "vitest";

import {
  buildConversationModelSwitchBoundaries,
  conversationMessageLlmModelId,
  type ConversationModelSwitchMessage,
} from "./conversationModelSwitch";

let nextId = 0;

function userMessage(): ConversationModelSwitchMessage {
  nextId += 1;
  return { id: `u${nextId}`, role: "user" };
}

function assistantWithModel(modelId: string): ConversationModelSwitchMessage {
  nextId += 1;
  return {
    id: `a${nextId}`,
    role: "assistant",
    metadata: { llmUsage: { llmModelId: modelId, inputTokens: 100 } },
  };
}

function compressionMarker(): ConversationModelSwitchMessage {
  nextId += 1;
  return {
    id: `m${nextId}`,
    role: "assistant",
    content: "",
    metadata: {
      kind: "context_compression_marker",
      status: "applied",
      title: "上下文已压缩",
      coveredEventSeqStart: 1,
      coveredEventSeqEnd: 8,
      summaryPreview: "压缩摘要",
    },
  } as ConversationModelSwitchMessage;
}

function turn(modelId: string): ConversationModelSwitchMessage[] {
  return [userMessage(), assistantWithModel(modelId)];
}

describe("conversationModelSwitch", () => {
  it("marks the first turn-with-model as the initial boundary", () => {
    const [u1, a1] = turn("gpt-5.2");
    expect(buildConversationModelSwitchBoundaries([u1, a1])).toEqual(
      new Map([[u1.id, { kind: "initial", toModelId: "gpt-5.2" }]]),
    );
  });

  it("marks a model change as a switch relative to the previous turn-with-model", () => {
    const [u1, a1] = turn("gpt-5.2");
    const [u2, a2] = turn("glm-5");
    expect(buildConversationModelSwitchBoundaries([u1, a1, u2, a2])).toEqual(
      new Map([
        [u1.id, { kind: "initial", toModelId: "gpt-5.2" }],
        [u2.id, { kind: "switch", fromModelId: "gpt-5.2", toModelId: "glm-5" }],
      ]),
    );
  });

  it("attaches nothing when consecutive turns keep the same model", () => {
    const t1 = turn("glm-5");
    const [u1] = t1;
    const messages = [...t1, ...turn("glm-5"), ...turn("glm-5")];
    const boundaries = buildConversationModelSwitchBoundaries(messages);
    expect(boundaries.size).toBe(1);
    expect(boundaries.get(u1.id)).toEqual({ kind: "initial", toModelId: "glm-5" });
  });

  it("ignores compression markers: no model source and no turn-grouping break", () => {
    // Marker sits between the user row and the assistant row of the same
    // turn, plus one between turns.
    const [u1, a1] = turn("gpt-5.2");
    const m1 = compressionMarker();
    const u2 = userMessage();
    const m2 = compressionMarker();
    const a2 = assistantWithModel("glm-5");
    const boundaries = buildConversationModelSwitchBoundaries([u1, m1, a1, u2, m2, a2]);
    expect(boundaries).toEqual(
      new Map([
        [u1.id, { kind: "initial", toModelId: "gpt-5.2" }],
        [u2.id, { kind: "switch", fromModelId: "gpt-5.2", toModelId: "glm-5" }],
      ]),
    );
    // The marker itself never becomes a boundary key or a model chain step.
    expect(boundaries.has(m1.id)).toBe(false);
    expect(boundaries.has(m2.id)).toBe(false);
  });

  it("skips turns without an assistant model and bridges the model chain across them", () => {
    const [u1, a1] = turn("gpt-5.2");
    // Turn 2: user row with an assistant turn that never reported usage.
    const u2 = userMessage();
    const a2: ConversationModelSwitchMessage = {
      id: "a-no-usage",
      role: "assistant",
      metadata: { kind: "cli_agent_lifecycle" },
    };
    const [u3, a3] = turn("glm-5");
    const boundaries = buildConversationModelSwitchBoundaries([u1, a1, u2, a2, u3, a3]);
    expect(boundaries.get(u2.id)).toBeUndefined();
    // The switch compares against the last turn WITH a model, not the skipped
    // turn in between.
    expect(boundaries.get(u3.id)).toEqual({
      kind: "switch",
      fromModelId: "gpt-5.2",
      toModelId: "glm-5",
    });
  });

  it("resolves every model change across multiple switches, including back-switches", () => {
    const t1 = turn("glm-5");
    const t2 = turn("gpt-5.2");
    const t3 = turn("glm-5");
    const t4 = turn("claude-opus");
    const [u1] = t1;
    const [u2] = t2;
    const [u3] = t3;
    const [u4] = t4;
    const boundaries = buildConversationModelSwitchBoundaries([...t1, ...t2, ...t3, ...t4]);
    expect(boundaries).toEqual(
      new Map([
        [u1.id, { kind: "initial", toModelId: "glm-5" }],
        [u2.id, { kind: "switch", fromModelId: "glm-5", toModelId: "gpt-5.2" }],
        [u3.id, { kind: "switch", fromModelId: "gpt-5.2", toModelId: "glm-5" }],
        [u4.id, { kind: "switch", fromModelId: "glm-5", toModelId: "claude-opus" }],
      ]),
    );
  });

  it("skips assistant rows before any user row and still yields initial for the first real turn", () => {
    const a0 = assistantWithModel("gpt-5.2");
    const [u1, a1] = turn("glm-5");
    const boundaries = buildConversationModelSwitchBoundaries([a0, u1, a1]);
    expect(boundaries).toEqual(new Map([[u1.id, { kind: "initial", toModelId: "glm-5" }]]));
  });

  it("reads llmModelId defensively from untyped metadata", () => {
    expect(conversationMessageLlmModelId({ metadata: { llmUsage: { llmModelId: " glm-5 " } } })).toBe("glm-5");
    expect(conversationMessageLlmModelId({ metadata: { llmUsage: { llmModelId: 42 } } })).toBe("");
    expect(conversationMessageLlmModelId({ metadata: { llmUsage: "broken" } })).toBe("");
    expect(conversationMessageLlmModelId({ metadata: { kind: "context_compression_marker" } })).toBe("");
    expect(conversationMessageLlmModelId({})).toBe("");
  });
});
