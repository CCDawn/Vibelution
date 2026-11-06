// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import { dictionary } from "../../i18n/dictionary";
import { ChatComposerPlusMenu } from "../../routes/chat/ChatComposerPlusMenu";
import { ConversationView } from "./ConversationView";
import type { ConversationViewProps } from "./conversationViewTypes";

vi.mock("../../api/chat", async original => ({ ...await original<typeof import("../../api/chat")>(),
  fetchSessionComposerExample: vi.fn(async () => ({ command: "" })),
  fetchSessionPromptSuggestion: vi.fn(async () => ({ suggestion: "" })),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let container: HTMLDivElement;
afterEach(async () => { await act(async () => root?.unmount()); root = undefined; container?.remove(); });

async function composer(overrides: Partial<ConversationViewProps> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false, staleTime: Infinity } } });
  client.setQueryData(queryKeys.configPublic(), { language: "zh" });
  client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
  client.setQueryData(queryKeys.sessionMessageCuration("single-action"), { items: [] });
  const onSubmit = vi.fn(), onStop = vi.fn(), onSafeGuidance = vi.fn(), onInterruptGuidance = vi.fn();
  let props: Partial<ConversationViewProps> = { onSubmit, onStop, onSafeGuidance, onInterruptGuidance, ...overrides };
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  async function render(next: Partial<ConversationViewProps> = {}) {
    props = { ...props, ...next };
    await act(async () => root!.render(<QueryClientProvider client={client}>
      <ConversationView sessionId="single-action" title="Conversation" phase="running" messages={[]}
        showHeader={false} showSessionOverview={false} composerVariant="codex" composerValue=""
        composerPlaceholder="" composerDisabled={false} composerPending={false} promptSuggestionEnabled={false}
        composerLeadingControl={<ChatComposerPlusMenu lang="zh" showCapabilities={false} showReferences={false} sessionReferences={[]} attachmentDisabled={false} onAddAttachments={vi.fn()} />}
        onComposerChange={vi.fn()} onSubmit={onSubmit} {...props} />
    </QueryClientProvider>));
  }
  await render();
  function primary() {
    const controls = container.querySelectorAll<HTMLButtonElement>('[data-testid="composer-primary-action"]');
    expect(controls).toHaveLength(1);
    return controls[0];
  }
  return { render, primary, onSubmit, onStop, onSafeGuidance, onInterruptGuidance };
}

describe("one composer action across native hosts", () => {
  it("keeps the send action named when a host has no custom submit label", async () => {
    const view = await composer({ composerValue: "你好", submitLabel: "" });
    expect(view.primary().getAttribute("aria-label")).toBe("发送");
  });
  it("changes stop to send guidance as the running draft changes, including an existing queue", async () => {
    const view = await composer({ composerActionMode: "stop", followupQueue: [{ id: "q", text: "queued" }] });
    expect(view.primary().dataset.composerAction).toBe("stop");
    expect(view.primary().querySelector(".lucide-square")).toBeTruthy();
    await view.render({ composerValue: "先核对日程" });
    expect(view.primary().dataset.composerAction).toBe("steer");
    expect(view.primary().querySelector(".lucide-arrow-up")).toBeTruthy();
    await act(async () => view.primary().click());
    expect(view.onSafeGuidance).toHaveBeenCalledOnce();
    expect(view.onSubmit).not.toHaveBeenCalled();
    expect(view.onStop).not.toHaveBeenCalled();
    await view.render({ composerValue: "" });
    await act(async () => view.primary().click());
    expect(view.onStop).toHaveBeenCalledOnce();
  });

  it("shows sending while an optimistic running snapshot precedes the submit ACK, and blocks duplicates", async () => {
    const view = await composer({ composerValue: "你好", composerActionMode: "send" });
    await act(async () => view.primary().click());
    expect(view.onSubmit).toHaveBeenCalledOnce();
    await view.render({ composerActionMode: "stop", composerPending: true, composerSubmitPending: true });
    expect(view.primary().getAttribute("aria-label")).toBe("发送中");
    expect(view.primary().disabled).toBe(true);
    expect(view.primary().getAttribute("aria-busy")).toBe("true");
    expect(view.primary().querySelector(".lucide-loader-circle")).toBeTruthy();
    expect(container.textContent).not.toContain("正在排队");
    await act(async () => view.primary().click());
    expect(view.onSubmit).toHaveBeenCalledOnce();
    expect(view.onStop).not.toHaveBeenCalled();
    await view.render({ composerValue: "", composerPending: false, composerSubmitPending: false });
    expect(view.primary().dataset.composerAction).toBe("stop");
  });

  it("keeps stop confirmation dominant over a simultaneous submit", async () => {
    const view = await composer({ composerActionMode: "stop", composerPending: true, composerSubmitPending: true, composerStopPending: true });
    expect(view.primary().getAttribute("aria-label")).toBe("终止中");
    expect(view.primary().disabled).toBe(true);
    await act(async () => view.primary().click());
    expect(view.onStop).not.toHaveBeenCalled();
  });

  it.each(["attachment", "reference"])("queues a %s-only draft by click and Enter instead of dropping its payload", async kind => {
    const view = await composer({ composerActionMode: "stop",
      ...(kind === "attachment" ? { composerAttachments: [{ id: "file", filename: "note.txt", previewUrl: "", kind: "document" as const, contentType: "text/plain", sizeBytes: 10 }] }
        : { composerReferences: [{ kind: "session", referenceId: "ref", sessionId: "other", title: "Reference" }] }),
    });
    expect(view.primary().dataset.composerAction).toBe("queue");
    expect(view.primary().disabled).toBe(false);
    await act(async () => view.primary().click());
    const textarea = container.querySelector("textarea")!;
    await act(async () => textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })));
    expect(view.onSubmit).toHaveBeenCalledTimes(2);
    expect(view.onSafeGuidance).not.toHaveBeenCalled();
  });

  it("moves queue and interrupt delivery into the host plus menu", async () => {
    const view = await composer({ composerActionMode: "stop", composerValue: "调整安排" });
    expect(container.querySelector('[data-testid="composer-interrupt-guidance"]')).toBeNull();
    const plus = container.querySelector<HTMLButtonElement>('button[aria-label="添加与更多操作"]')
      ?? container.querySelector<HTMLButtonElement>('button[aria-label="更多操作"]')!;
    expect(plus).toBeTruthy();
    await act(async () => plus.click());
    const menu = document.querySelector('[data-testid="chat-composer-plus-delivery"]');
    expect(menu).toBeTruthy();
    const actions = [...menu!.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
    expect(actions.map(node => node.textContent)).toEqual(["排队", "打断并引导"]);
    await act(async () => actions[1].click());
    expect(view.onInterruptGuidance).toHaveBeenCalledOnce();
    expect(view.onSubmit).not.toHaveBeenCalled();
    expect(view.onSafeGuidance).not.toHaveBeenCalled();
    view.primary();
  });
});
