import { describe, expect, it } from "vitest";

import type { TeamResearchProject } from "../../../api/types";
import { projectDraftFromProject, researchProjectQueryKey } from "./ResearchProjectSwitcher";
import switcherSource from "./ResearchProjectSwitcher.tsx?raw";

const project: TeamResearchProject = {
  projectId: "research-1",
  name: "Causal robustness",
  topic: "Robust causal discovery",
  experimentMethod: "statistical_causal_test",
  storageMode: "isolated",
  nameLocked: false,
  nameLockedAt: "",
  nameLockReason: "",
  createdAt: "2026-07-24T00:00:00Z",
  updatedAt: "2026-07-24T00:00:00Z",
};

describe("ResearchProjectSwitcher", () => {
  it("keeps project queries isolated by team", () => {
    expect(researchProjectQueryKey("team-a")).toEqual(["teams", "team-a", "research-projects"]);
  });

  it("builds editable drafts from persisted project identity", () => {
    expect(projectDraftFromProject(project)).toEqual({
      name: "Causal robustness",
      topic: "Robust causal discovery",
    });
  });

  it("exposes create, edit, activate, and isolated workspace guidance", () => {
    expect(switcherSource).toContain("research-projects");
    expect(switcherSource).toContain("/activate");
    expect(switcherSource).toContain("新建研究项目");
    expect(switcherSource).toContain("每个项目拥有独立的资料、实验设计和迭代数据");
  });

  it("supports the approved project hero without replacing project operations", () => {
    expect(switcherSource).toContain('variant?: "compact" | "hero"');
    expect(switcherSource).toContain('variant === "hero"');
    expect(switcherSource).toContain("primaryActionHref");
    expect(switcherSource).toContain("primaryActionLabel");
    expect(switcherSource).toContain("已自动保存");
    expect(switcherSource).toContain("切换项目");
    expect(switcherSource).toContain("VStatusChip");
    expect(switcherSource).toContain("projectStatusTone");
  });

  it("keeps project identity stable after the first experiment task", () => {
    expect(switcherSource).toContain("activeProject?.nameLocked ? {} : { name: draft.name.trim() }");
    expect(switcherSource).toContain('disabled={dialogMode === "edit" && activeProject?.nameLocked === true}');
    expect(switcherSource).toContain("首次实验任务已建立，项目名称已锁定");
  });
});
