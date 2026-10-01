/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CONVERSATION_RUNNING_TASKS_POLL_MS, ConversationRunningTasks } from "./ConversationRunningTasks";
import { queryKeys } from "../../api/queryKeys";
import type { RuntimeTaskCard, RuntimeTaskListPayload } from "../../api/runtimeTasks";

const runtimeApi = vi.hoisted(() => ({
  listRuntimeTasksRevisionAware: vi.fn(),
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

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SESSION_ID = "session-1";

function task(overrides: Partial<RuntimeTaskCard> & { taskId: string }): RuntimeTaskCard {
  return {
    kind: "child_session",
    status: "running",
    title: `任务 ${overrides.taskId}`,
    parentSessionId: SESSION_ID,
    childSessionId: "",
    startedAt: new Date(Date.now() - 30_000).toISOString(),
    endedAt: "",
    summary: "",
    outputPath: "",
    ...overrides,
  };
}

function listPayload(running: RuntimeTaskCard[]): RuntimeTaskListPayload {
  return {
    revision: "rev-1",
    running,
    ended: { items: [], total: 0, nextCursor: "" },
  };
}

describe("ConversationRunningTasks", () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;

  /**
   * Seeds the list cache before mount so the first render already shows the
   * rows: DOM assertions stay deterministic instead of racing act flushes.
   * The polled refetch resolves the same payload, so later poll beats cannot
   * wipe the seeded rows out from under the assertions.
   */
  async function mountStrip(seed: RuntimeTaskListPayload) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    runtimeApi.listRuntimeTasksRevisionAware.mockResolvedValue(seed);
    queryClient.setQueryData(queryKeys.runtimeTasks("", SESSION_ID), seed);
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <ConversationRunningTasks sessionId={SESSION_ID} />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });
    return queryClient;
  }

  /** Settles async chains (list fetch, mutation): yield, then drain via act. */
  async function flushUntil(predicate: () => boolean, tries = 20) {
    for (let i = 0; i < tries && !predicate(); i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await act(async () => {});
    }
  }

  function testButton(testId: string): HTMLButtonElement {
    const found = host?.querySelector<HTMLButtonElement>(`[data-testid="${testId}"]`);
    expect(found, `button "${testId}" should exist`).toBeTruthy();
    return found!;
  }

  beforeEach(() => {
    pollingState.visible = true;
    runtimeApi.listRuntimeTasksRevisionAware.mockReset().mockResolvedValue(listPayload([]));
    runtimeApi.stopRuntimeTask.mockReset().mockResolvedValue({
      accepted: true,
      taskId: "task-1",
      status: "stopping",
    });
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

  it("renders nothing when no runtime tasks are running", async () => {
    await mountStrip(listPayload([]));
    await flushUntil(() => runtimeApi.listRuntimeTasksRevisionAware.mock.calls.length > 0);
    // The poll is session-scoped and active-only.
    expect(runtimeApi.listRuntimeTasksRevisionAware).toHaveBeenCalledWith(
      expect.objectContaining({ status: "active", parentSessionId: SESSION_ID }),
      expect.anything(),
      expect.anything(),
    );
    expect(host?.querySelector('[data-conversation-running-tasks="true"]')).toBeNull();
    expect(host?.textContent).toBe("");
  });

  it("renders one compact row per running task with kind, title, elapsed and jump links", async () => {
    await mountStrip(
      listPayload([
        task({
          taskId: "task-child",
          kind: "child_session",
          title: "子任务：调研资料",
          childSessionId: "child-session-1",
        }),
        task({
          taskId: "task-cli",
          kind: "cli_agent",
          title: "CLI 修复构建",
        }),
      ]),
    );
    await flushUntil(() => Boolean(host?.querySelector('[data-conversation-running-tasks="true"]')));

    const childRow = host!.querySelector('[data-testid="conversation-running-task-task-child"]');
    expect(childRow, "child session row should exist").toBeTruthy();
    expect(childRow!.textContent).toContain("子任务：调研资料");
    expect(childRow!.textContent).toContain("子会话");
    expect(childRow!.querySelector('[data-testid="conversation-running-task-elapsed-task-child"]')?.textContent)
      .toMatch(/^3[01]s$/);
    const childLink = childRow!.querySelector<HTMLAnchorElement>(
      '[data-testid="conversation-running-task-open-task-child"]',
    );
    expect(childLink?.getAttribute("href")).toBe("/chat?session=child-session-1");

    const cliRow = host!.querySelector('[data-testid="conversation-running-task-task-cli"]');
    expect(cliRow!.textContent).toContain("CLI agent");
    const cliLink = cliRow!.querySelector<HTMLAnchorElement>(
      '[data-testid="conversation-running-task-open-task-cli"]',
    );
    // Kinds without a child session jump to the aux task center.
    expect(cliLink?.getAttribute("href")).toBe("/aux");
  });

  it("stops a running task through the confirm dialog and keeps 停止中 until the row leaves the running bucket", async () => {
    await mountStrip(listPayload([task({ taskId: "task-1", title: "子任务：调研资料" })]));
    await flushUntil(() => Boolean(host?.querySelector('[data-conversation-running-tasks="true"]')));

    await act(async () => {
      testButton("conversation-running-task-stop-task-1").click();
    });
    const dialog = document.querySelector('[data-vui="dialog-content"]');
    expect(dialog, "confirm dialog should open").toBeTruthy();
    expect(dialog!.textContent).toContain("停止该任务？");
    const confirmButton = [...dialog!.querySelectorAll<HTMLButtonElement>("button")].find(
      (candidate) => candidate.textContent?.includes("停止"),
    );
    expect(confirmButton).toBeTruthy();
    await act(async () => {
      confirmButton!.click();
    });
    await vi.waitFor(() => expect(runtimeApi.stopRuntimeTask).toHaveBeenCalledWith("task-1"));
    await flushUntil(() => Boolean(host?.textContent?.includes("停止中…")));

    // Dialog closes; the row records the intent and the stop button disables
    // until the polled list moves the task out of the running bucket.
    expect(document.querySelector('[data-vui="dialog-content"]')).toBeNull();
    const stopButton = testButton("conversation-running-task-stop-task-1");
    expect(stopButton.textContent).toContain("停止中…");
    expect(stopButton.disabled).toBe(true);
    expect(host!.querySelector('[data-testid="conversation-running-task-task-1"]')?.getAttribute(
      "data-conversation-running-task-stop-requested",
    )).toBe("true");
  });

  it("treats accepted:false stop as intent-not-recorded, not an error", async () => {
    runtimeApi.stopRuntimeTask.mockResolvedValue({ accepted: false, taskId: "task-1", status: "running" });
    await mountStrip(listPayload([task({ taskId: "task-1", title: "子任务：调研资料" })]));
    await flushUntil(() => Boolean(host?.querySelector('[data-conversation-running-tasks="true"]')));

    await act(async () => {
      testButton("conversation-running-task-stop-task-1").click();
    });
    const confirmButton = [...document.querySelectorAll<HTMLButtonElement>('[data-vui="dialog-content"] button')].find(
      (candidate) => candidate.textContent?.includes("停止"),
    );
    await act(async () => {
      confirmButton!.click();
    });
    await vi.waitFor(() => expect(runtimeApi.stopRuntimeTask).toHaveBeenCalledWith("task-1"));
    await flushUntil(() => document.querySelector('[data-vui="dialog-content"]') === null);

    expect(host!.textContent).not.toContain("停止中…");
    expect(testButton("conversation-running-task-stop-task-1").disabled).toBe(false);
  });

  it("ticks the elapsed counter every second while rows are live", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-10-01T12:00:00Z"));
      runtimeApi.listRuntimeTasksRevisionAware.mockResolvedValue(
        listPayload([task({ taskId: "task-1", startedAt: "2026-10-01T11:59:30.000Z" })]),
      );
      await mountStrip(listPayload([task({ taskId: "task-1", startedAt: "2026-10-01T11:59:30.000Z" })]));      const elapsed = () =>
        host!.querySelector('[data-testid="conversation-running-task-elapsed-task-1"]')?.textContent;
      expect(elapsed()).toBe("30s");
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
      expect(elapsed()).toBe("31s");
      expect(CONVERSATION_RUNNING_TASKS_POLL_MS).toBe(4_000);
    } finally {
      vi.useRealTimers();
    }
  });
});
