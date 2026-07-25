import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  WORKBENCH_LAYOUT_IDS,
  WORKBENCH_LAYOUT_ID_LIST,
  isWorkbenchLayoutId,
} from "./workbenchLayoutIds";

const root = resolve(import.meta.dirname, "../..");

function read(rel: string) {
  return readFileSync(resolve(root, rel), "utf-8");
}

describe("workbenchLayoutIds", () => {
  it("exposes unique stable layout ids", () => {
    expect(new Set(WORKBENCH_LAYOUT_ID_LIST).size).toBe(WORKBENCH_LAYOUT_ID_LIST.length);
    expect(isWorkbenchLayoutId("chat")).toBe(true);
    expect(isWorkbenchLayoutId("not-a-layout")).toBe(false);
  });

  it("keeps primary shells on registry ids (Wave 4C gate)", () => {
    const samples: Array<{ file: string; token: string }> = [
      { file: "routes/AgentWorkspaceLayoutPanel.tsx", token: "WORKBENCH_LAYOUT_IDS.agents" },
      { file: "store/shellStore.ts", token: "WORKBENCH_LAYOUT_IDS.chat" },
      { file: "routes/ConfigRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.configSettings" },
      { file: "routes/ConfigProviderRegistryPanel.tsx", token: "WORKBENCH_LAYOUT_IDS.configModelAssets" },
      { file: "routes/SkillsRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.skills" },
      { file: "routes/PromptTemplatesRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.promptTemplates" },
      { file: "routes/KernelTaskCenterRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.kernelTaskCenter" },
      { file: "routes/LauncherRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.launcher" },
      { file: "routes/TeamsRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.teams" },
      { file: "routes/MemoryRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.memory" },
      { file: "routes/LogsRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.logs" },
      { file: "routes/ToolsRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.tools" },
      { file: "routes/GitRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.git" },
      { file: "routes/SupervisedReviewRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.supervisedReview" },
      { file: "routes/EvolutionRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.evolution" },
      { file: "routes/SelfEvolutionTrack.tsx", token: "WORKBENCH_LAYOUT_IDS.evolutionSelf" },
      { file: "routes/ChatCodingRoute.tsx", token: "WORKBENCH_LAYOUT_IDS.chat" },
    ];

    for (const sample of samples) {
      const source = read(sample.file);
      expect(source, sample.file).toContain(sample.token);
    }
  });

  it("documents recipe + layoutId as the preferred new-page path", () => {
    const readme = read("components/vui/README.md");
    expect(readme).toContain("layoutId");
    expect(readme).toContain("pane-layouts.v1");
    expect(readme).toContain("Workbench layoutIds");
  });
});
