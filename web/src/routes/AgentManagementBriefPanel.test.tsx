import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentManagementBriefPanel } from "./AgentManagementBriefPanel";

describe("AgentManagementBriefPanel", () => {
  it("keeps actions visible while moving status detail into the existing contextual hint", () => {
    const markup = renderToStaticMarkup(
      <AgentManagementBriefPanel
        brief={{
          score: 72,
          statusLabel: "需要处理",
          statusDetail: "还需处理 1 项",
          items: [{ id: "item-1", label: "补充证据", complete: false, pane: "effective" }],
          actions: [{ id: "action-1", label: "查看配置", detail: "检查当前配置来源", pane: "config" }],
        }}
        copy={{
          managementBriefHint: "用于汇总当前管理状态。",
          managementBriefTitle: "管理摘要",
          nextActionsTitle: "下一步",
          nextAllReady: "已全部就绪",
        }}
        onOpenRoute={() => undefined}
        onSelectPane={() => undefined}
      />,
    );

    expect(markup).toContain("需要处理");
    expect(markup).toContain("补充证据");
    expect(markup).toContain("查看配置");
    expect(markup).toContain('aria-label="下一步"');
    expect(markup).not.toContain(">还需处理 1 项<");
    expect(markup).not.toContain("state-success");
  });
});
