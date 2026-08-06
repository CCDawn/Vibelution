import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent, AgentInboxMessage } from "../api/types";
import { AgentActivityHistoryPanel, type AgentActivityHistoryPanelCopy } from "./AgentActivityHistoryPanel";

const copy: AgentActivityHistoryPanelCopy = {
  sessions: "会话",
  logs: "更新",
  activityPane: "活动",
  activityTimeline: "活动记录",
  loading: "加载中",
  activityTimelineEmpty: "暂无活动",
  openSession: "打开会话",
  openLogs: "打开日志",
  focusMessage: "定位消息",
  runHistoryTitle: "运行记录",
  parentRuns: "主运行",
  subAgentRuns: "子运行",
  maxDepth: "深度",
  runHistoryLoading: "加载运行记录",
  noRunHistory: "暂无运行记录",
  communication: "通信",
  inboxTitle: "收件箱",
  consumeAllMessages: "全部处理",
  consumingMessage: "处理中",
  inboxLoading: "加载收件箱",
  consumeMessage: "处理",
  wakeStatus: "唤醒",
  inboxEmpty: "暂无消息",
};

describe("AgentActivityHistoryPanel", () => {
  it("moves session and activity metadata to focusable tooltip triggers", () => {
    const markup = renderToStaticMarkup(
      <AgentActivityHistoryPanel
        agent={{
          directSessionId: "session-1",
          workspacePath: "C:\\workspace",
          updatedAt: "2026-08-06T08:00:00Z",
        } as AgentConfigWorkspaceAgent}
        copy={copy}
        lang="zh"
        activityTimeline={[{
          id: "activity-1",
          kind: "run",
          title: "完成检索",
          body: "已整理候选资料",
          meta: "运行 RUN-001",
          timestamp: "2026-08-06T08:00:00Z",
          sessionId: "session-1",
          messageId: "",
          canOpenLogs: false,
          evidence: null,
        }]}
        isActivityLoading={false}
        runHistory={undefined}
        isRunHistoryLoading={false}
        inboxMessages={[{
          messageId: "message-1",
          sourceAgentName: "证据 Agent",
          createdAt: "2026-08-06T08:00:00Z",
          kind: "agent_message",
          summary: "证据包已更新",
          threadId: "thread-1",
          delivery: { wakeStatus: "pending" },
        } as AgentInboxMessage]}
        isInboxLoading={false}
        inboxPendingCount={1}
        focusedMessageId=""
        pendingMessageId=""
        isConsumeAllPending={false}
        onOpenSession={() => undefined}
        onOpenLogs={() => undefined}
        onFocusMessage={() => undefined}
        onConsumeAllMessages={() => undefined}
        onConsumeInboxMessage={() => undefined}
      />,
    );

    expect(markup).toContain("session-1");
    expect(markup).toContain("完成检索");
    expect(markup).toContain("证据 Agent");
    expect(markup).toContain('tabindex="0"');
    expect(markup).not.toContain("<small");
    expect(markup).not.toContain("state-success");
  });
});
