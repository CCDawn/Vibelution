// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

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
type PanelProps = React.ComponentProps<typeof AgentPerceptionPanel>;

const defaultPanelProps: PanelProps = {
  agentId: "agent-a",
  lang: "zh",
  configuration: configuration(),
  configurationPending: false,
  onRetryConfiguration: () => undefined,
  runtime: runtime(),
  runtimePending: false,
  onRetryRuntime: () => undefined,
  savePending: false,
  onSave: () => undefined,
  onOpenSession: () => undefined,
  cancelPending: false,
  onCancelRun: () => undefined,
};
let currentPanelProps = defaultPanelProps;

function renderPanel({
  config,
  runtimeValue,
  ...props
}: {
  config?: AgentPerceptionConfiguration;
  runtimeValue?: AgentPerceptionRuntime;
} & Partial<Omit<PanelProps, "configuration" | "runtime">> = {}) {
  currentPanelProps = {
    ...defaultPanelProps,
    ...props,
    configuration: config ?? defaultPanelProps.configuration,
    runtime: runtimeValue ?? defaultPanelProps.runtime,
  };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(<AgentPerceptionPanel {...currentPanelProps} />);
  });
  return container;
}

function rerenderPanel(overrides: Partial<PanelProps>) {
  currentPanelProps = { ...currentPanelProps, ...overrides };
  act(() => root?.render(<AgentPerceptionPanel {...currentPanelProps} />));
  return container!;
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

function clickControl(control: HTMLElement | null) {
  if (!control) throw new Error("Missing control");
  act(() => control.click());
}

function findButton(panel: HTMLElement, label: string) {
  return Array.from(panel.querySelectorAll<HTMLButtonElement>("button"))
    .find((button) => button.getAttribute("aria-label") === label || button.textContent?.includes(label)) ?? null;
}

function setSelectValue(select: HTMLSelectElement | null, value: string) {
  if (!select) throw new Error("Missing select");
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function setInputValue(input: HTMLInputElement | null, value: string) {
  if (!input) throw new Error("Missing input");
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    valueSetter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function clickRuntimeDetails(panel: HTMLElement) {
  clickButton(panel.querySelector<HTMLButtonElement>('[aria-label="查看运行事实"]'));
}

function clickSourceMode(panel: HTMLElement, sourceTitle: string, modeLabel: string) {
  clickButton(panel.querySelector<HTMLButtonElement>(`[aria-label="${sourceTitle} · ${modeLabel}"]`));
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  currentPanelProps = defaultPanelProps;
});

describe("AgentPerceptionPanel", () => {
  it("defaults to settings, keeps navigation visible, and folds idle runtime facts until requested", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.sources.personal.mode = "manual";
    const panel = renderPanel({ config: configuration(policy) });
    const settingsTab = Array.from(panel.querySelectorAll<HTMLElement>("[role=tab]"))
      .find((item) => item.textContent?.includes("感知设置"));
    const historyTab = Array.from(panel.querySelectorAll<HTMLElement>("[role=tab]"))
      .find((item) => item.textContent?.includes("运行记录"));

    expect(settingsTab?.getAttribute("data-state")).toBe("active");
    expect(historyTab).not.toBeNull();
    expect(panel.querySelector('[data-vui-layout-id="agent-perception"]')).toBeNull();
    expect(panel.querySelector('[data-testid="perception-source-personal"]')?.textContent)
      .toContain("需本轮用户明确请求");
    expect(panel.querySelector('[data-testid="agent-perception-tab-settings"]')).not.toBeNull();
    expect(panel.querySelector('[data-testid="perception-runtime"]')).toBeNull();
    expect(panel.querySelector('[data-testid="agent-perception-save"]')).not.toBeNull();
    const runtimeToggle = panel.querySelector<HTMLButtonElement>('[aria-label="查看运行事实"]');
    expect(runtimeToggle?.getAttribute("aria-expanded")).toBe("false");
    expect(panel.querySelector('[data-testid="perception-runtime-details"]')).toBeNull();

    clickRuntimeDetails(panel);
    expect(panel.querySelector('[aria-label="收起运行事实"]')?.getAttribute("aria-expanded")).toBe("true");
    expect(panel.querySelector('[data-testid="perception-runtime-details"]')?.textContent).toContain("授权知识库");
    expect(panel.querySelector('[data-testid="perception-runtime-details"]')?.textContent).toContain("最近实际读取");
  });

  it("keeps the complete source modes keyboard-readable in the wide control and native select", () => {
    const panel = renderPanel();
    const sourceTitle = "指定团队";
    const modeNames = ["关闭", "按需查询", "自动感知"];
    for (const modeName of modeNames) {
      expect(panel.querySelector(`[aria-label="${sourceTitle} · ${modeName}"]`)).not.toBeNull();
    }
    const offButton = panel.querySelector<HTMLButtonElement>(`[aria-label="${sourceTitle} · 关闭"]`);
    expect(offButton?.getAttribute("aria-pressed")).toBe("true");

    const compactSelect = panel.querySelector<HTMLSelectElement>(`select[aria-label="${sourceTitle} · 感知方式"]`);
    expect(compactSelect).not.toBeNull();
    expect(compactSelect?.value).toBe("off");

    clickSourceMode(panel, sourceTitle, "自动感知");
    expect(panel.querySelector<HTMLButtonElement>(`[aria-label="${sourceTitle} · 自动感知"]`)?.getAttribute("aria-pressed")).toBe("true");
    expect(panel.querySelector<HTMLSelectElement>(`select[aria-label="${sourceTitle} · 感知方式"]`)?.value).toBe("auto");
  });

  it("keeps the header status tied to the saved policy while the global switch is only a draft", () => {
    const panel = renderPanel();
    const header = panel.querySelector('[data-vui="settings-form-header"] [data-vui="route-header"]');
    expect(header?.textContent).toContain("当前已保存 · 关闭");

    const enabledSwitch = panel.querySelector<HTMLInputElement>('[role="switch"][aria-label="启用感知控制"]');
    clickControl(enabledSwitch);

    expect(enabledSwitch?.checked).toBe(true);
    const updatedHeader = panel.querySelector('[data-vui="settings-form-header"] [data-vui="route-header"]');
    expect(updatedHeader?.textContent).toContain("当前已保存 · 关闭");
    expect(updatedHeader?.textContent).not.toContain("当前已保存 · 开启");
  });

  it("hides background topics and budgets while off, edits topics inline when enabled, and preserves values on close", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.background.topics = ["部署安全"];
    policy.background.intervalMinutes = 90;
    const panel = renderPanel({ config: configuration(policy) });
    const backgroundSwitch = panel.querySelector<HTMLElement>('[role="switch"][aria-label="启用后台调研"]');
    expect(backgroundSwitch).not.toBeNull();
    expect(panel.querySelector('[aria-label="添加一个调研主题"]')).toBeNull();
    expect(panel.querySelector('ul[aria-label="调研主题"]')).toBeNull();
    expect(panel.querySelector('[aria-label="检查间隔（分钟）"]')).toBeNull();
    expect(panel.querySelector('[aria-label="通知策略"]')).not.toBeNull();

    clickControl(backgroundSwitch);
    const topicInput = panel.querySelector<HTMLInputElement>('[aria-label="添加一个调研主题"]');
    expect(topicInput).not.toBeNull();
    expect(panel.querySelector('[aria-label="编辑调研主题"]')).toBeNull();
    expect(panel.querySelector('ul[aria-label="调研主题"]')?.textContent).toContain("部署安全");
    expect(panel.querySelector<HTMLInputElement>('[aria-label="检查间隔（分钟）"]')?.value).toBe("90");
    expect(panel.querySelector('[aria-label="每次最多工具调用"]')).toBeNull();

    const advanced = findButton(panel, "高级用量限制");
    expect(advanced?.getAttribute("aria-expanded")).toBe("false");
    clickButton(advanced);
    expect(advanced?.getAttribute("aria-expanded")).toBe("true");
    const interval = panel.querySelector<HTMLInputElement>('[aria-label="检查间隔（分钟）"]');
    expect(interval?.value).toBe("90");
    expect(panel.querySelector<HTMLInputElement>('[aria-label="每次最多工具调用"]')).not.toBeNull();
    clickButton(advanced);
    expect(panel.querySelector<HTMLInputElement>('[aria-label="每次最多工具调用"]')).toBeNull();
    clickButton(advanced);

    setInputValue(topicInput, "依赖漏洞");
    clickButton(findButton(panel, "添加主题"));
    const switchAfterTopic = panel.querySelector<HTMLElement>('[role="switch"][aria-label="启用后台调研"]');
    clickControl(switchAfterTopic);
    expect(panel.querySelector('[aria-label="添加一个调研主题"]')).toBeNull();
    clickControl(panel.querySelector<HTMLElement>('[role="switch"][aria-label="启用后台调研"]'));
    expect(panel.querySelector('ul[aria-label="调研主题"]')?.textContent).toContain("部署安全");
    expect(panel.querySelector('ul[aria-label="调研主题"]')?.textContent).toContain("依赖漏洞");
    expect(panel.querySelector<HTMLInputElement>('[aria-label="检查间隔（分钟）"]')?.value).toBe("90");
  });

  it("keeps notification policy independently editable when background research is off", () => {
    const saved: AgentPerceptionConfiguration["policy"][] = [];
    const panel = renderPanel({ onSave: (next) => saved.push(next) });
    const notificationPolicy = panel.querySelector<HTMLSelectElement>('[aria-label="通知策略"]');
    expect(notificationPolicy?.disabled).toBe(false);
    setSelectValue(notificationPolicy, "quiet");
    clickButton(panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]'));

    expect(saved).toHaveLength(1);
    expect(saved[0].background.enabled).toBe(false);
    expect(saved[0].notifications.mode).toBe("quiet");
  });

  it("shows the canonical pending-change summary and discard restores the saved policy", () => {
    const panel = renderPanel();
    clickSourceMode(panel, "指定团队", "按需查询");
    clickButton(panel.querySelector<HTMLButtonElement>('[aria-label="查看变更"]'));
    const changes = panel.querySelector('[data-testid="agent-perception-change-summary"]');
    expect(changes?.textContent).toContain("指定团队");
    expect(changes?.textContent).toContain("按需查询");

    clickButton(findButton(panel, "放弃修改"));
    expect(panel.querySelector<HTMLButtonElement>('[aria-label="指定团队 · 关闭"]')?.getAttribute("aria-pressed")).toBe("true");
    expect(panel.querySelector('[data-testid="agent-perception-change-summary"]')).toBeNull();
  });

  it("blocks editing and repeated saves while a save is pending", () => {
    const policy = defaultAgentPerceptionPolicy();
    policy.background.enabled = true;
    policy.background.topics = ["部署安全"];
    const onSave = vi.fn();
    const panel = renderPanel({ config: configuration(policy), onSave });
    setSelectValue(panel.querySelector<HTMLSelectElement>('[aria-label="通知策略"]'), "quiet");
    clickButton(panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]'));
    expect(onSave).toHaveBeenCalledTimes(1);
    rerenderPanel({ savePending: true });

    const teamMode = panel.querySelector<HTMLButtonElement>('[aria-label="指定团队 · 自动感知"]');
    const topic = panel.querySelector<HTMLInputElement>('[aria-label="添加一个调研主题"]');
    const notification = panel.querySelector<HTMLSelectElement>('[aria-label="通知策略"]');
    const save = panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]');

    expect(panel.querySelector("fieldset[disabled]")?.getAttribute("disabled")).not.toBeNull();
    expect(teamMode?.closest("fieldset")?.disabled).toBe(true);
    expect(topic?.closest("fieldset")?.disabled).toBe(true);
    expect(notification?.closest("fieldset")?.disabled).toBe(true);
    expect(save?.disabled).toBe(true);
    clickButton(save);
    clickButton(save);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("retains a failed draft and allows an explicit retry", () => {
    const saved: AgentPerceptionConfiguration["policy"][] = [];
    const panel = renderPanel({ onSave: (next) => saved.push(next) });
    setSelectValue(panel.querySelector<HTMLSelectElement>('[aria-label="通知策略"]'), "quiet");
    rerenderPanel({ saveError: "保存失败，请重试" });

    expect(panel.textContent).toContain("保存失败，请重试");
    expect(panel.querySelector<HTMLSelectElement>('[aria-label="通知策略"]')?.value).toBe("quiet");
    clickButton(panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]'));
    expect(saved).toHaveLength(1);
    expect(saved[0].notifications.mode).toBe("quiet");
  });

  it("lets a first-time unconfigured Agent explicitly save the unchanged off policy", () => {
    const config = configuration();
    config.configured = false;
    const saved: Array<{ policy: AgentPerceptionConfiguration["policy"]; revision: string }> = [];
    const panel = renderPanel({
      config,
      onSave: (policy, revision) => saved.push({ policy, revision }),
    });

    const save = panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]');
    expect(save?.disabled).toBe(false);
    clickButton(save);

    expect(saved).toHaveLength(1);
    expect(saved[0].policy.enabled).toBe(false);
    expect(saved[0].policy.sources.personal.mode).toBe("off");
    expect(saved[0].revision).toBe(config.agentUpdatedAt);
  });

  it("preserves the draft on server revision conflict and reloads only on explicit request", async () => {
    const initial = configuration();
    const onSave = vi.fn();
    const panel = renderPanel({ config: initial, onSave });
    clickSourceMode(panel, "指定团队", "按需查询");

    const latest = configuration();
    latest.agentUpdatedAt = "2026-10-06T00:00:00Z";
    latest.configurationRevision = 2;
    latest.policyFingerprint = "policy-b";
    latest.policy.enabled = true;
    await act(async () => {
      currentPanelProps = { ...currentPanelProps, configuration: latest };
      root?.render(<AgentPerceptionPanel {...currentPanelProps} />);
      await Promise.resolve();
    });

    expect(panel.querySelector('[data-testid="agent-perception-policy-conflict"]')).not.toBeNull();
    expect(panel.querySelector<HTMLButtonElement>('[aria-label="指定团队 · 按需查询"]')?.getAttribute("aria-pressed")).toBe("true");
    expect(panel.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]')?.disabled).toBe(true);
    expect(onSave).not.toHaveBeenCalled();

    clickButton(findButton(panel, "加载最新策略"));
    expect(panel.querySelector('[data-testid="agent-perception-policy-conflict"]')).toBeNull();
    expect(panel.querySelector<HTMLInputElement>('[role="switch"][aria-label="启用感知控制"]')?.checked).toBe(true);
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

    clickSourceMode(panel, "指定团队", "关闭");
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
    clickRuntimeDetails(panel);
    const summary = panel.querySelector('[data-testid="perception-runtime-details"]');

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
    expect(panel.querySelector('[data-testid="perception-runtime-details"]')).not.toBeNull();
    const stopButton = Array.from(panel.querySelectorAll<HTMLButtonElement>("button"))
      .find((button) => button.textContent?.includes("停止后台调研"));

    clickButton(stopButton ?? null);

    expect(cancelledRunIds).toEqual(["server-run-47"]);
  });

  it("auto-opens runtime facts when a runtime refresh fails", () => {
    const panel = renderPanel({ runtimeError: "runtime refresh failed" });

    const details = panel.querySelector('[data-testid="perception-runtime-details"]');
    expect(details).not.toBeNull();
    expect(panel.textContent).toContain("runtime refresh failed");
    expect(Array.from(panel.querySelectorAll<HTMLButtonElement>("button")).some((button) => button.textContent?.includes("重试"))).toBe(true);
  });
});
