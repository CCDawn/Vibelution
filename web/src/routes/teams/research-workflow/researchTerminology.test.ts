import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  HYPOTHESIS_DESIGN_NODE_TERM,
  RESEARCH_STAGE_TERMS,
  RUN_TIMELINE_TERM,
  researchStageTermZh,
} from "./researchTerminology";

/**
 * Terminology contract: the research workflow surfaces must not reintroduce
 * retired split synonyms. Each entry maps an owning source file to literals
 * that were unified into researchTerminology.ts.
 */
const RETIRED_SYNONYMS: Array<{ file: string; banned: string[] }> = [
  {
    file: "researchNodePresentation.ts",
    banned: ["知识搜集"],
  },
  {
    file: "researchWorkflowContextModel.ts",
    banned: ["知识搜集"],
  },
  {
    file: "ResearchRunSafetyLimitPanel.tsx",
    banned: ["知识搜集"],
  },
  {
    file: "nodeAdapterModel.ts",
    banned: ["假设设计"],
  },
  {
    file: "ResearchWorkflowToolbar.tsx",
    banned: ["知识搜集", "运行记录"],
  },
  // Stage pages and the workbench chrome that sit next to the workflow
  // toolbar: the same stage must keep the same name across the chain.
  {
    file: "../ResearchStageNav.tsx",
    banned: ["知识搜集"],
  },
  {
    file: "../ResearchBoardKanban.tsx",
    banned: ["知识搜集"],
  },
  {
    file: "../researchBoardModel.ts",
    banned: ["知识搜集"],
  },
  {
    file: "../researchWorkspaceModel.ts",
    banned: ["知识搜集"],
  },
  {
    file: "../SourceCollectionComposer.tsx",
    banned: ["知识搜集"],
  },
  {
    file: "../ResearchPrimaryActionBar.tsx",
    banned: ["知识搜集"],
  },
  {
    file: "../ResearchStageWorkbenchShell.tsx",
    banned: ["知识搜集"],
  },
  {
    file: "../researchPrimaryActionModel.ts",
    banned: ["知识搜集"],
  },
  {
    file: "../workflowPresentation.ts",
    banned: ["知识搜集"],
  },
  {
    file: "../source-collection/createSourceCollectionController.tsx",
    banned: ["知识搜集"],
  },
  {
    file: "../source-collection/presentationActionReadiness.ts",
    banned: ["知识搜集"],
  },
  {
    file: "../source-collection/stageModulesModel.ts",
    banned: ["知识搜集"],
  },
  {
    file: "../../TeamResearchStageLauncherPanel.tsx",
    banned: ["知识搜集"],
  },
  {
    // app layer stays import-free of routes, so this file pins the literal.
    file: "../../../app/systemStatus.ts",
    banned: ["知识搜集"],
  },
];

describe("researchTerminology", () => {
  it("keeps one canonical term per stage and surface", () => {
    expect(RESEARCH_STAGE_TERMS.knowledge_collection).toEqual({
      zh: "资料搜集",
      en: "Knowledge collection",
    });
    expect(HYPOTHESIS_DESIGN_NODE_TERM).toEqual({ zh: "假说设计", en: "Hypothesis design" });
    expect(RUN_TIMELINE_TERM).toEqual({ zh: "运行时间线", en: "Run timeline" });
  });

  it("falls back to a neutral label for unknown stages", () => {
    expect(researchStageTermZh("not_a_stage")).toBe("流程阶段");
    expect(researchStageTermZh("knowledge_collection")).toBe("资料搜集");
  });

  it("bans retired split synonyms in the owning source files", () => {
    for (const { file, banned } of RETIRED_SYNONYMS) {
      const source = readFileSync(fileURLToPath(new URL(file, import.meta.url)), "utf8");
      for (const literal of banned) {
        expect(
          source.includes(literal),
          `${file} must consume researchTerminology instead of the retired literal "${literal}"`
        ).toBe(false);
      }
    }
  });
});
