import { describe, expect, it } from "vitest";

import activeStageSource from "./TeamSourceCollectionActiveStagePanel.tsx?raw";
import activeStageStyles from "./TeamSourceCollectionActiveStagePanel.styles";
import standaloneStageSource from "./TeamSourceCollectionStandaloneStagePanel.tsx?raw";
import standaloneStageStyles from "./TeamSourceCollectionStandaloneStagePanel.styles";

describe("source collection vertical three-column workbench", () => {
  it("places run context, result workspace, and stage controls in persistent desktop rails", () => {
    expect(standaloneStageStyles.sourceCollectionPageBody).toContain(
      "grid-cols-[clamp(228px,14vw,278px)_minmax(520px,1fr)_clamp(270px,17vw,338px)]",
    );
    expect(standaloneStageStyles.sourceCollectionRunContext).toContain("col-start-1");
    expect(standaloneStageStyles.sourceCollectionPageGrid).toContain("col-start-2 col-span-2");
    expect(activeStageStyles.sourceCollectionStageWorkspace).toContain(
      "grid-cols-[minmax(0,1fr)_clamp(270px,17vw,338px)]",
    );
    expect(activeStageStyles.sourceCollectionStageResult).toContain(
      "col-start-1 row-start-1 row-span-2",
    );
    expect(activeStageStyles.sourceCollectionStageWorkspaceHeader).toContain(
      "col-start-2 row-start-1",
    );
  });

  it("keeps stage navigation free of duplicated long action buttons", () => {
    expect(standaloneStageSource).not.toContain("actions={");
    expect(standaloneStageSource).not.toContain('from "../components/vui"');
  });

  it("groups errors and results into explicit grid surfaces", () => {
    expect(activeStageSource).toContain("sourceCollectionStageErrors");
    expect(activeStageSource).toContain("sourceCollectionStageResult");
    expect(activeStageStyles.sourceCollectionStageChatActions).toContain(
      "grid-cols-[repeat(2,minmax(0,1fr))]",
    );
  });
});
