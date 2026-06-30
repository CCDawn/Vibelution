import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../api/types";
import { SessionContextMenu, sessionContextMenuStyle } from "./SessionContextMenu";

function t(key: string) {
  const labels: Record<string, string> = {
    addSessionToReview: "加入评审",
    addSessionToReviewBusy: "会话运行中",
    addingSessionToReview: "添加中",
    deleteSession: "移除会话记录",
    deleteSessionBusy: "会话运行中，先停止后再删除",
    renameSession: "重命名",
  };
  return labels[key] ?? key;
}

function session(): SessionSummary {
  return {
    id: "session-1",
    title: "会话一",
    status: "ready",
    taskSummary: "",
    lastActive: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    currentPhase: "ready",
  };
}

function agentSession(): SessionSummary {
  return {
    ...session(),
    agentId: "agent-1",
    agentDisplayName: "顾明澈",
  };
}

describe("SessionContextMenu", () => {
  it("keeps the action menu compact and accessible", () => {
    const markup = renderToStaticMarkup(
      <SessionContextMenu
        addToReviewDisabled={false}
        addToReviewPending={false}
        deleteDisabled={false}
        lang="zh"
        position={{ x: 24, y: 32 }}
        session={session()}
        t={t}
        onAddToReview={() => undefined}
        onDelete={() => undefined}
        onRename={() => undefined}
      />,
    );

    expect(markup).toContain("role=\"menu\"");
    expect(markup).toContain("aria-label=\"会话操作\"");
    expect(markup.match(/data-vui="button"/g)?.length).toBe(3);
    expect(markup).toContain("加入评审");
    expect(markup).toContain("重命名");
    expect(markup).toContain("移除会话记录");
    expect(markup).not.toContain("打开 Agent 配置");
  });

  it("shows the Agent configuration action for Agent-backed sessions", () => {
    const markup = renderToStaticMarkup(
      <SessionContextMenu
        addToReviewDisabled={false}
        addToReviewPending={false}
        deleteDisabled={false}
        lang="zh"
        position={{ x: 24, y: 32 }}
        session={agentSession()}
        t={t}
        onAddToReview={() => undefined}
        onDelete={() => undefined}
        onOpenAgentConfig={() => undefined}
        onRename={() => undefined}
      />,
    );

    expect(markup).toContain("打开 Agent 配置");
    expect(markup).toContain("title=\"打开当前 Agent 配置\"");
  });

  it("shows pending and busy states without changing the menu structure", () => {
    const markup = renderToStaticMarkup(
      <SessionContextMenu
        addToReviewDisabled
        addToReviewPending
        deleteDisabled
        lang="en"
        position={{ x: 24, y: 32 }}
        session={session()}
        t={t}
        onAddToReview={() => undefined}
        onDelete={() => undefined}
        onRename={() => undefined}
      />,
    );

    expect(markup).toContain("aria-label=\"Session actions\"");
    expect(markup).toContain("添加中");
    expect(markup).toContain("title=\"会话运行中，先停止后再删除\"");
    expect(markup.match(/disabled=""/g)?.length).toBe(2);
  });

  it("clamps the menu inside the visible viewport", () => {
    expect(sessionContextMenuStyle({ x: 900, y: 700 }, { width: 960, height: 720 })).toEqual({
      left: 772,
      top: 556,
    });
    expect(sessionContextMenuStyle({ x: 24, y: 32 }, undefined)).toEqual({
      left: 24,
      top: 32,
    });
  });
});
