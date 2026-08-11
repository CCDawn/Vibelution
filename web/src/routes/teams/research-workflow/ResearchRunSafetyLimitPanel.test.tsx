import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ResearchRunSafetyLimitPanel } from "./ResearchRunSafetyLimitPanel";
import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";

describe("ResearchRunSafetyLimitPanel", () => {
  it("presents phase safety limits without introducing Agent quotas", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunSafetyLimitPanel budget={createResearchRunSafetyBudget()} onChange={() => undefined} />,
    );

    expect(markup).toContain("运行安全上限");
    expect(markup).toContain("知识搜集 阶段 token 上限");
    expect(markup).toContain("三阶段合计");
    expect(markup).toContain("运行时间（小时）");
    expect(markup).not.toContain("Agent 配额");
  });
});
