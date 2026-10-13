/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearControlToken, seedControlTokenForTests } from "../../api/client";
import { ConversationShareExportButton } from "./ConversationShareExportButton";
import buttonSource from "./ConversationShareExportButton.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const transcript = [
  { id: "s-message-1", role: "user", content: "问题", timestamp: "t" },
] as never;

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
          messages={transcript}
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

  it("opens the existing transcript dialog from the session actions menu", async () => {
    await act(async () => {
      root = createRoot(document.body);
      root.render(
        <ConversationShareExportButton
          sessionId="sess-9"
          messages={transcript}
          language="zh"
          presentation="menu"
        />,
      );
    });

    const trigger = document.querySelector<HTMLButtonElement>('button[aria-label="更多会话操作"]');
    expect(trigger).not.toBeNull();
    await act(async () => {
      trigger!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerType: "mouse" }));
    });
    await vi.waitFor(() => expect(document.querySelector('[role="menuitem"]')?.textContent).toContain("导出 HTML"));

    await act(async () => {
      document.querySelector<HTMLElement>('[role="menuitem"]')!.click();
    });
    await vi.waitFor(() => {
      expect(document.querySelector('[data-vui="conversation-share-export-dialog"]')).not.toBeNull();
    });
    expect(document.body.textContent).toContain("导出会话为 HTML");
    expect(document.body.textContent).toContain("问题");
    await act(async () => {
      Array.from(document.querySelectorAll("button")).find(button => button.textContent === "取消")!.click();
    });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)); });
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps the export menu item disabled without opening the dialog", async () => {
    await act(async () => {
      root = createRoot(document.body);
      root.render(
        <ConversationShareExportButton
          sessionId="sess-9"
          messages={transcript}
          language="zh"
          presentation="menu"
          isDisabled
        />,
      );
    });

    const trigger = document.querySelector<HTMLButtonElement>('button[aria-label="更多会话操作"]');
    expect(trigger).not.toBeNull();
    await act(async () => {
      trigger!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerType: "mouse" }));
    });
    const menuItem = await vi.waitFor(() => {
      const item = document.querySelector<HTMLElement>('[role="menuitem"]');
      expect(item?.textContent).toContain("导出 HTML");
      return item!;
    });
    expect(menuItem.getAttribute("aria-disabled")).toBe("true");

    await act(async () => menuItem.click());
    expect(document.querySelector('[data-vui="conversation-share-export-dialog"]')).toBeNull();
  });
});
