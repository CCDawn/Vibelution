import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";

const displayMessagesModulePath = new URL("./conversationDisplayMessages.ts", import.meta.url);
const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");

async function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  if (!existsSync(displayMessagesModulePath)) {
    expect(existsSync(displayMessagesModulePath)).toBe(true);
  }
  const module = await import("./conversationDisplayMessages");
  return module.projectConversationDisplayMessages(messages);
}

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message",
    role: "assistant",
    content: "",
    timestamp: "2026-07-03T21:44:00Z",
    ...overrides,
  };
}

describe("conversation display message projection", () => {
  it("keeps ConversationView from owning display message DTO merge rules", () => {
    expect(existsSync(displayMessagesModulePath)).toBe(true);
    expect(conversationViewSource).toContain("projectConversationDisplayMessages");
    expect(conversationViewSource).not.toContain("function mergeAdjacentTurnErrorMessages");
    expect(conversationViewSource).not.toContain("const mergedMessages: ConversationMessage[]");
  });
  it("keeps append order for unsequenced messages without reordering by wall clock", async () => {
    // detail.messages is already ordered by mergeSessionDetailMessageWindow
    // (journal sequence first, append order otherwise). The display projection
    // must not reorder unsequenced messages by timestamp: optimistic user
    // messages carry the client clock while live assistant layers carry the
    // server clock, so a small skew would swap them.
    const projected = await projectConversationDisplayMessages([
      message({
        id: "user-old",
        role: "user",
        content: "old question",
        timestamp: "2026-07-09T01:26:58Z",
      }),
      message({
        id: "assistant-old",
        role: "assistant",
        content: "old answer",
        timestamp: "2026-07-09T01:26:48Z",
      }),
      message({
        id: "user-new",
        role: "user",
        content: "new question",
        timestamp: "2026-07-09T01:26:46Z",
      }),
      message({
        id: "assistant-new",
        role: "assistant",
        content: "new answer",
        timestamp: "2026-07-09T01:26:44Z",
      }),
    ]);

    expect(projected.map((item) => item.id)).toEqual([
      "user-old",
      "assistant-old",
      "user-new",
      "assistant-new",
    ]);
  });

  it("drops recovery-superseded interrupted partials from display while journal keeps them", async () => {
    const projected = await projectConversationDisplayMessages([
      message({
        id: "assistant-partial",
        content: "half-streamed answer before the restart",
        metadata: { interrupted: true, recoverySuperseded: true },
      }),
      message({
        id: "assistant-resumed",
        content: "",
        metadata: { kind: "session_recovery_resumed", attempt: 2, turnLabel: "重构导出脚本" },
      }),
    ]);

    expect(projected.map((item) => item.id)).toEqual(["assistant-resumed"]);
  });

  it("drops the system-authored resume user row so the timeline keeps one user message", async () => {
    // Startup recovery re-journals the interrupted turn's user text with
    // kind=hot_restart_resume (journal untouched); the display projection must
    // not duplicate it next to the original user row.
    const projected = await projectConversationDisplayMessages([
      message({
        id: "user-original",
        role: "user",
        content: "E2E-MOCK-SLOW-V1 重启自动恢复",
      }),
      message({
        id: "assistant-resumed-status",
        content: "",
        metadata: { kind: "session_recovery_resumed", attempt: 1, turnLabel: "重启自动恢复" },
      }),
      message({
        id: "user-resumed-duplicate",
        role: "user",
        content: "E2E-MOCK-SLOW-V1 重启自动恢复",
        metadata: { kind: "hot_restart_resume", recoveredTurnId: "turn-1" },
      }),
      message({
        id: "assistant-resumed-answer",
        content: "0123456789 resumed answer",
      }),
    ]);

    expect(projected.map((item) => item.id)).toEqual([
      "user-original",
      "assistant-resumed-status",
      "assistant-resumed-answer",
    ]);
  });

  it("keeps interrupted partials visible when recovery did not supersede them", async () => {
    const projected = await projectConversationDisplayMessages([
      message({
        id: "assistant-partial",
        content: "half-streamed answer",
        metadata: { interrupted: true },
      }),
    ]);

    expect(projected.map((item) => item.id)).toEqual(["assistant-partial"]);
  });
});
