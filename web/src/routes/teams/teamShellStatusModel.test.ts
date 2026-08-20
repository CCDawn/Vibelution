import { describe, expect, it } from "vitest";

import type { TeamCanvasNode } from "../../api/types";
import type { ResearchBoardColumn } from "./researchBoardModel";
import {
  teamShellKindLabel,
  teamShellNodesFromCanvas,
  teamShellStageChipTone,
  teamShellStagesFromBoardColumns,
} from "./teamShellStatusModel";

function node(partial: Partial<TeamCanvasNode> & Pick<TeamCanvasNode, "id" | "label">): TeamCanvasNode {
  return {
    type: "role",
    status: "unbound",
    x: 0,
    y: 0,
    agentId: "",
    agentCode: "",
    agentName: "",
    role: "source_finder",
    purpose: "",
    ...partial,
  };
}

describe("teamShellStatusModel", () => {
  it("maps board columns to a three-stage index", () => {
    const columns: ResearchBoardColumn[] = [
      {
        id: "knowledge_collection",
        titleZh: "资料寻找",
        titleEn: "Sources",
        cards: [{ id: "a", title: "t", body: "", meta: [], foot: "进行中", active: true }],
      },
      {
        id: "experiment",
        titleZh: "实验设计",
        titleEn: "Experiment",
        cards: [{ id: "b", title: "t", body: "", meta: [], foot: "未开始" }],
      },
      {
        id: "iteration",
        titleZh: "执行迭代",
        titleEn: "Iteration",
        cards: [{ id: "c", title: "t", body: "", meta: [], foot: "未开始" }],
      },
    ];
    const stages = teamShellStagesFromBoardColumns(columns, "zh");
    expect(stages).toHaveLength(3);
    expect(stages[0]).toMatchObject({ title: "资料寻找", tone: "active", status: "进行中" });
    expect(stages[1].tone).toBe("idle");
    expect(teamShellStageChipTone("active")).toBe("warning");
  });

  it("maps canvas nodes to a status index without inventing agents", () => {
    const nodes = teamShellNodesFromCanvas([
      node({ id: "n1", label: "资料寻找", agentName: "白望舒", agentId: "a1", status: "bound" }),
      node({ id: "n2", label: "资料提炼", status: "unbound" }),
    ], "zh");
    expect(nodes[0]).toMatchObject({
      id: "n1",
      label: "资料寻找",
      agent: "白望舒",
      statusTone: "success",
    });
    expect(nodes[1].agent).toBe("未绑定");
    expect(nodes[1].statusTone).toBe("warning");
  });

  it("labels known team kinds", () => {
    expect(teamShellKindLabel({
      teamId: "research-team",
      name: "挑战杯",
      teamKind: "research",
    } as never, "zh")).toBe("科研工作流");
  });
});
