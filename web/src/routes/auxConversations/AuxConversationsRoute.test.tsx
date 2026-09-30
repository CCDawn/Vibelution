/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AUX_TASKS_POLL_MS, AuxConversationsRoute } from "./AuxConversationsRoute";
import { queryKeys } from "../../api/queryKeys";
import type { RuntimeTaskCard, RuntimeTaskListPayload } from "../../api/runtimeTasks";

const runtimeApi = vi.hoisted(() => ({
  listRuntimeTasksRevisionAware: vi.fn(),
  listRuntimeTasks: vi.fn(),
  getRuntimeTask: vi.fn(),
  stopRuntimeTask: vi.fn(),
}));

vi.mock("../../api/runtimeTasks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/runtimeTasks")>();
  return { ...actual, ...runtimeApi };
});

vi.mock("../../i18n/useShellI18n", () => ({
  useShellI18n: () => ({ lang: "zh" as const }),
}));

const pollingState = vi.hoisted(() => ({ visible: true }));

vi.mock("../../app/pollingPolicy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../app/pollingPolicy")>();
  return {
    ...actual,
    usePageVisibility: () => pollingState.visible,
  };
});

vi.mock("../../app/browserTelemetry", () => ({
  collectBrowserPageSnapshot: () => ({}),
  postBrowserTelemetry: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.parse("2026-10-01T12:00:00Z");

function task(overrides: Partial<RuntimeTaskCard> & { taskId: string }): RuntimeTaskCard {
  return {
    kind: "child_session",
    status: "running",
    title: `任务 ${overrides.taskId}`,
    parentSessionId: "parent-session-1",
    childSessionId: "",
    startedAt: new Date(NOW - 30_000).toISOString(),
    endedAt: "",
    summary: "",
    outputPath: "",
    ...overrides,
  };
}

const runningTask = task({
  taskId: "task-running-1",
  kind: "child_session",
  status: "running",
  title: "子任务：调研资料",
  childSessionId: "child-session-1",
  summary: "正在汇总候选资料",
  outputPath: "C:\\tmp\\aux-out.md",
});

const endedTask = task({
  taskId: "task-ended-1",
  kind: "cli_agent",
  status: "succeeded",
  title: "CLI 修复构建",
  childSessionId: "",
  startedAt: new Date(NOW - 3 * 3_600_000).toISOString(),
  endedAt: new Date(NOW - 2 * 3_600_000).toISOString(),
  summary: "已修复 tsc 报错",
});

function listPayload(overrides: Partial<RuntimeTaskListPayload> = {}): RuntimeTaskListPayload {
  return {
    revision: "rev-1",
    running: [runningTask],
    ended: { items: [endedTask], total: 1, nextCursor: "" },
    ...overrides,
  };
}

describe("AuxConversationsRoute", () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;

  /**
   * Seeds the list cache before mount so the first render already shows the
   * sections: DOM assertions stay deterministic instead of racing act flushes.
   * The mount-time background refetch still exercises the queryFn.
   */
  function mountRoute(initialEntry = "/aux", seed: RuntimeTaskListPayload = listPayload()) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(queryKeys.runtimeTasks(""), seed);
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    return act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[initialEntry]}>
            <AuxConversationsRoute />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
  }

  /**
   * Settles async chains (detail fetch, mutation, load-more): yield the event
   * loop first so scheduler-level work runs, then drain it through act.
   */
  async function flushUntil(predicate: () => boolean, tries = 20) {
    for (let i = 0; i < tries && !predicate(); i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await act(async () => {});
    }
  }

  function button(label: string): HTMLButtonElement {
    const found = [...(host?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find(
      (candidate) => candidate.textContent?.includes(label) || candidate.getAttribute("aria-label") === label,
    );
    expect(found, `button "${label}" should exist`).toBeTruthy();
    return found!;
  }

  beforeEach(() => {
    pollingState.visible = true;
    runtimeApi.listRuntimeTasksRevisionAware.mockReset().mockResolvedValue(listPayload());
    runtimeApi.listRuntimeTasks.mockReset().mockResolvedValue(
      listPayload({ revision: "rev-1", ended: { items: [], total: 1, nextCursor: "" } }),
    );
    runtimeApi.getRuntimeTask.mockReset().mockResolvedValue({
      ...runningTask,
      pendingMessageCount: 2,
      timeline: [
        { at: new Date(NOW - 30_000).toISOString(), label: "任务已创建" },
        { at: new Date(NOW - 10_000).toISOString(), status: "running" },
      ],
    });
    runtimeApi.stopRuntimeTask.mockReset().mockResolvedValue({ accepted: true, taskId: "task-running-1", status: "stopping" });
  });

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    host?.remove();
    root = null;
    host = null;
    document.querySelectorAll('[data-vui="dialog-content"]').forEach((node) => node.remove());
  });

  it("renders running and ended sections with status dots, titles, kind badges and relative time", async () => {
    await mountRoute();
    await flushUntil(() => runtimeApi.listRuntimeTasksRevisionAware.mock.calls.length > 0);
    expect(host!.textContent).toContain("正在运行");
    expect(host!.textContent).toContain("已结束");
    expect(host!.querySelector('section[aria-label="正在运行"]')?.textContent).toContain("子任务：调研资料");
    expect(host!.querySelector('section[aria-label="正在运行"]')?.textContent).toContain("子会话");
    expect(host!.querySelector('section[aria-label="已结束"]')?.textContent).toContain("CLI 修复构建");
    expect(host!.querySelector('section[aria-label="已结束"]')?.textContent).toContain("CLI agent");
    expect(host!.textContent).toContain("刚刚");
    // Detail pane starts with the empty selection state.
    expect(host!.textContent).toContain("选择一个任务查看详情");
    // The list fetch receives the default (unfiltered) kind and the seeded
    // payload as the revision baseline.
    expect(runtimeApi.listRuntimeTasksRevisionAware).toHaveBeenCalledWith(
      expect.objectContaining({ status: "all", kind: undefined }),
      expect.objectContaining({ revision: "rev-1" }),
      expect.anything(),
    );
  });

  it("selects a task and shows meta strip, stop button, session link, summary and detail extras", async () => {
    await mountRoute();
    await act(async () => {
      button("子任务：调研资料").click();
    });
    await flushUntil(() => Boolean(host?.textContent?.includes("待处理消息")));
    expect(host!.textContent).toContain("父会话");
    expect(host!.textContent).toContain("正在汇总候选资料");
    expect(host!.textContent).toContain("输出文件");
    expect(host!.textContent).toContain("待处理消息");
    expect(host!.querySelector('section[aria-label="时间线"]')?.textContent).toContain("任务已创建");
    expect(host!.querySelector('section[aria-label="时间线"]')?.textContent).toContain("running");
    // Detail extras always ride the detail endpoint; the card stays list-fresh.
    await vi.waitFor(() => expect(runtimeApi.getRuntimeTask).toHaveBeenCalledWith("task-running-1"));
    const openLink = host!.querySelector<HTMLAnchorElement>('a[href="/chat?session=child-session-1"]');
    expect(openLink, "child session link should exist").toBeTruthy();
    expect(openLink!.textContent).toContain("在会话中打开");
    // Running task exposes the stop affordance.
    expect(button("停止任务")).toBeTruthy();
  });

  it("falls back to the task detail endpoint when the card is outside the list", async () => {
    runtimeApi.getRuntimeTask.mockResolvedValue(runningTask);
    await mountRoute(
      "/aux?taskId=task-running-1",
      listPayload({ running: [], ended: { items: [], total: 0, nextCursor: "" } }),
    );
    await flushUntil(() => Boolean(host?.textContent?.includes("子任务：调研资料")));
    expect(host!.textContent).toContain("子任务：调研资料");
    expect(host!.querySelector('a[href="/chat?session=child-session-1"]')).toBeTruthy();
  });

  it("stops a running task through the confirm dialog and keeps the stopping hint until the status settles", async () => {
    await mountRoute();
    await act(async () => {
      button("子任务：调研资料").click();
    });
    await act(async () => {
      button("停止任务").click();
    });
    const dialog = document.querySelector('[data-vui="dialog-content"]');
    expect(dialog, "confirm dialog should open").toBeTruthy();
    expect(dialog!.textContent).toContain("停止该任务？");
    const confirmButton = [...dialog!.querySelectorAll<HTMLButtonElement>("button")].find(
      (candidate) => candidate.textContent?.includes("停止任务"),
    );
    expect(confirmButton).toBeTruthy();
    await act(async () => {
      confirmButton!.click();
    });
    await vi.waitFor(() => expect(runtimeApi.stopRuntimeTask).toHaveBeenCalledWith("task-running-1"));
    await flushUntil(() => Boolean(host?.textContent?.includes("停止中…")));
    // Dialog closes after an accepted stop; the button flips to 停止中… and the
    // hint stays until the polled status reaches a terminal bucket.
    expect(document.querySelector('[data-vui="dialog-content"]')).toBeNull();
    expect(host!.textContent).toContain("停止中…");
    expect(host!.textContent).toContain("已请求停止，等待任务结束");
  });

  it("loads more ended tasks with the cursor and keeps extras until the revision changes", async () => {
    const secondPageTask = task({
      taskId: "task-ended-2",
      kind: "research_task",
      status: "failed",
      title: "研究任务：补证据",
    });
    runtimeApi.listRuntimeTasks.mockResolvedValue(
      listPayload({ ended: { items: [secondPageTask], total: 2, nextCursor: "" } }),
    );
    await mountRoute(
      "/aux",
      listPayload({ ended: { items: [endedTask], total: 2, nextCursor: "cursor-1" } }),
    );
    expect(host!.querySelector('section[aria-label="已结束"]')?.textContent).not.toContain("研究任务：补证据");
    await act(async () => {
      button("加载更多").click();
    });
    await vi.waitFor(() =>
      expect(runtimeApi.listRuntimeTasks).toHaveBeenCalledWith(
        expect.objectContaining({ status: "ended", cursor: "cursor-1", kind: undefined }),
      ),
    );
    await flushUntil(() =>
      Boolean(host?.querySelector('section[aria-label="已结束"]')?.textContent?.includes("研究任务：补证据")),
    );
    expect(host!.querySelector('section[aria-label="已结束"]')?.textContent).toContain("研究任务：补证据");
  });

  it("polls the list every 4s while visible and stops polling when hidden", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(NOW);
      const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      // A builder, not a constant: re-rendering the same element object lets
      // React bail out of reconciliation entirely, so the visibility flip
      // would never reach the route.
      const renderTree = () => (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/aux"]}>
            <AuxConversationsRoute />
          </MemoryRouter>
        </QueryClientProvider>
      );
      host = document.createElement("div");
      document.body.appendChild(host);
      root = createRoot(host);
      runtimeApi.listRuntimeTasksRevisionAware.mockClear();
      await act(async () => {
        root?.render(renderTree());
      });
      await act(async () => {});
      expect(runtimeApi.listRuntimeTasksRevisionAware).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(AUX_TASKS_POLL_MS + 200);
      });
      expect(runtimeApi.listRuntimeTasksRevisionAware).toHaveBeenCalledTimes(2);

      // Same React tree, same query cache: flipping visibility only re-renders
      // the route, and the interval must be torn down without another fetch.
      pollingState.visible = false;
      await act(async () => {
        root?.render(renderTree());
      });
      await act(async () => {});
      const callsWhenHidden = runtimeApi.listRuntimeTasksRevisionAware.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(AUX_TASKS_POLL_MS * 3);
      });
      expect(runtimeApi.listRuntimeTasksRevisionAware.mock.calls.length).toBe(callsWhenHidden);
    } finally {
      vi.useRealTimers();
    }
  });
});
