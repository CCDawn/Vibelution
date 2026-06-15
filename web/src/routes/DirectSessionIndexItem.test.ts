import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../api/types";
import type { AgentDisplayInfo } from "./agentDisplay";
import {
  buildDirectSessionIndexViewModel,
  isAgentRootSession,
  isChildSession,
  sessionUnreadBadgeTitle,
  sessionUnreadCount,
  sessionModelTooltip,
  sessionAgentMetaLabel,
  sessionListTitle,
  showSessionFunctionLabel,
  showSessionSummaryInline,
} from "./DirectSessionIndexItem";

function makeSession(overrides: Partial<SessionSummary>): SessionSummary {
  return {
    id: "session-1",
    title: "",
    status: "idle",
    taskSummary: "",
    lastActive: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    currentPhase: "idle",
    ...overrides,
  };
}

function display(overrides: Partial<AgentDisplayInfo>): AgentDisplayInfo {
  return {
    name: "Agent",
    functionLabel: "",
    modelLabel: "",
    tone: "chat",
    meta: "",
    ...overrides,
  };
}

describe("DirectSessionIndexItem helpers", () => {
  it("keeps root direct session titles driven by session title before agent display name", () => {
    expect(sessionListTitle(makeSession({ title: "用户改名", agentDisplayName: "Agent 名" }))).toBe("用户改名");
    expect(sessionListTitle(makeSession({ title: "", agentDisplayName: "Agent 名" }))).toBe("Agent 名");
  });

  it("keeps child session titles driven by task result fields before inherited titles", () => {
    expect(sessionListTitle(makeSession({ sessionKind: "child", taskTitle: "子任务标题", title: "父级标题" }))).toBe("子任务标题");
    expect(sessionListTitle(makeSession({
      sessionKind: "child",
      resultCard: { title: "结果卡标题", summary: "摘要" },
      title: "父级标题",
    }))).toBe("结果卡标题");
  });

  it("keeps internal Agent identifiers out of the compact session card", () => {
    expect(sessionAgentMetaLabel(makeSession({ agentCode: " A030 ", agentId: "generated-xiaomi-mimo" }))).toBe("");
    expect(sessionAgentMetaLabel(makeSession({ agentCode: "", agentId: "agent-A017" }))).toBe("");
  });

  it("hides generic or English function labels while keeping meaningful Chinese role labels", () => {
    expect(showSessionFunctionLabel(display({ tone: "chat", functionLabel: "会话入口" }))).toBe(false);
    expect(showSessionFunctionLabel(display({ tone: "chat", functionLabel: "Chat entry" }))).toBe(false);
    expect(showSessionFunctionLabel(display({ tone: "chat", functionLabel: "agent-center-review-session" }))).toBe(false);
    expect(showSessionFunctionLabel(display({ tone: "memory", functionLabel: "知识管理员" }))).toBe(true);
  });

  it("uses model icons without surfacing English model identifiers in the Chinese card tooltip", () => {
    expect(sessionModelTooltip("小米 MiMo V2.5 Pro", "zh")).toBe("模型已绑定");
    expect(sessionModelTooltip("小米模型", "zh")).toBe("模型：小米模型");
    expect(sessionModelTooltip("gpt-5", "en")).toBe("Model: gpt-5");
  });

  it("keeps root session summaries out of the compact card and only allows concise Chinese child summaries", () => {
    expect(showSessionSummaryInline("我按照前面写一份报告", "zh", false)).toBe(false);
    expect(showSessionSummaryInline("暂无摘要", "zh", true)).toBe(false);
    expect(showSessionSummaryInline("Report summary", "zh", true)).toBe(false);
    expect(showSessionSummaryInline("已完成资料整理", "zh", true)).toBe(true);
  });

  it("classifies child sessions and root Agent sessions independently", () => {
    const root = makeSession({ agentId: "agent-root", sessionKind: "main" });
    const child = makeSession({ agentId: "agent-root", sessionKind: "child" });

    expect(isAgentRootSession(root)).toBe(true);
    expect(isChildSession(root)).toBe(false);
    expect(isAgentRootSession(child)).toBe(false);
    expect(isChildSession(child)).toBe(true);
  });

  it("normalizes pending inbox messages into a compact unread badge count", () => {
    expect(sessionUnreadCount(makeSession({ agentInboxPendingCount: 3 }))).toBe(3);
    expect(sessionUnreadCount(makeSession({ agentInboxPendingCount: 0 }))).toBe(0);
    expect(sessionUnreadCount(makeSession({ agentInboxPendingCount: -2 }))).toBe(0);
    expect(sessionUnreadBadgeTitle(3, "zh")).toBe("未读信息：3 条");
    expect(sessionUnreadBadgeTitle(1, "en")).toBe("1 unread message");
    expect(sessionUnreadBadgeTitle(2, "en")).toBe("2 unread messages");
  });

  it("builds the compact direct session item view model for normal sessions", () => {
    const view = buildDirectSessionIndexViewModel({
      addToReviewSucceededLabel: "已加入评审",
      agent: undefined,
      deleteBusyLabel: "会话运行中",
      itemError: "",
      lang: "zh",
      session: makeSession({
        agentCode: "A030",
        agentDisplayName: "顾明澈",
        taskSummary: "",
        title: "小米2.5pro",
      }),
      sessionBusy: false,
    });

    expect(view.sessionTitle).toBe("小米2.5pro");
    expect(view.sessionSummary).toBe("暂无摘要");
    expect(view.sessionAgentMeta).toBe("");
    expect(view.itemMessage).toBe("");
    expect(view.itemIsNotice).toBe(false);
    expect(view.missingAgentMessage).toBe("");
  });

  it("uses child session result summaries before generic fallback copy", () => {
    const view = buildDirectSessionIndexViewModel({
      addToReviewSucceededLabel: "Added",
      agent: undefined,
      deleteBusyLabel: "Busy",
      itemError: "",
      lang: "en",
      session: makeSession({
        resultCard: { title: "Child title", summary: "Report summary" },
        sessionKind: "child",
        taskSummary: "Task summary",
        title: "Inherited title",
      }),
      sessionBusy: false,
    });

    expect(view.sessionTitle).toBe("Child title");
    expect(view.sessionSummary).toBe("Report summary");
  });

  it("marks busy delete reasons and review success messages as notices", () => {
    const busy = buildDirectSessionIndexViewModel({
      addToReviewSucceededLabel: "已加入评审",
      agent: undefined,
      deleteBusyLabel: "会话运行中",
      itemError: "",
      lang: "zh",
      session: makeSession({}),
      sessionBusy: true,
    });
    const success = buildDirectSessionIndexViewModel({
      addToReviewSucceededLabel: "已加入评审",
      agent: undefined,
      deleteBusyLabel: "会话运行中",
      itemError: "已加入评审队列",
      lang: "zh",
      session: makeSession({}),
      sessionBusy: false,
    });

    expect(busy.itemMessage).toBe("会话运行中");
    expect(busy.itemIsNotice).toBe(true);
    expect(success.itemMessage).toBe("已加入评审队列");
    expect(success.itemIsNotice).toBe(true);
  });

  it("keeps missing Agent copy near the direct session view model", () => {
    const view = buildDirectSessionIndexViewModel({
      addToReviewSucceededLabel: "Added",
      agent: undefined,
      deleteBusyLabel: "Busy",
      itemError: "",
      lang: "en",
      session: makeSession({ agentMissing: true, agentStatusMessage: "" }),
      sessionBusy: false,
    });

    expect(view.missingAgentMessage).toBe("Missing valid Agent. This session has no runnable Agent content.");
  });
});
