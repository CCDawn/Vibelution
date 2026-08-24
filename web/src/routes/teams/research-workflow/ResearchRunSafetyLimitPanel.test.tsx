/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
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
    expect(markup).toContain("三阶段合计");
    expect(markup).toContain("调整上限");
    expect(markup).not.toContain("资料搜集 阶段 token 上限");
    expect(markup).not.toContain("运行时间（小时）");
    expect(markup).not.toContain("Agent 配额");
  });

  it("keeps detailed limits reachable on demand", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ResearchRunSafetyLimitPanel budget={createResearchRunSafetyBudget()} onChange={() => undefined} />,
      );
    });
    const toggle = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("调整上限"));
    expect(toggle).toBeTruthy();

    await act(async () => toggle?.click());
    expect(container.querySelector('[aria-label="资料搜集 阶段 token 上限"]')).not.toBeNull();
    expect(container.textContent).toContain("运行时间（小时）");

    await act(async () => root.unmount());
    container.remove();
  });
});
