// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { defaultAgentPerceptionPolicy } from "./agentPerceptionDraft";
import { AgentPerceptionPanel } from "./AgentPerceptionPanel";
import type { AgentPerceptionConfiguration, AgentPerceptionRuntime } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function configuration(): AgentPerceptionConfiguration {
  return {
    schemaVersion: 1,
    agentId: "agent-a",
    agentUpdatedAt: "2026-10-05T00:00:00Z",
    configurationRevision: 1,
    configured: true,
    policy: defaultAgentPerceptionPolicy(),
    sourceDecisions: [],
    policyFingerprint: "policy-a",
    availableScopes: {
      teams: [],
      knowledgeBases: [{ id: "knowledge-base-a", label: "研究知识库", detail: "Agent 可读" }],
    },
  };
}

function runtime(): AgentPerceptionRuntime {
  return {
    schemaVersion: 1,
    agentId: "agent-a",
    enabled: true,
    status: "completed",
    nextRunAt: "",
    readableSources: [{
      source: "knowledge",
      selectedCount: 1,
      readableCount: 1,
      mode: "auto",
      triggers: { task: true, update: true, background: false },
      requiresUserRequest: false,
    }],
    activeRun: null,
    lastRun: null,
    lastActivity: {
      trigger: "task",
      sources: ["knowledge"],
      readCount: 2,
      resultCount: 1,
      completedAt: "2026-10-05T00:00:00Z",
      sessionId: "session-last",
      turnId: "turn-last",
      runId: "run-last",
    },
    dailyBudget: { date: "2026-10-05", used: 0, limit: 4, remaining: 4 },
    caps: { maxCallsPerRun: 8, maxInputTokensPerRun: 16_000, maxResultChars: 12_000, maxConcurrent: 1 },
    cancelAvailable: false,
    notifications: {
      unreadCount: 2,
      totalCount: 2,
      suppressedCount: 0,
      items: [
        {
          notificationId: "notification-a",
          knowledgeBaseId: "knowledge-base-a",
          knowledgeItemId: "item-a",
          revision: "2",
          contentHash: "hash-a",
          observedAt: "2026-10-05T00:00:00Z",
          sessionId: "session-a",
          turnId: "turn-a",
          delivered: false,
        },
        {
          notificationId: "notification-project",
          source: "projects",
          knowledgeBaseId: "local-project-governance",
          knowledgeItemId: "project-a",
          revision: "3",
          contentHash: "hash-project",
          observedAt: "2026-10-05T00:00:00Z",
          sessionId: "session-project",
          turnId: "turn-project",
          delivered: false,
        },
      ],
    },
    knowledgeScan: { basesScanned: 1, cursorCount: 1, pendingCount: 2 },
    updatedAt: "2026-10-05T00:00:00Z",
  };
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function renderPanel() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <AgentPerceptionPanel
        agentId="agent-a"
        lang="zh"
        configuration={configuration()}
        configurationPending={false}
        onRetryConfiguration={() => undefined}
        runtime={runtime()}
        runtimePending={false}
        onRetryRuntime={() => undefined}
        savePending={false}
        onSave={() => undefined}
        onOpenSession={() => undefined}
        cancelPending={false}
        onCancelRun={() => undefined}
      />,
    );
  });
  return container;
}

function clickTab(label: string) {
  const trigger = Array.from(container?.querySelectorAll<HTMLElement>("[role=tab]") ?? [])
    .find((item) => item.textContent?.includes(label));
  if (!trigger) throw new Error(`Missing tab: ${label}`);
  act(() => trigger.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
});

describe("AgentPerceptionPanel", () => {
  it("defaults to settings, keeps navigation visible, and shows recorded runtime facts in the side panel", () => {
    const panel = renderPanel();
    const settingsTab = Array.from(panel.querySelectorAll<HTMLElement>("[role=tab]"))
      .find((item) => item.textContent?.includes("感知设置"));
    const historyTab = Array.from(panel.querySelectorAll<HTMLElement>("[role=tab]"))
      .find((item) => item.textContent?.includes("运行记录"));

    expect(settingsTab?.getAttribute("data-state")).toBe("active");
    expect(historyTab).not.toBeNull();
    expect(panel.querySelector('[data-vui-layout-id="agent-perception"]')).not.toBeNull();
    expect(panel.querySelector('[data-testid="perception-runtime-summary"]')?.textContent).toContain("授权知识库");
    expect(panel.querySelector('[data-testid="perception-runtime-summary"]')?.textContent).toContain("实际读取来源");
    expect(panel.querySelector('[data-testid="agent-perception-tab-settings"]')).not.toBeNull();
    expect(panel.querySelector('[data-testid="perception-runtime"]')).toBeNull();
  });

  it("shows server-recorded run and update details in the history tab, including project-index notifications", () => {
    const panel = renderPanel();
    clickTab("运行记录");

    const historyTab = Array.from(panel.querySelectorAll<HTMLElement>("[role=tab]"))
      .find((item) => item.textContent?.includes("运行记录"));
    expect(historyTab?.getAttribute("data-state")).toBe("active");
    expect(panel.querySelector('[data-testid="agent-perception-tabs"]')?.textContent).toContain("感知设置");
    expect(panel.querySelector('[data-testid="agent-perception-tab-history"]')).not.toBeNull();
    expect(panel.textContent).toContain("新更新");
    expect(panel.textContent).toContain("研究知识库");
    expect(panel.textContent).toContain("打开关联会话");
    expect(panel.textContent).toContain("session-a");
    expect(panel.textContent).toContain("turn-a");
    expect(panel.textContent).toContain("本地成熟项目索引");
    expect(panel.textContent).toContain("project-a");
    expect(panel.textContent).not.toContain("静音中");
  });
});
