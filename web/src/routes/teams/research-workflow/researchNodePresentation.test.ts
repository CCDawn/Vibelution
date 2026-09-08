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

  it("uses the frozen definition's stage name for stage-one runs", () => {
    expect(researchStageLabel("experiment_design", "假说形成")).toBe("假说形成");
    expect(researchStageLabel("execution_iteration", "结果核验")).toBe("结果核验");
    expect(researchStageLabel("experiment_design")).toBe("实验设计");
  });
});
