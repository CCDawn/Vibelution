import { describe, expect, it } from "vitest";

import type { TeamCanvasNode } from "../../api/types";
import {
  canvasNodeRoleBadgeKind,
  canvasNodeToneKind,
  nodeToneClass,
  roleBadgeToneClass,
} from "./teamCanvasNodePresentation";

describe("teamCanvasNodePresentation", () => {
  it("classifies role badge and node tone kinds", () => {
    const lead = { role: "research_ceo", purpose: "lead", agentId: "a1", status: "bound" } as TeamCanvasNode;
    expect(canvasNodeRoleBadgeKind(lead)).toBe("lead");
    expect(canvasNodeToneKind(lead)).toBe("bound");

    const stale = { role: "worker", purpose: "", agentId: "a2", status: "stale" } as TeamCanvasNode;
    expect(canvasNodeRoleBadgeKind(stale)).toBe("stale");
    expect(canvasNodeToneKind(stale)).toBe("stale");

    const open = { role: "worker", purpose: "", agentId: "", status: "open" } as TeamCanvasNode;
    expect(canvasNodeRoleBadgeKind(open)).toBe("open");
    expect(canvasNodeToneKind(open)).toBe("open");
  });

  it("maps kinds onto style tokens", () => {
    const node = { role: "capability_steward", purpose: "管家", agentId: "a1", status: "bound" } as TeamCanvasNode;
    const badgeStyles = {
      stale: "s",
      open: "o",
      lead: "l",
      advisor: "a",
      steward: "st",
      research: "r",
      self: "self",
      general: "g",
    };
    const toneStyles = { stale: "ns", bound: "nb", open: "no" };
    expect(roleBadgeToneClass(node, badgeStyles)).toBe("st");
    expect(nodeToneClass(node, toneStyles)).toBe("nb");
  });
});
