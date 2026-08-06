import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentRuntimeFocusPanel } from "./AgentRuntimeFocusPanel";

describe("AgentRuntimeFocusPanel", () => {
  it("keeps the operational state visible while moving runtime metadata into focusable disclosure", () => {
    const markup = renderToStaticMarkup(
      <AgentRuntimeFocusPanel
        copy={{
          openLogs: "查看日志",
          openSession: "打开会话",
          runtimeEvidence: "证据",
          runtimeFocus: "运行焦点",
          runtimeLatestRun: "最近运行",
          runtimeNextStep: "下一步",
          runtimeReason: "原因",
          runtimeUpdated: "更新时间",
        }}
        statusLabel="等待人工确认"
        statusReason="需处理"
        tone="blocked"
        summary="等待实验方案确认后继续。"
        latestRunId="RUN-42"
        runReason="实验协议未冻结"
        updatedAt="刚刚"
        nextStep="打开实验方案"
        evidenceReason="监督记录"
        evidenceSceneId="scene-42"
        onOpenLogs={() => undefined}
      />,
    );

    expect(markup).toContain("等待人工确认");
    expect(markup).toContain("需处理");
    expect(markup).toContain("打开实验方案");
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain(">RUN-42<");
    expect(markup).not.toContain(">scene-42<");
  });
});
