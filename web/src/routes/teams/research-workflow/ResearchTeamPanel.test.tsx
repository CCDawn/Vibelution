import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import { ResearchTeamPanel } from "./ResearchTeamPanel";

function renderPanel(language: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ResearchTeamPanel
          teamId="research-team"
          teamName="科研团队"
          linkedChatRoomId=""
          run={null}
          projection={null}
          effectiveBindings={null}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ResearchTeamPanel", () => {
  it("mounts the research project switcher on the main-path team panel", () => {
    const html = renderPanel();
    expect(html).toContain("研究项目");
    expect(html).toContain("当前研究项目");
    expect(html).toContain("团队治理");
    expect(html).toContain("绑定覆盖");
    expect(html).toContain("未创建运行");
    expect(html).toContain("团队尚未关联讨论会话");
  });

  it("renders English chrome when the shell language is en", () => {
    const html = renderPanel("en");
    expect(html).toContain("Research projects");
    expect(html).toContain("Current research project");
    expect(html).toContain("Team governance");
    expect(html).toContain("Binding coverage");
    expect(html).toContain("No run yet");
    expect(html).toContain("No chat room is linked to this team yet");
  });
});
