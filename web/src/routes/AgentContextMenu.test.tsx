import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AgentInstance, SessionSummary } from "../api/types";
import {
  AgentContextMenu,
  agentCanArchiveFromContextMenu,
  agentContextMenuStyle,
} from "./AgentContextMenu";

function agent(metadata: Record<string, unknown> = {}): AgentInstance {
  return {
    agentId: "agent-1",
    agentCode: "A001",
    displayName: "周望舒",
    status: "active",
    metadata,
  } as AgentInstance;
}

function session(): SessionSummary {
  return {
    id: "session-1",
    title: "最近会话",
    status: "ready",
    taskSummary: "",
    lastActive: "2026-07-20T01:02:00.000Z",
    updatedAt: "2026-07-20T01:02:00.000Z",
    currentPhase: "ready",
  };
}

describe("AgentContextMenu", () => {
  it("offers Agent-scoped actions without destructive session actions", () => {
    const markup = renderToStaticMarkup(
      <AgentContextMenu
        createPending={false}
        archivePending={false}
        lang="zh"
        state={{ agent: agent(), latestSession: session(), x: 24, y: 32 }}
        onArchive={() => undefined}
        onCreateSession={() => undefined}
        onOpenConfig={() => undefined}
        onOpenLatest={() => undefined}
      />,
    );

    expect(markup).toContain('role="menu"');
    expect(markup).toContain('aria-label="Agent 操作"');
    expect(markup).toContain('data-agent-context-menu="agent-1"');
    expect(markup).toContain("打开最近会话");
    expect(markup).toContain("新建会话");
    expect(markup).toContain("打开 Agent 设置");
    expect(markup).toContain("安全归档");
    expect(markup).not.toContain("彻底删除");
    expect(markup).not.toContain("清空");
    expect(markup.match(/role="menuitem"/g)?.length).toBe(4);
  });

  it("disables opening when the Agent has no session", () => {
    const markup = renderToStaticMarkup(
      <AgentContextMenu
        createPending
        archivePending={false}
        lang="en"
        state={{ agent: agent(), latestSession: null, x: 24, y: 32 }}
        onArchive={() => undefined}
        onCreateSession={() => undefined}
        onOpenConfig={() => undefined}
        onOpenLatest={() => undefined}
      />,
    );

    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("Open latest session");
    expect(markup).toContain("Creating session");
    expect(markup.match(/disabled=""/g)?.length).toBe(2);
  });

  it("hides archive for protected Agents and exposes pending state for eligible Agents", () => {
    expect(agentCanArchiveFromContextMenu(agent({ protected: true }))).toBe(false);
    expect(agentCanArchiveFromContextMenu(agent({ fixedRole: true }))).toBe(false);
    expect(agentCanArchiveFromContextMenu(agent())).toBe(true);

    const protectedMarkup = renderToStaticMarkup(
      <AgentContextMenu
        archivePending={false}
        createPending={false}
        lang="zh"
        state={{ agent: agent({ protected: true }), latestSession: session(), x: 24, y: 32 }}
        onArchive={() => undefined}
        onCreateSession={() => undefined}
        onOpenConfig={() => undefined}
        onOpenLatest={() => undefined}
      />,
    );
    expect(protectedMarkup).not.toContain("安全归档");

    const pendingMarkup = renderToStaticMarkup(
      <AgentContextMenu
        archivePending
        createPending={false}
        lang="zh"
        state={{ agent: agent(), latestSession: session(), x: 24, y: 32 }}
        onArchive={() => undefined}
        onCreateSession={() => undefined}
        onOpenConfig={() => undefined}
        onOpenLatest={() => undefined}
      />,
    );
    expect(pendingMarkup).toContain('aria-busy="true"');
    expect(pendingMarkup).toContain("正在归档");
  });

  it("clamps the menu inside the visible viewport", () => {
    expect(agentContextMenuStyle({ x: 900, y: 700 }, { width: 960, height: 720 })).toEqual({
      left: 772,
      top: 544,
    });
    expect(agentContextMenuStyle({ x: 24, y: 32 }, undefined)).toEqual({
      left: 24,
      top: 32,
    });
  });
});
