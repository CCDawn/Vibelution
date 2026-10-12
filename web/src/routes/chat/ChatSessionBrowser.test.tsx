// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentInstance, SessionSummary } from "../../api/types";
import { VuiProvider } from "../../components/vui";
import { markSessionActivitySeen, sessionActivityStamp } from "../sessionActivityIndicator";
import { ChatSessionBrowser, type ChatSessionBrowserProps } from "./ChatSessionBrowser";

function session(id: string, patch: Partial<SessionSummary> = {}): SessionSummary {
  const updatedAt = patch.updatedAt ?? new Date().toISOString();
  return {
    id,
    title: id,
    agentId: "agent-a",
    agentCode: "A-01",
    agentDisplayName: "Research Agent",
    status: "ready",
    taskSummary: `Summary for ${id}`,
    lastActive: updatedAt,
    updatedAt,
    currentPhase: "ready",
    ...patch,
  };
}

const agent = {
  agentId: "agent-a",
  agentCode: "A-01",
  displayName: "Research Agent",
  primaryMode: "research",
  roleKey: "research-agent",
  llmBindings: { dialogue: { modelId: "model-a" } },
  metadata: {},
  avatarImageUrl: "/agent-a.png",
} as AgentInstance;

function props(patch: Partial<ChatSessionBrowserProps> = {}): ChatSessionBrowserProps {
  return {
    sessions: [session("session-a")],
    agentsById: new Map([[agent.agentId, agent]]),
    activeSessionId: null,
    lang: "zh",
    resolveModelLabel: (modelId) => modelId === "model-a" ? "Model A" : undefined,
    onOpen: () => undefined,
    onCreate: () => undefined,
    onRetry: () => undefined,
    ...patch,
  };
}

async function mount(initialProps: ChatSessionBrowserProps) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement("div");
  document.body.append(host);
  const root: Root = createRoot(host);
  await act(async () => {
    root.render(<VuiProvider><ChatSessionBrowser {...initialProps} /></VuiProvider>);
  });
  return {
    host,
    update: async (nextProps: ChatSessionBrowserProps) => act(async () => {
      root.render(<VuiProvider><ChatSessionBrowser {...nextProps} /></VuiProvider>);
    }),
    unmount: async () => {
      await act(async () => root.unmount());
      host.remove();
    },
  };
}

function changeInput(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("ChatSessionBrowser", () => {
  it("filters by session content and status, then opens the selected result", async () => {
    const onOpen = vi.fn();
    const preview = await mount(props({
      sessions: [
        session("compile-report", { title: "Review report", taskSummary: "Compile the final schedule", status: "running" }),
        session("other", { title: "Browse references", taskSummary: "Source notes", status: "ready" }),
      ],
      runtimeRunningSessionIds: ["compile-report"],
      onOpen,
    }));
    try {
      const search = preview.host.querySelector<HTMLInputElement>('input[type="search"]')!;
      await act(async () => changeInput(search, "compile"));
      expect(preview.host.querySelectorAll("[data-session-browser-id]")).toHaveLength(1);
      expect(preview.host.querySelector('[data-session-browser-id="compile-report"]')).not.toBeNull();

      const runningFilter = preview.host.querySelector<HTMLButtonElement>('[data-session-status-filter="running"]')!;
      await act(async () => runningFilter.click());
      const result = preview.host.querySelector<HTMLButtonElement>('[data-session-browser-id="compile-report"]')!;
      await act(async () => result.click());
      expect(onOpen).toHaveBeenCalledOnce();
      expect(onOpen).toHaveBeenCalledWith("compile-report");
    } finally {
      await preview.unmount();
    }
  });

  it("keeps completed sessions in the completed filter after they are read or opened", async () => {
    const timestamp = "2026-10-12T10:00:00.000Z";
    const activeCompleted = session("active-completed", {
      title: "Completed active session",
      status: "completed",
      currentPhase: "completed",
      updatedAt: timestamp,
      lastActive: timestamp,
    });
    const readCompleted = session("read-completed", {
      title: "Completed read session",
      status: "done",
      currentPhase: "done",
      updatedAt: timestamp,
      lastActive: timestamp,
    });
    const stillRunning = session("running-stale-completion", {
      title: "Running session with stale completion status",
      status: "completed",
      currentPhase: "running",
      lastTurnStatus: "running",
      updatedAt: timestamp,
      lastActive: timestamp,
    });
    markSessionActivitySeen(readCompleted.id, sessionActivityStamp(readCompleted));

    const preview = await mount(props({
      sessions: [activeCompleted, readCompleted, stillRunning],
      activeSessionId: activeCompleted.id,
    }));
    try {
      const completedFilter = preview.host.querySelector<HTMLButtonElement>('[data-session-status-filter="completed"]')!;
      await act(async () => completedFilter.click());
      expect([...preview.host.querySelectorAll<HTMLElement>("[data-session-browser-id]")]
        .map((row) => row.dataset.sessionBrowserId))
        .toEqual([activeCompleted.id, readCompleted.id]);
    } finally {
      await preview.unmount();
    }
  });

  it("groups by local day and orders recent sessions first", async () => {
    const now = new Date();
    const todayNewest = new Date(now); todayNewest.setHours(23, 0, 0, 0);
    const todayOlder = new Date(now); todayOlder.setHours(18, 0, 0, 0);
    const yesterday = new Date(now); yesterday.setDate(yesterday.getDate() - 1); yesterday.setHours(15, 0, 0, 0);
    const preview = await mount(props({
      sessions: [
        session("today-older", { updatedAt: todayOlder.toISOString(), lastActive: todayOlder.toISOString() }),
        session("yesterday", { updatedAt: yesterday.toISOString(), lastActive: yesterday.toISOString() }),
        session("today-newest", { updatedAt: todayNewest.toISOString(), lastActive: todayNewest.toISOString() }),
      ],
    }));
    try {
      const today = preview.host.querySelector('[data-session-group="today"]')!;
      expect([...today.querySelectorAll<HTMLElement>("[data-session-browser-id]")].map((row) => row.dataset.sessionBrowserId))
        .toEqual(["today-newest", "today-older"]);
      expect(preview.host.querySelectorAll('[data-session-group="yesterday"] [data-session-browser-id]')).toHaveLength(1);
    } finally {
      await preview.unmount();
    }
  });

  it("shows a no-match state and clears the query", async () => {
    const preview = await mount(props());
    try {
      const search = preview.host.querySelector<HTMLInputElement>('input[type="search"]')!;
      await act(async () => changeInput(search, "no-such-session"));
      expect(preview.host.textContent).toContain("没有找到匹配的会话");
      const clear = [...preview.host.querySelectorAll<HTMLButtonElement>("button")]
        .find((button) => button.textContent?.includes("清除筛选"));
      expect(clear).toBeDefined();
      await act(async () => clear!.click());
      expect(preview.host.querySelector('[data-session-browser-id="session-a"]')).not.toBeNull();
    } finally {
      await preview.unmount();
    }
  });

  it("renders loading and retryable error states", async () => {
    const onRetry = vi.fn();
    const preview = await mount(props({ sessions: [], loading: true, onRetry }));
    try {
      expect(preview.host.querySelector('[data-tone="loading"]')).not.toBeNull();
      await preview.update(props({ sessions: [], error: "Temporary catalog error", onRetry }));
      expect(preview.host.textContent).toContain("Temporary catalog error");
      const retry = [...preview.host.querySelectorAll<HTMLButtonElement>("button")]
        .find((button) => button.textContent?.includes("重试"));
      expect(retry).toBeDefined();
      await act(async () => retry!.click());
      expect(onRetry).toHaveBeenCalledOnce();
    } finally {
      await preview.unmount();
    }
  });
});
