/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("composer image attachment preview", () => {
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

  it("opens the shared image preview dialog from the pending attachment thumbnail", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <QueryClientProvider client={createQueryClient()}>
          <ConversationView
            sessionId="session-composer-attachment-preview"
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
            composerAttachments={[
              {
                id: "pending-image",
                filename: "pending.png",
                previewUrl: "blob:pending-image",
                sizeBytes: 256,
                contentType: "image/png",
              },
            ]}
            onComposerChange={() => undefined}
            onSubmit={() => undefined}
            onEditUserMessage={() => undefined}
          />
        </QueryClientProvider>,
      );
    });
    await flush();

    const thumbnail = container.querySelector<HTMLButtonElement>('[aria-label="预览附件 pending.png"]');
    expect(thumbnail).not.toBeNull();

    await act(async () => {
      thumbnail?.click();
    });
    // The dialog module is loaded lazily; poll instead of assuming a fixed
    // number of macrotask ticks so a cold transform cache cannot flake this.
    let dialogOpened = false;
    for (let attempt = 0; attempt < 40 && !dialogOpened; attempt += 1) {
      await flush();
      dialogOpened = document.body.textContent?.includes("下载图片") ?? false;
    }

    expect(document.body.textContent).toContain("下载图片");
  });
});
