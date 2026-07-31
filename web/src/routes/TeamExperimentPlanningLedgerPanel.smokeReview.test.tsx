import { describe, expect, it } from "vitest";

import { boundedSmokeReviewCopy } from "./TeamExperimentPlanningLedgerPanel";

describe("bounded Smoke review copy", () => {
  it("directs proxy-only evidence to the governed evidence follow-up", () => {
    expect(boundedSmokeReviewCopy("needs_review", true, "zh")).toEqual({
      statusLabel: "代理结果 · 需正式证据",
      actionLabel: "查看评审与补证据",
    });
  });

  it("keeps the ordinary human-review copy for a non-proxy run", () => {
    expect(boundedSmokeReviewCopy("needs_review", false, "zh")).toEqual({
      statusLabel: "待人工复核",
      actionLabel: "进入执行与迭代",
    });
  });
});
