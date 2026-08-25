import { describe, expect, it } from "vitest";

import type { TeamCanvasNode } from "../../api/types";
import {
  canvasNodeAgentLine,
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

  it("resolves the card agent line through display name, stored names, then localized status", () => {
    const bound = {
      role: "source_finder",
      purpose: "",
      agentId: "a1",
      agentName: "Finder Bot",
      agentCode: "finder-01",
      status: "bound",
    } as TeamCanvasNode;
    expect(canvasNodeAgentLine(bound, "资料寻找员", "zh")).toBe("资料寻找员");
    expect(canvasNodeAgentLine(bound, undefined, "zh")).toBe("Finder Bot");
    expect(canvasNodeAgentLine(bound, "  ", "zh")).toBe("Finder Bot");
    expect(canvasNodeAgentLine({ ...bound, agentName: "" }, undefined, "zh")).toBe("finder-01");

    const unbound = {
      role: "worker",
      purpose: "",
      agentId: "",
      agentName: "",
      agentCode: "",
      status: "unbound",
    } as TeamCanvasNode;
    expect(canvasNodeAgentLine(unbound, undefined, "zh")).toBe("未绑定");
    expect(canvasNodeAgentLine(unbound, undefined, "en")).toBe("unbound");

    const stale = {
      role: "worker",
      purpose: "",
      agentId: "a9",
      agentName: "",
      agentCode: "",
      status: "stale",
    } as TeamCanvasNode;
    expect(canvasNodeAgentLine(stale, undefined, "zh")).toBe("引用失效");
    expect(canvasNodeAgentLine(stale, undefined, "en")).toBe("stale reference");
  });
});
