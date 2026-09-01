import { describe, expect, it } from "vitest";

import {
  avatarInitials,
  chatRoomModeLabel,
  compactAgentRoleLabel,
  formatAgentIdentityLabel,
  groupConsecutiveBy,
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
