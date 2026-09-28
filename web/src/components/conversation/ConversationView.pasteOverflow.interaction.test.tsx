/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
type FakeClipboardData = {
  files: File[];
  types: string[];
  getData: (format: string) => string;
};

function createQueryClient() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
  return queryClient;
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function textOfLength(length: number) {
  return "x".repeat(length);
}

function pasteClipboardData(overrides: Partial<FakeClipboardData> = {}): FakeClipboardData {
  return {
    files: [],
    types: ["text/plain"],
    getData: (format: string) => (format === "text/plain" ? overrides.getData?.("text/plain") ?? "" : ""),
    ...overrides,
  };
}

async function firePasteOnComposerTextarea(
  clipboardData: FakeClipboardData,
  onAddComposerAttachments: (files: File[]) => void,
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root?.render(
      <QueryClientProvider client={createQueryClient()}>
        <ConversationView
          sessionId="session-paste-overflow"
          title="Session"
          phase="running"
          messages={[]}
          showHeader={false}
          showSessionOverview={false}
          showComposer
          composerValue=""
          composerPlaceholder="Type"
          composerDisabled={false}
          composerPending={false}
          defaultFileContext="workspace"
          onComposerChange={() => undefined}
          onSubmit={() => undefined}
          onEditUserMessage={() => undefined}
          onAddComposerAttachments={onAddComposerAttachments}
        />
      </QueryClientProvider>,
    );
  });
  await flush();

  const textarea = container.querySelector("textarea");
  expect(textarea).not.toBeNull();
  const event = new Event("paste", { bubbles: true, cancelable: true }) as Event & {
    clipboardData: FakeClipboardData;
  };
  event.clipboardData = clipboardData;
  await act(async () => {
    textarea?.dispatchEvent(event);
  });
  await flush();

  const noticeElement = container.querySelector('[data-composer-paste-notice="true"]');
  const noticeText = noticeElement?.textContent ?? "";

  await act(async () => {
    root?.unmount();
  });
  container.remove();

  return { defaultPrevented: event.defaultPrevented, noticeText, noticePresent: Boolean(noticeElement) };
}

describe("composer oversized paste conversion", () => {
  it("converts plain text above 15360 characters into a txt attachment with a light notice", async () => {
    const attachments = vi.fn<(files: File[]) => void>();
    const result = await firePasteOnComposerTextarea(
      pasteClipboardData({ getData: () => textOfLength(15361) }),
      attachments,
    );

    expect(result.defaultPrevented).toBe(true);
    expect(attachments).toHaveBeenCalledTimes(1);
    const attached = attachments.mock.calls[0]?.[0] ?? [];
    expect(attached).toHaveLength(1);
    const file = attached[0];
    expect(file).toBeInstanceOf(File);
    expect(file.name).toMatch(/^粘贴文本-\d{8}-\d{6}\.txt$/);
    expect(file.type).toBe("text/plain");
    expect(file.size).toBeGreaterThan(0);
    expect(result.noticePresent).toBe(true);
    expect(result.noticeText).toContain(file.name);
    expect(result.noticeText).toContain("已转为附件");
  });

  it("keeps plain text at or below the threshold in the composer", async () => {
    const attachments = vi.fn<(files: File[]) => void>();
    const result = await firePasteOnComposerTextarea(
      pasteClipboardData({ getData: () => textOfLength(14999) }),
      attachments,
    );

    expect(result.defaultPrevented).toBe(false);
    expect(attachments).not.toHaveBeenCalled();
    expect(result.noticePresent).toBe(false);
  });

  it("lets clipboard file payloads such as images win without conversion", async () => {
    const attachments = vi.fn<(files: File[]) => void>();
    const imageFile = new File(["png"], "clipboard.png", { type: "image/png" });
    const result = await firePasteOnComposerTextarea(
      pasteClipboardData({
        files: [imageFile],
        types: ["text/plain", "Files"],
        getData: () => textOfLength(20000),
      }),
      attachments,
    );

    expect(result.defaultPrevented).toBe(true);
    expect(attachments).toHaveBeenCalledTimes(1);
    const attached = attachments.mock.calls[0]?.[0] ?? [];
    expect(attached).toEqual([imageFile]);
    expect(result.noticePresent).toBe(false);
  });
});
