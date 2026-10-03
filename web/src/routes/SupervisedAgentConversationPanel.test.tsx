import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { SupervisedAgentConversationPanel } from "./SupervisedAgentConversationPanel";

describe("SupervisedAgentConversationPanel missing evidence", () => {
  it.each(["zh", "en"] as const)("describes missing session evidence without inventing a not-started state in %s", (lang) => {
    const client = new QueryClient();
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <SupervisedAgentConversationPanel
            compact
            members={[{
              role: "baseline", label: "基线", name: "Baseline", model: "", modelId: "", agentId: "agent-baseline",
              status: "configured", chatRoute: "", configRoute: "",
            }]}
            selectedRole="baseline"
            fallbackMessages={[]}
            taskSummary=""
            isLive={false}
            lang={lang}
            roleLabel={(role) => role || ""}
            roleDescription={() => ""}
            statusLabel={(status) => status}
            onSelectRole={() => undefined}
            onFollowLive={() => undefined}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    client.clear();
    expect(markup).toContain(lang === "zh" ? "暂无会话记录" : "has no linked session record");
    expect(markup).not.toContain(lang === "zh" ? "尚未启动" : "has not started");
    expect(markup).toContain(lang === "zh" ? "不会借用其他 Agent 的消息" : "without borrowing another Agent&#x27;s messages");
  });
});
