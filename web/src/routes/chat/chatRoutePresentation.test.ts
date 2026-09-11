import { describe, expect, it } from "vitest";

import type { TranslationKey } from "../../i18n/dictionary";
import {
  avatarInitials,
  chatRoomModeLabel,
  compactAgentRoleLabel,
  formatAgentIdentityLabel,
  groupConsecutiveBy,
  promptSegmentDisplayLabel,
  shouldCollapseGroupMessage,
} from "./chatRoutePresentation";

describe("chatRoutePresentation", () => {
  it("labels chat room modes in zh/en", () => {
    expect(chatRoomModeLabel({ id: "round_robin", label: "" }, "zh")).toBe("轮询讨论");
    expect(chatRoomModeLabel({ id: "opportunistic", label: "" }, "en")).toBe("Opportunistic");
    expect(chatRoomModeLabel({ id: "custom", label: "X" }, "en")).toBe("X");
  });

  it("formats agent identity labels without role suffix", () => {
    expect(formatAgentIdentityLabel("Alpha")).toBe("Alpha");
    expect(formatAgentIdentityLabel("", "p1")).toBe("p1");
    expect(compactAgentRoleLabel("planner / long description")).toBe("planner");
  });

  it("derives avatar initials from codes and names", () => {
    expect(avatarInitials("agent12", "Name")).toBe("12");
    expect(avatarInitials("AB", "Name")).toBe("AB");
    expect(avatarInitials("", "你好")).toBe("你好");
  });

  it("collapses long group messages", () => {
    expect(shouldCollapseGroupMessage("short")).toBe(false);
    expect(shouldCollapseGroupMessage("x".repeat(261))).toBe(true);
    expect(shouldCollapseGroupMessage("a\n".repeat(9))).toBe(true);
  });

  it("groups consecutive items that share a speaker key", () => {
    const groups = groupConsecutiveBy(
      [{ id: "a", speaker: "p1" }, { id: "b", speaker: "p1" }, { id: "c", speaker: "p2" }],
      (item) => item.speaker,
    );
    expect(groups.map((group) => group.map((item) => item.id))).toEqual([["a", "b"], ["c"]]);
  });
});

function testTranslator(key: TranslationKey) {
  if (key === "contextSegment_history") {
    return "历史";
  }
  return key;
}

describe("promptSegmentDisplayLabel", () => {
  it("localizes manifest and runtime context segment keys", () => {
    expect(promptSegmentDisplayLabel(
      { key: "agent_prompt_snapshot", label: "agent prompt snapshot", promptCategory: "system_prompt" },
      "zh",
      testTranslator,
    )).toBe("Agent 提示快照");
    expect(promptSegmentDisplayLabel(
      { key: "dynamic_runtime_context", label: "dynamic runtime context", promptCategory: "" },
      "zh",
      testTranslator,
    )).toBe("动态运行上下文");
    expect(promptSegmentDisplayLabel(
      { key: "computed_missing", label: "computed missing", promptCategory: "" },
      "zh",
      testTranslator,
    )).toBe("无法计算");
    expect(promptSegmentDisplayLabel(
      { key: "agent_prompt_snapshot", label: "agent prompt snapshot", promptCategory: "system_prompt" },
      "en",
      testTranslator,
    )).toBe("agent prompt snapshot");
  });

  it("never leaks a raw english fallback for unknown keys", () => {
    expect(promptSegmentDisplayLabel(
      { key: "mystery_segment", label: "mystery segment", promptCategory: "" },
      "zh",
      testTranslator,
    )).toBe("其他上下文");
    expect(promptSegmentDisplayLabel(
      { key: "mystery_segment", label: "mystery segment", promptCategory: "" },
      "en",
      testTranslator,
    )).toBe("other context");
  });

  it("keeps i18n-backed segment names", () => {
    expect(promptSegmentDisplayLabel(
      { key: "history", label: "history", promptCategory: "" },
      "zh",
      testTranslator,
    )).toBe("历史");
  });
});
