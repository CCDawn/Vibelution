/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import { ConversationFollowupQueueBar } from "./ConversationFollowupQueueBar";
import { ConversationView } from "./ConversationView";
import type { ComposerQueueItem } from "./composerFollowupQueueModel";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function setNativeValue(element: HTMLTextAreaElement, value: string) {
  const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
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
          queueLabel="排队"
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
    const editor = container?.querySelector<HTMLTextAreaElement>('textarea[aria-label="修改这条排队 1"]');
    expect(editor).toBeTruthy();
    await act(async () => {
      setNativeValue(editor!, "先不要改测试，只汇报改了哪些文件。");
      const save = Array.from(container?.querySelectorAll("button") ?? []).find((button) => button.textContent === "保存");
      save?.click();
    });
    expect(onUpdate).toHaveBeenCalledWith("q-1", "先不要改测试，只汇报改了哪些文件。");
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
    expect(container?.textContent).toContain("排队 1");
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
            queueLabel="排队"
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
