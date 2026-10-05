// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { defaultAgentPerceptionPolicy } from "./agentPerceptionDraft";
import { AgentPerceptionPanel } from "./AgentPerceptionPanel";
import type { AgentPerceptionConfiguration, AgentPerceptionRuntime } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function configuration(
  policy = defaultAgentPerceptionPolicy(),
  availableScopes: AgentPerceptionConfiguration["availableScopes"] = {
    teams: [],
    knowledgeBases: [{ id: "knowledge-base-a", label: "研究知识库", detail: "Agent 可读" }],
  },
): AgentPerceptionConfiguration {
  return {
    schemaVersion: 1,
    agentId: "agent-a",
    agentUpdatedAt: "2026-10-05T00:00:00Z",
    configurationRevision: 1,
    configured: true,
    policy,
    sourceDecisions: [],
    policyFingerprint: "policy-a",
    availableScopes,
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

function renderPanel({
  config = configuration(),
  runtimeValue = runtime(),
  onSave = () => undefined,
  onCancelRun = () => undefined,
}: {
  config?: AgentPerceptionConfiguration;
  runtimeValue?: AgentPerceptionRuntime;
  onSave?: (policy: AgentPerceptionConfiguration["policy"], expectedAgentUpdatedAt: string) => void;
  onCancelRun?: (runId: string) => void;
} = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <AgentPerceptionPanel
        agentId="agent-a"
        lang="zh"
        configuration={config}
        configurationPending={false}
        onRetryConfiguration={() => undefined}
        runtime={runtimeValue}
        runtimePending={false}
        onRetryRuntime={() => undefined}
        savePending={false}
        onSave={onSave}
        onOpenSession={() => undefined}
        cancelPending={false}
        onCancelRun={onCancelRun}
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

function clickButton(button: HTMLButtonElement | null) {
  if (!button) throw new Error("Missing button");
  act(() => button.click());
}

function setSelectValue(select: HTMLSelectElement | null, value: string) {
  if (!select) throw new Error("Missing select");
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
});

describe("AgentPerceptionPanel", () => {
  it("defaults to settings, keeps navigation and the concise runtime summary visible", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.sources.personal.mode = "manual";
    const panel = renderPanel({ config: configuration(policy) });
    const settingsTab = Array.from(panel.querySelectorAll<HTMLElement>("[role=tab]"))
      .find((item) => item.textContent?.includes("感知设置"));
    const historyTab = Array.from(panel.querySelectorAll<HTMLElement>("[role=tab]"))
      .find((item) => item.textContent?.includes("运行记录"));

    expect(settingsTab?.getAttribute("data-state")).toBe("active");
    expect(historyTab).not.toBeNull();
    const summary = panel.querySelector('[data-testid="perception-runtime-summary"]');
    expect(panel.querySelector('[data-vui-layout-id="agent-perception"]')).toBeNull();
    expect(summary?.textContent).toContain("授权知识库");
    expect(summary?.textContent).toContain("最近实际读取");
    expect(panel.querySelector('[data-testid="perception-source-personal"]')?.textContent)
      .toContain("需本轮用户明确请求");
    expect(panel.querySelector('[data-testid="agent-perception-tab-settings"]')).not.toBeNull();
    expect(panel.querySelector('[data-testid="perception-runtime"]')).toBeNull();
    expect(panel.querySelector('[data-testid="agent-perception-save"]')).not.toBeNull();

    clickButton(panel.querySelector<HTMLButtonElement>('[aria-label="编辑调研主题"]'));
    expect(panel.querySelector('[aria-label="收起调研主题"]')).not.toBeNull();
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

  it("keeps folded team and knowledge scopes in the saved policy when a source is turned off", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.enabled = true;
    policy.sources.team = {
      mode: "auto",
      teamIds: ["team-a"],
      triggers: { task: true, update: false, background: true },
    };
    policy.sources.knowledge = {
      ...policy.sources.knowledge,
      mode: "auto",
      knowledgeBaseIds: ["knowledge-base-a"],
      triggers: { task: false, update: true, background: false },
    };
    let savedPolicy: AgentPerceptionConfiguration["policy"] | null = null;
    const panel = renderPanel({
      config: configuration(policy, {
        teams: [{ id: "team-a", label: "研究团队", detail: "Agent 可读" }],
        knowledgeBases: [{ id: "knowledge-base-a", label: "研究知识库", detail: "Agent 可读" }],
      }),
      onSave: (nextPolicy) => { savedPolicy = nextPolicy; },
    });

    const teamEdit = panel.querySelector<HTMLButtonElement>('[aria-label="指定团队 · 编辑范围"]');
    clickButton(teamEdit);
    expect(panel.querySelector<HTMLInputElement>('[aria-label="研究团队"]')?.checked).toBe(true);
    clickButton(panel.querySelector<HTMLButtonElement>('[aria-label="指定团队 · 收起范围"]'));

    const knowledgeEdit = panel.querySelector<HTMLButtonElement>('[aria-label="授权知识库 · 编辑范围"]');
    clickButton(knowledgeEdit);
    expect(panel.querySelector<HTMLInputElement>('[aria-label="研究知识库"]')?.checked).toBe(true);
    clickButton(panel.querySelector<HTMLButtonElement>('[aria-label="授权知识库 · 收起范围"]'));

    setSelectValue(panel.querySelector<HTMLSelectElement>('[aria-label="指定团队 · 感知方式"]'), "off");
    clickButton(panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]'));

    expect(savedPolicy?.sources.team.mode).toBe("off");
    expect(savedPolicy?.sources.team.teamIds).toEqual(["team-a"]);
    expect(savedPolicy?.sources.team.triggers).toEqual({ task: true, update: false, background: true });
    expect(savedPolicy?.sources.knowledge.knowledgeBaseIds).toEqual(["knowledge-base-a"]);
    expect(savedPolicy?.sources.knowledge.triggers).toEqual({ task: false, update: true, background: false });
  });

  it("preserves exclusions from an all-authorized knowledge scope after folding and saving", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.enabled = true;
    policy.sources.knowledge = {
      ...policy.sources.knowledge,
      mode: "auto",
      scope: "all_authorized",
      knowledgeBaseIds: [],
      excludedKnowledgeBaseIds: ["knowledge-base-a"],
    };
    let savedPolicy: AgentPerceptionConfiguration["policy"] | null = null;
    const panel = renderPanel({
      config: configuration(policy, {
        teams: [],
        knowledgeBases: [
          { id: "knowledge-base-a", label: "研究知识库", detail: "Agent 可读" },
          { id: "knowledge-base-b", label: "评测知识库", detail: "Agent 可读" },
        ],
      }),
      onSave: (nextPolicy) => { savedPolicy = nextPolicy; },
    });

    clickButton(panel.querySelector<HTMLButtonElement>('[aria-label="授权知识库 · 编辑范围"]'));
    const excluded = panel.querySelector<HTMLInputElement>('[aria-label="评测知识库"]');
    expect(panel.querySelector<HTMLInputElement>('[aria-label="研究知识库"]')?.checked).toBe(true);
    expect(excluded?.checked).toBe(false);
    act(() => excluded?.click());
    expect(excluded?.checked).toBe(true);
    clickButton(panel.querySelector<HTMLButtonElement>('[aria-label="授权知识库 · 收起范围"]'));
    clickButton(panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]'));

    expect(savedPolicy?.sources.knowledge.scope).toBe("all_authorized");
    expect(savedPolicy?.sources.knowledge.knowledgeBaseIds).toEqual([]);
    expect(savedPolicy?.sources.knowledge.excludedKnowledgeBaseIds).toEqual([
      "knowledge-base-a",
      "knowledge-base-b",
    ]);
  });

  it("reports actual runtime sources from server facts rather than the edited policy draft", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.sources.team.mode = "auto";
    policy.sources.team.teamIds = ["team-a"];
    const runtimeValue = runtime();
    runtimeValue.readableSources = [{
      source: "knowledge",
      selectedCount: 1,
      readableCount: 1,
      mode: "auto",
      triggers: { task: true, update: true, background: false },
      requiresUserRequest: false,
    }];
    runtimeValue.lastActivity = {
      ...runtimeValue.lastActivity!,
      sources: ["projects"],
    };
    const panel = renderPanel({ config: configuration(policy), runtimeValue });
    const summary = panel.querySelector('[data-testid="perception-runtime-summary"]');

    expect(summary?.textContent).toContain("当前可用");
    expect(summary?.textContent).toContain("授权知识库");
    expect(summary?.textContent).toContain("最近实际读取");
    expect(summary?.textContent).toContain("本地成熟项目索引");
    expect(summary?.textContent).not.toContain("指定团队");
  });

  it("passes the server-recorded run ID to the stop action in the runtime summary", () => {
    const runtimeValue = runtime();
    runtimeValue.status = "running";
    runtimeValue.cancelAvailable = true;
    runtimeValue.activeRun = {
      runId: "server-run-47",
      topicId: "topic-a",
      status: "running",
      sessionId: "session-active",
      turnId: "turn-active",
      startedAt: "2026-10-05T00:00:00Z",
      finishedAt: null,
      toolCallsUsed: 1,
      inputTokensUsed: 120,
      outputCharsUsed: 40,
      sources: ["knowledge"],
      readCount: 1,
      resultCount: 0,
      sourceReadCallsUsed: 1,
    };
    const cancelledRunIds: string[] = [];
    const panel = renderPanel({
      runtimeValue,
      onCancelRun: (runId) => { cancelledRunIds.push(runId); },
    });
    const stopButton = Array.from(panel.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button.textContent?.includes("停止后台调研"));

    clickButton(stopButton ?? null);

    expect(cancelledRunIds).toEqual(["server-run-47"]);
  });
});
