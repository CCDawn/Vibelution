/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import {
  ConversationFollowupQueueBar,
  FollowupQueueTogglePauseContext,
} from "./ConversationFollowupQueueBar";
import { ConversationView } from "./ConversationView";
import type { ComposerQueueItem } from "./composerFollowupQueueModel";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function setNativeValue(element: HTMLInputElement, value: string) {
  const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  proto?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("ConversationFollowupQueueBar", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  it("withdraws and saves edits on the live queue bar", async () => {
    const onUpdate = vi.fn();
    const onRemove = vi.fn();
    const onMove = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[
            { id: "q-1", text: "先不要改测试" },
            { id: "q-2", text: "登录失败用中文提示" },
          ]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          onUpdate={onUpdate}
          onRemove={onRemove}
          onMove={onMove}
        />,
      );
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="撤回这条排队"]')?.click();
    });
    expect(onRemove).toHaveBeenCalledWith("q-1");

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="修改这条排队"]')?.click();
    });
    const editor = container?.querySelector<HTMLInputElement>('input[aria-label="修改这条排队 1"]');
    expect(editor).toBeTruthy();
    await act(async () => {
      setNativeValue(editor!, "先不要改测试，只汇报改了哪些文件。");
      const save = Array.from(container?.querySelectorAll("button") ?? []).find((button) => button.textContent === "保存");
      save?.click();
    });
    expect(onUpdate).toHaveBeenCalledWith("q-1", "先不要改测试，只汇报改了哪些文件。");
  });

  it("shows a system return in the queue without edit or steer controls", async () => {
    const onRemove = vi.fn();
    const onSteer = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[{ id: "notice-1", text: "后台任务完成", kind: "task_notification", canSteer: false }]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          steerLabel="立刻引导"
          onUpdate={vi.fn()}
          onRemove={onRemove}
          onMove={vi.fn()}
          onSteer={onSteer}
        />,
      );
    });

    expect(container?.textContent).toContain("后台");
    expect(container?.textContent).toContain("后台任务完成");
    expect(container?.querySelector('button[aria-label="修改这条排队"]')).toBeNull();
    expect(container?.querySelector('button[aria-label="立刻引导"]')).toBeNull();
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="撤回这条排队"]')?.click();
    });
    expect(onRemove).toHaveBeenCalledWith("notice-1");
    expect(onSteer).not.toHaveBeenCalled();
  });

  it("toggles pause and resume per queued item and weakens paused rows", async () => {
    const onTogglePause = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[
            { id: "q-1", text: "正常排队", status: "queued" },
            { id: "q-2", text: "暂停的排队", status: "paused" },
          ]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          onUpdate={() => undefined}
          onRemove={() => undefined}
          onMove={() => undefined}
          onTogglePause={onTogglePause}
        />,
      );
    });

    const pauseButton = container?.querySelector<HTMLButtonElement>('button[aria-label="暂停发送"]');
    const resumeButton = container?.querySelector<HTMLButtonElement>('button[aria-label="恢复发送，排到队尾"]');
    expect(pauseButton).not.toBeNull();
    expect(resumeButton).not.toBeNull();
    // The paused row is visually weakened and labeled.
    expect(container?.querySelector('[class*="followupQueueRowPaused"]')).not.toBeNull();
    expect(container?.textContent).toContain("已暂停");

    await act(async () => {
      pauseButton?.click();
    });
    expect(onTogglePause).toHaveBeenCalledWith("q-1", true);

    await act(async () => {
      resumeButton?.click();
    });
    expect(onTogglePause).toHaveBeenCalledWith("q-2", false);
  });

  it("keeps paused rows editable, withdrawable and reorderable", async () => {
    const onUpdate = vi.fn();
    const onRemove = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[{ id: "q-1", text: "暂停的排队", status: "paused" }]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          onUpdate={onUpdate}
          onRemove={onRemove}
          onMove={() => undefined}
          onTogglePause={() => undefined}
        />,
      );
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="撤回这条排队"]')?.click();
    });
    expect(onRemove).toHaveBeenCalledWith("q-1");

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="修改这条排队"]')?.click();
    });
    const editor = container?.querySelector<HTMLInputElement>('input[aria-label="修改这条排队 1"]');
    expect(editor).toBeTruthy();
    await act(async () => {
      setNativeValue(editor!, "暂停的排队改文本");
      const save = Array.from(container?.querySelectorAll("button") ?? []).find((button) => button.textContent === "保存");
      save?.click();
    });
    expect(onUpdate).toHaveBeenCalledWith("q-1", "暂停的排队改文本");
  });

  it("hides the pause toggle for blocked rows and without a handler", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[{ id: "q-1", text: "失败的排队", status: "blocked" }]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          onUpdate={() => undefined}
          onRemove={() => undefined}
          onMove={() => undefined}
          onTogglePause={() => undefined}
        />,
      );
    });
    expect(container?.querySelector('button[aria-label="暂停发送"]')).toBeNull();

    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[{ id: "q-1", text: "正常排队", status: "queued" }]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          onUpdate={() => undefined}
          onRemove={() => undefined}
          onMove={() => undefined}
        />,
      );
    });
    expect(container?.querySelector('button[aria-label="暂停发送"]')).toBeNull();
  });

  it("receives the pause action from the workbench context provider", async () => {
    const onTogglePause = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <FollowupQueueTogglePauseContext.Provider value={onTogglePause}>
          <ConversationFollowupQueueBar
            items={[{ id: "q-1", text: "正常排队", status: "queued" }]}
            lang="zh"
            editLabel="修改这条排队"
            withdrawLabel="撤回这条排队"
            onUpdate={() => undefined}
            onRemove={() => undefined}
            onMove={() => undefined}
          />
        </FollowupQueueTogglePauseContext.Provider>,
      );
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="暂停发送"]')?.click();
    });
    expect(onTogglePause).toHaveBeenCalledWith("q-1", true);
  });

  it("labels queued attachment counts neutrally", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[
            { id: "q-1", text: "带附件的排队", attachmentCount: 2 },
          ]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          onUpdate={() => undefined}
          onRemove={() => undefined}
          onMove={() => undefined}
        />,
      );
    });

    // Attachment chip is a VTooltip trigger now (no native title attribute).
    const chip = container.querySelector('[data-slot="tooltip-trigger"]');
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toContain("2");
  });

  it("collapses long queues behind an expand toggle", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <ConversationFollowupQueueBar
          items={[
            { id: "q-1", text: "第一条" },
            { id: "q-2", text: "第二条" },
            { id: "q-3", text: "第三条" },
            { id: "q-4", text: "第四条" },
            { id: "q-5", text: "第五条" },
          ]}
          lang="zh"
          editLabel="修改这条排队"
          withdrawLabel="撤回这条排队"
          onUpdate={() => undefined}
          onRemove={() => undefined}
          onMove={() => undefined}
        />,
      );
    });

    expect(container.textContent).toContain("排队中 · 5 条");
    expect(container.textContent).not.toContain("第五条");

    await act(async () => {
      Array.from(container.querySelectorAll("button"))
        .find((button) => button.textContent === "另有 1 条 · 展开")
        ?.click();
    });

    expect(container.textContent).toContain("第五条");
    expect(container.textContent).toContain("收起");
  });
});

describe("ConversationView follow-up queue actions", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  function renderBusyComposer(options: {
    composerValue: string;
    followupQueue?: ComposerQueueItem[];
    onSubmit: () => void;
  }) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    return act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <ConversationView
            sessionId="session-1"
            title="Session"
            phase="running"
            messages={[]}
            showHeader={false}
            showSessionOverview={false}
            showComposer
            defaultFileContext="workspace"
            composerValue={options.composerValue}
            composerPlaceholder=""
            composerDisabled={false}
            composerActionMode="stop"
            composerActionDisabled={false}
            composerPending={false}
            followupQueue={options.followupQueue}
            onComposerChange={() => undefined}
            onSubmit={options.onSubmit}
            onStop={() => undefined}
          />
        </QueryClientProvider>,
      );
    });
  }

  it("submits queue and immediate-steer from the running composer", async () => {
    const onSubmit = vi.fn();
    await renderBusyComposer({
      composerValue: "先不要改测试",
      onSubmit,
    });
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="排队"]')?.click();
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);

    onSubmit.mockClear();
    await renderBusyComposer({
      composerValue: "",
      followupQueue: [{ id: "q-1", text: "先不要改测试" }],
      onSubmit,
    });
    expect(container?.textContent).toContain("排队中 · 1 条");
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="立刻引导"]')?.click();
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("submits the same queue action from Enter on the running composer", async () => {
    const onSubmit = vi.fn();
    await renderBusyComposer({
      composerValue: "先不要改测试",
      onSubmit,
    });
    const textarea = container?.querySelector("textarea");
    expect(textarea).toBeTruthy();
    await act(async () => {
      textarea?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

describe("ConversationView follow-up queue state harness", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  it("keeps queue edits on the bar without writing the transcript", async () => {
    function Harness() {
      const [queue, setQueue] = useState<ComposerQueueItem[]>([
        { id: "q-1", text: "先不要改测试" },
      ]);
      return (
        <>
          <output data-testid="queue-count">{queue.length}</output>
          <ConversationFollowupQueueBar
            items={queue}
            lang="zh"
            editLabel="修改这条排队"
            withdrawLabel="撤回这条排队"
            onUpdate={(id, text) => {
              setQueue((current) => current.map((item) => (item.id === id ? { ...item, text } : item)));
            }}
            onRemove={(id) => {
              setQueue((current) => current.filter((item) => item.id !== id));
            }}
            onMove={() => undefined}
          />
        </>
      );
    }

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness />);
    });
    expect(container.querySelector('[data-testid="queue-count"]')?.textContent).toBe("1");

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('button[aria-label="撤回这条排队"]')?.click();
    });
    expect(container.querySelector('[data-testid="queue-count"]')?.textContent).toBe("0");
    expect(container.querySelector('[aria-label="待发送队列"]')).toBeNull();
  });
});
