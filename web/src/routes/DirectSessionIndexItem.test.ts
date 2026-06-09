import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../api/types";
import type { AgentDisplayInfo } from "./agentDisplay";
import {
  isAgentRootSession,
  isChildSession,
  sessionAgentMetaLabel,
  sessionListTitle,
  showSessionFunctionLabel,
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

  it("formats compact Agent metadata without exposing generated display names", () => {
    expect(sessionAgentMetaLabel(makeSession({ agentCode: " A030 ", agentId: "generated-xiaomi-mimo" }))).toBe("Agent A030");
    expect(sessionAgentMetaLabel(makeSession({ agentCode: "", agentId: "agent-A017" }))).toBe("Agent A017");
  });

  it("hides generic chat entry labels while keeping meaningful role labels", () => {
    expect(showSessionFunctionLabel(display({ tone: "chat", functionLabel: "会话入口" }))).toBe(false);
    expect(showSessionFunctionLabel(display({ tone: "chat", functionLabel: "Chat entry" }))).toBe(false);
    expect(showSessionFunctionLabel(display({ tone: "memory", functionLabel: "知识管理员" }))).toBe(true);
  });

  it("classifies child sessions and root Agent sessions independently", () => {
    const root = makeSession({ agentId: "agent-root", sessionKind: "main" });
    const child = makeSession({ agentId: "agent-root", sessionKind: "child" });

    expect(isAgentRootSession(root)).toBe(true);
    expect(isChildSession(root)).toBe(false);
    expect(isAgentRootSession(child)).toBe(false);
    expect(isChildSession(child)).toBe(true);
  });
});
