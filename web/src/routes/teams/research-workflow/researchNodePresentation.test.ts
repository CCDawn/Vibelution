import { describe, expect, it } from "vitest";

import { researchActorLabel, researchStageLabel } from "./researchNodePresentation";

describe("research node presentation", () => {
  it("localizes workflow stage and actor values", () => {
    expect(researchStageLabel("knowledge_collection")).toBe("资料搜集");
    expect(researchActorLabel("agent")).toBe("Agent 执行");
  });

  it("does not leak future backend enums", () => {
    expect(researchStageLabel("future_stage")).toBe("流程阶段");
    expect(researchActorLabel("future_actor")).toBe("执行节点");
  });
});
