import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import type { AgentInstance } from "../api/types";
import {
  agentCanArchiveFromContextMenu,
  agentContextMenuStyle,
} from "./AgentContextMenu";

const menuSource = readFileSync(resolve(import.meta.dirname, "AgentContextMenu.tsx"), "utf8");

function agent(metadata: Record<string, unknown> = {}): AgentInstance {
  return {
    agentId: "agent-1",
    agentCode: "A001",
    displayName: "周望舒",
    status: "active",
    metadata,
  } as AgentInstance;
}

describe("AgentContextMenu", () => {
  it("offers Agent-scoped actions through VDropdownMenu without session-destructive items", () => {
    expect(menuSource).toContain("VDropdownMenu");
    expect(menuSource).toContain('aria-label={lang === "zh" ? "Agent 操作" : "Agent actions"}');
    expect(menuSource).toContain("打开最近会话");
    expect(menuSource).toContain("新建会话");
    expect(menuSource).toContain("重命名 Agent");
    expect(menuSource).toContain("打开 Agent 设置");
    expect(menuSource).toContain("安全归档");
    expect(menuSource).toContain("data-agent-context-menu");
    expect(menuSource).not.toContain("彻底删除");
    expect(menuSource).not.toContain("清空");
    expect(menuSource).toContain("id: \"rename\"");
    expect(menuSource).toContain("id: \"archive\"");
  });

  it("wires pending labels and busy aria for async actions", () => {
    expect(menuSource).toContain("Creating session");
    expect(menuSource).toContain("正在新建会话");
    expect(menuSource).toContain("正在归档");
    expect(menuSource).toContain("aria-busy");
    expect(menuSource).toContain("createPending");
    expect(menuSource).toContain("renamePending");
    expect(menuSource).toContain("archivePending");
  });

  it("hides archive for protected Agents and exposes pending state for eligible Agents", () => {
    expect(agentCanArchiveFromContextMenu(agent({ protected: true }))).toBe(false);
    expect(agentCanArchiveFromContextMenu(agent({ fixedRole: true }))).toBe(false);
    expect(agentCanArchiveFromContextMenu(agent({ researchOrgRole: "capability_steward" }))).toBe(false);
    expect(agentCanArchiveFromContextMenu(agent())).toBe(true);
    expect(menuSource).toContain("agentCanArchiveFromContextMenu(state.agent)");
    expect(menuSource).toContain("canArchive");
  });

  it("clamps the menu inside the visible viewport", () => {
    expect(agentContextMenuStyle({ x: 900, y: 700 }, { width: 960, height: 720 })).toEqual({
      left: 772,
      top: 508,
    });
    expect(agentContextMenuStyle({ x: 24, y: 32 }, undefined)).toEqual({
      left: 24,
      top: 32,
    });
  });
});
