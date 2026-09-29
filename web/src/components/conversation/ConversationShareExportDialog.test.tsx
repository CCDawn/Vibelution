/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearControlToken, seedControlTokenForTests } from "../../api/client";
import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { ConversationShareExportDialog } from "./ConversationShareExportDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function assistantItem(turnId: string, text: string): SessionTurnItem {
  return {
    id: `${turnId}-item-1`,
    itemId: `${turnId}-item-1`,
    version: 3,
    sessionId: "sess-1",
    turnId,
    status: "completed",
    revision: 0,
    sequence: 1,
    type: "agent_message",
    phase: "final_answer",
    text,
  } as SessionTurnItem;
}

const MESSAGES: ConversationMessage[] = [
  { id: "s-message-1", role: "user", content: "第一问", timestamp: "2026-01-02T10:30:00" },
  {
    id: "s-message-2",
    role: "assistant",
    turnId: "turn-1",
    status: "completed",
    timestamp: "2026-01-02T10:30:05",
    turnItems: [assistantItem("turn-1", "第一答")],
  },
  { id: "s-message-3", role: "user", content: "第二问", timestamp: "2026-01-02T10:31:00" },
  {
    id: "s-message-4",
    role: "assistant",
    turnId: "turn-2",
    status: "completed",
    timestamp: "2026-01-02T10:31:10",
    turnItems: [assistantItem("turn-2", "第二答")],
  },
];

const EXPORT_BODY = {
  filename: "vibelution-demo-20260928.html",
  html: "<!doctype html><html lang=\"zh\"></html>",
  skippedTurnIds: ["ghost"],
};

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function textContent(): string {
  return document.body.textContent ?? "";
}

function buttonByText(text: string): HTMLButtonElement | null {
  return Array.from(document.querySelectorAll("button"))
    .find((button) => (button.textContent ?? "").includes(text)) ?? null;
}

function checkboxByLabel(label: string): HTMLInputElement | null {
  return document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
}

async function waitFor(predicate: () => boolean, message: string) {
  for (let attempt = 0; attempt < 200 && !predicate(); attempt += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
  expect(predicate(), message).toBe(true);
}

describe("ConversationShareExportDialog", () => {
  let root: Root | null = null;
  let fetchMock: ReturnType<typeof vi.fn> | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    document.body.innerHTML = "";
    root = null;
    fetchMock = null;
    clearControlToken();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function mount(responder: () => Promise<Response>) {
    fetchMock = vi.fn(responder);
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    await act(async () => {
      root = createRoot(document.body);
      root.render(
        <ConversationShareExportDialog
          open
          sessionId="sess-1"
          messages={MESSAGES}
          language="zh"
          onOpenChange={() => undefined}
        />,
      );
    });
  }

  function postedBody(): Record<string, unknown> {
    const calls = postedCalls();
    expect(calls).not.toHaveLength(0);
    return JSON.parse((calls[0][1] as RequestInit).body as string);
  }

  function postedCalls(): Array<[string, RequestInit]> {
    return (fetchMock?.mock.calls ?? []).filter(
      (call) => (call[1] as RequestInit | undefined)?.method === "POST",
    ) as Array<[string, RequestInit]>;
  }

  it("renders per-turn checkboxes with previews and exports every turn by default", async () => {
    await mount(() => Promise.resolve(jsonResponse(200, EXPORT_BODY)));
    await waitFor(() => textContent().includes("第 2 轮"), "turn rows render");
    expect(textContent()).toContain("第一问");
    expect(textContent()).toContain("第二答");
    expect(textContent()).toContain("内嵌图片附件");

    await act(async () => {
      buttonByText("导出所选轮次（2）")!.click();
    });
    await waitFor(() => postedCalls().length === 1, "export posted");
    const [endpoint, init] = postedCalls()[0];
    expect(endpoint).toBe("/api/sessions/sess-1/export-html");
    expect(JSON.parse(init.body as string)).toEqual({
      turnIds: ["turn-1", "turn-2"],
      includeAttachments: true,
    });
    await waitFor(() => textContent().includes("已生成 vibelution-demo-20260928.html"), "result feedback");
    expect(textContent()).toContain("已忽略 1 个无效轮次");
  });

  it("disables the export action at zero selection and honours single-turn picks", async () => {
    await mount(() => Promise.resolve(jsonResponse(200, EXPORT_BODY)));
    await waitFor(() => textContent().includes("第 2 轮"), "turn rows render");

    const selectAll = document.querySelectorAll<HTMLInputElement>("input[data-vui='checkbox'], input[type='checkbox']")[0];
    await act(async () => {
      selectAll.click();
    });
    await waitFor(
      () => buttonByText("导出所选轮次（0）")?.disabled === true,
      "export disabled at zero selection",
    );

    await act(async () => {
      selectAll.click();
    });
    await act(async () => {
      checkboxByLabel("第 1 轮")!.click();
    });
    await waitFor(
      () => buttonByText("导出所选轮次（1）") !== null,
      "single selection counted",
    );

    await act(async () => {
      buttonByText("导出所选轮次（1）")!.click();
    });
    await waitFor(() => postedCalls().length === 1, "export posted");
    expect(postedBody()).toEqual({
      turnIds: ["turn-2"],
      includeAttachments: true,
    });
  });

  it("surfaces the 404 missing-session failure without closing the dialog", async () => {
    await mount(() => Promise.resolve(jsonResponse(404, { detail: "Session not found" })));
    await waitFor(() => textContent().includes("第 2 轮"), "turn rows render");
    await act(async () => {
      buttonByText("导出所选轮次（2）")!.click();
    });
    await waitFor(() => textContent().includes("会话不存在或已被删除"), "error renders");
    expect(document.querySelector('[role="alert"]')).not.toBeNull();
    expect(buttonByText("导出所选轮次（2）")).not.toBeNull();
  });

  it("saves the document through a blob anchor download with the server filename", async () => {
    const createdUrls: string[] = [];
    const revokeSpy = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: () => {
        const url = `blob:mock-${createdUrls.length}`;
        createdUrls.push(url);
        return url;
      },
      revokeObjectURL: revokeSpy,
    });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    await mount(() => Promise.resolve(jsonResponse(200, EXPORT_BODY)));
    await waitFor(() => textContent().includes("第 2 轮"), "turn rows render");
    await act(async () => {
      buttonByText("导出所选轮次（2）")!.click();
    });
    await waitFor(() => createdUrls.length === 1, "blob url created");
    expect(clickSpy).toHaveBeenCalled();
    const anchor = clickSpy.mock.contexts[0] as HTMLAnchorElement;
    expect(anchor.download).toBe("vibelution-demo-20260928.html");
    expect(anchor.href).toContain("blob:mock-0");
  });
});
