import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");
const helperModuleUrl = new URL("./conversationTimeFormat.ts", import.meta.url);

describe("conversationTimeFormat", () => {
  it("keeps conversation time formatting helpers outside ConversationView", () => {
    expect(existsSync(helperModuleUrl)).toBe(true);
    expect(conversationViewSource).toContain("from \"./conversationTimeFormat\"");
    expect(conversationViewSource).not.toContain("function formatTimestamp(");
    expect(conversationViewSource).not.toContain("function formatDuration(");
  });

  it("formats timestamps through the caller-owned formatter", async () => {
    const { formatConversationTimestamp } = await import("./conversationTimeFormat");
    const formatter = {
      format: (date: Date) => `formatted:${date.toISOString()}`,
    };

    expect(formatConversationTimestamp("2026-07-04T01:52:00.000Z", formatter)).toBe(
      "formatted:2026-07-04T01:52:00.000Z",
    );
    expect(formatConversationTimestamp("", formatter)).toBe("");
    expect(formatConversationTimestamp("not-a-date", formatter)).toBe("not-a-date");
  });

  it("formats operation durations with the existing compact labels", async () => {
    const { formatConversationDuration } = await import("./conversationTimeFormat");

    expect(formatConversationDuration(null)).toBe("");
    expect(formatConversationDuration(Number.NaN)).toBe("");
    expect(formatConversationDuration(-1)).toBe("");
    expect(formatConversationDuration(4.24)).toBe("4.2s");
    expect(formatConversationDuration(10.2)).toBe("10s");
    expect(formatConversationDuration(61.2)).toBe("1m 1s");
    expect(formatConversationDuration(120)).toBe("2m");
  });
});
