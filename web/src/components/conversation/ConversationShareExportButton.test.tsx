/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearControlToken, seedControlTokenForTests } from "../../api/client";
import { ConversationShareExportButton } from "./ConversationShareExportButton";
import buttonSource from "./ConversationShareExportButton.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("ConversationShareExportButton", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    document.body.innerHTML = "";
    root = null;
    clearControlToken();
    vi.unstubAllGlobals();
  });

  it("composes VButton plus the dialog and stays decoupled from ConversationView", () => {
    expect(buttonSource).toContain("<VButton");
    expect(buttonSource).toContain("<ConversationShareExportDialog");
    expect(buttonSource).toContain("sessionId");
    expect(buttonSource).toContain("messages");
    // This task ships the entry component only; wiring ConversationView is the
    // integrator's move and must not happen implicitly.
    expect(conversationViewSource).not.toContain("ConversationShareExportButton");
    expect(conversationViewSource).not.toContain("ConversationShareExportDialog");
  });

  it("opens the export dialog with the session id and transcript", async () => {
    vi.stubGlobal("fetch", vi.fn());
    seedControlTokenForTests();
    await act(async () => {
      root = createRoot(document.body);
      root.render(
        <ConversationShareExportButton
          sessionId="sess-9"
          messages={[
            { id: "s-message-1", role: "user", content: "问题", timestamp: "t" },
          ] as never}
          language="zh"
        />,
      );
    });
    expect(document.body.textContent).toContain("导出 HTML");

    await act(async () => {
      (Array.from(document.querySelectorAll("button"))
        .find((button) => (button.textContent ?? "").includes("导出 HTML")) ?? null)!.click();
    });
    expect(document.body.textContent).toContain("导出会话为 HTML");
    expect(document.body.textContent).toContain("问题");
    expect(document.querySelector('[data-vui="conversation-share-export-dialog"]')).not.toBeNull();
  });
});
