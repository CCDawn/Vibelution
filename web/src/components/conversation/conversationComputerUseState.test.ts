import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  COMPUTER_USE_TOOL_NAME,
  buildComputerUseStateForMessage,
  computerUseSessionIdsForMessage,
  computerUseSessionIdFromPreview,
  type ComputerUseResult,
} from "./conversationComputerUseState";

const conversationViewSource = readFileSync(
  new URL("./ConversationView.tsx", import.meta.url),
  "utf8",
);

describe("conversationComputerUseState", () => {
  it("keeps computer-use state helpers outside ConversationView", () => {
    expect(conversationViewSource).toContain("from \"./conversationComputerUseState\"");
    expect(conversationViewSource).not.toContain("function computerUseSessionIdFromPreview(");
    expect(conversationViewSource).not.toContain("function computerUseSessionIdsForMessage(");
    expect(conversationViewSource).not.toContain("function computerUseStateForMessage(");
  });

  it("extracts a trimmed computer-use session id from JSON preview", () => {
    expect(computerUseSessionIdFromPreview(JSON.stringify({ sessionId: " cu-1 " }))).toBe("cu-1");
    expect(computerUseSessionIdFromPreview(JSON.stringify({ sessionId: 42 }))).toBe("42");
    expect(computerUseSessionIdFromPreview("not-json")).toBe("");
    expect(computerUseSessionIdFromPreview("{invalid")).toBe("");
  });

  it("collects sorted unique computer-use session ids from tool calls and feedback events", () => {
    const message = {
      role: "assistant",
      toolCalls: [
        { name: COMPUTER_USE_TOOL_NAME, resultPreview: JSON.stringify({ sessionId: "cu-b" }) },
        { name: "other_tool", resultPreview: JSON.stringify({ sessionId: "ignored" }) },
      ],
      feedbackEvents: [
        { kind: "tool", name: COMPUTER_USE_TOOL_NAME, resultPreview: JSON.stringify({ sessionId: "cu-a" }) },
        { kind: "tool", name: COMPUTER_USE_TOOL_NAME, resultPreview: JSON.stringify({ sessionId: "cu-b" }) },
      ],
    } as ConversationMessage;

    expect(computerUseSessionIdsForMessage(message)).toEqual(["cu-a", "cu-b"]);
    expect(computerUseSessionIdsForMessage({ role: "user" } as ConversationMessage)).toEqual([]);
  });

  it("builds stable row-state text from result and pending maps", () => {
    const message = {
      role: "assistant",
      toolCalls: [
        { name: COMPUTER_USE_TOOL_NAME, resultPreview: JSON.stringify({ sessionId: "cu-a" }) },
        { name: COMPUTER_USE_TOOL_NAME, resultPreview: JSON.stringify({ sessionId: "cu-b" }) },
      ],
    } as ConversationMessage;
    const results: Record<string, ComputerUseResult> = {
      "cu-a": {
        status: "running",
        sessionId: "cu-a",
        summary: "Opening the page",
        steps: [],
        screenshotUrl: "/screens/cu-a.png",
        needsConfirmation: true,
        error: "",
      },
    };

    expect(buildComputerUseStateForMessage(message, results, { "cu-a": "confirm" })).toBe(
      [
        ["cu-a", "confirm", "running", "Opening the page", "", "/screens/cu-a.png", "1"].join("\u001f"),
        ["cu-b", "", "", "", "", "", "0"].join("\u001f"),
      ].join("\u001e"),
    );
    expect(buildComputerUseStateForMessage({ role: "user" } as ConversationMessage, results, {})).toBe("");
  });
});
