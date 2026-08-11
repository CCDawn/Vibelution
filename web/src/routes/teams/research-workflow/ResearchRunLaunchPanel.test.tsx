import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ResearchRunLaunchPanel } from "./ResearchRunLaunchPanel";

describe("ResearchRunLaunchPanel", () => {
  it("waits for the canonical approved-question list instead of exposing manual contract fields", () => {
    const client = new QueryClient();
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ResearchRunLaunchPanel
          teamId="team-1"
          busy={false}
          onSubmit={async () => undefined}
          onCancel={() => undefined}
        />
      </QueryClientProvider>,
    );

    expect(markup).toContain("加载可启动题目");
    expect(markup).not.toContain("高级运行合同");
    expect(markup).not.toContain("研究简报 Hash");
    expect(markup).not.toContain("数据集引用");
  });
});
