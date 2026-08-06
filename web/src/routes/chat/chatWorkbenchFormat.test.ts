import { describe, expect, it } from "vitest";

import { formatChatClockTime, formatChatConversationIndexTime } from "./chatWorkbenchFormat";

describe("chatWorkbenchFormat", () => {
  const formatter = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  it("formats clock times and strips seconds for index labels", () => {
    expect(formatChatClockTime("", formatter)).toBe("");
    expect(formatChatClockTime("not-a-date", formatter)).toBe("not-a-date");
    const iso = "2026-01-02T03:04:05.000Z";
    const full = formatChatClockTime(iso, formatter);
    expect(full.length).toBeGreaterThan(0);
    expect(formatChatConversationIndexTime(iso, formatter)).toBe(full.replace(/:\d{2}$/, ""));
  });
});
