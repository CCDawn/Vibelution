import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../api/types";
import sessionContextMenuStyles from "./SessionContextMenu.styles";
import { SessionContextMenu, sessionContextMenuStyle } from "./SessionContextMenu";

function t(key: string) {
  const labels: Record<string, string> = {
    addSessionToReview: "加入评审",
    addSessionToReviewBusy: "会话运行中",
    addingSessionToReview: "添加中",
    deleteSession: "移除会话记录",
    deleteSessionBusy: "会话运行中，先停止后再删除",
    clearSessionHistory: "清空会话内容",
    clearingSessionHistory: "清空中...",
    clearSessionHistoryBusy: "会话运行中，先停止后再清空",
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
        clearHistoryDisabled={false}
        clearHistoryPending={false}
        clearHistoryVisible={false}
        deleteDisabled={false}
        lang="zh"
        position={{ x: 24, y: 32 }}
        session={session()}
        t={t}
        onAddToReview={() => undefined}
        onClearHistory={() => undefined}
        onDelete={() => undefined}
        onRename={() => undefined}
      />,
    );

    expect(markup).toContain("role=\"menu\"");
    expect(markup).toContain("aria-label=\"会话操作\"");
    expect(markup).toContain("aria-orientation=\"vertical\"");
    expect(markup.match(/data-vui="button"/g)?.length).toBe(3);
    expect(markup.match(/aria-hidden="true"/g)?.length).toBe(3);
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
        clearHistoryDisabled={false}
        clearHistoryPending={false}
        clearHistoryVisible
        deleteDisabled={false}
        lang="zh"
        position={{ x: 24, y: 32 }}
        session={agentSession()}
        t={t}
        onAddToReview={() => undefined}
        onClearHistory={() => undefined}
        onDelete={() => undefined}
        onOpenAgentConfig={() => undefined}
        onRename={() => undefined}
      />,
    );

    expect(markup).toContain("打开 Agent 配置");
    expect(markup).toContain('data-slot="tooltip-trigger"');
    expect(markup).not.toContain("title=\"打开当前 Agent 配置\"");
    expect(markup).toContain("清空会话内容");
    expect(markup.match(/data-vui="button"/g)?.length).toBe(5);
  });

  it("shows pending and busy states without changing the menu structure", () => {
    const markup = renderToStaticMarkup(
      <SessionContextMenu
        addToReviewDisabled
        addToReviewPending
        clearHistoryDisabled
        clearHistoryPending
        clearHistoryVisible
        deleteDisabled
        lang="en"
        position={{ x: 24, y: 32 }}
        session={session()}
        t={t}
        onAddToReview={() => undefined}
        onClearHistory={() => undefined}
        onDelete={() => undefined}
        onRename={() => undefined}
      />,
    );

    expect(markup).toContain("aria-label=\"Session actions\"");
    expect(markup).toContain("添加中");
    expect(markup).toContain("aria-busy=\"true\"");
    expect(markup.match(/aria-disabled="true"/g)?.length).toBe(3);
    expect(markup).toContain("id=\"session-context-menu-session-1-add-to-review-reason\"");
    expect(markup).toContain("aria-describedby=\"session-context-menu-session-1-add-to-review-reason\"");
    expect(markup).toContain("id=\"session-context-menu-session-1-delete-reason\"");
    expect(markup).toContain("aria-describedby=\"session-context-menu-session-1-delete-reason\"");
    expect(markup).toContain("id=\"session-context-menu-session-1-clear-history-reason\"");
    expect(markup).toContain("aria-describedby=\"session-context-menu-session-1-clear-history-reason\"");
    expect(markup.match(/class=\"sr-only\"/g)?.length).toBe(3);
    expect(markup).not.toContain("title=\"会话运行中，先停止后再删除\"");
    expect(markup).not.toContain("title=\"清空中...\"");
    expect(markup.match(/disabled=""/g)?.length).toBe(3);
  });

  it("clamps the menu inside the visible viewport", () => {
    expect(sessionContextMenuStyle({ x: 900, y: 700 }, { width: 960, height: 720 })).toEqual({
      left: 772,
      top: 516,
    });
    expect(sessionContextMenuStyle({ x: 24, y: 32 }, undefined)).toEqual({
      left: 24,
      top: 32,
    });
  });

  it("renders as a floating overlay instead of a document-flow action block", () => {
    expect(sessionContextMenuStyles.sessionContextMenu.split(/\s+/)).toContain("fixed");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("z-[80]");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("w-[188px]");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("grid");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("gap-1");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("p-1");
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("shadow-none");
    expect(sessionContextMenuStyles.sessionContextMenuItem).toContain("!w-full");
    expect(sessionContextMenuStyles.sessionContextMenuItem).toContain("justify-start");
    expect(sessionContextMenuStyles.sessionContextMenuItem).toContain("text-left");
    expect(sessionContextMenuStyles.sessionContextMenuItem).toContain("[&_[data-slot=vui-button-content]]:grid");
    expect(sessionContextMenuStyles.sessionContextMenuItem).toContain("[&_[data-slot=vui-button-content]]:grid-cols-[auto_minmax(0,1fr)]");
    expect(sessionContextMenuStyles.sessionContextMenuDanger).toContain("text-[var(--state-error)]");
    expect(sessionContextMenuStyles.sessionContextMenuDanger).not.toContain("text-[var(--accent-warm)]");
  });
});
