/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearControlToken, seedControlTokenForTests } from "../../api/client";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { ConversationFileDeliveries } from "./ConversationFileDeliveries";
import type { ConversationChangedFileSummary } from "./conversationFileDeliveryModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function writeCell(id: string, path: string, content: string): CodexTranscriptCell {
  return {
    id, messageId: "turn1", kind: "tool_call", status: "completed", tone: "neutral",
    toolLifecycleModel: {
      toolCalls: [{
        toolCallId: id, rawOperationId: id, rawToolName: "write_file_tool",
        arguments: { file_path: path, content }, status: "completed", title: "写入文件", runtimeKind: "tool",
      }],
      terminalOperations: [], terminalSessions: [], modelObservations: [],
    },
  };
}

const CHANGED_FILES: ConversationChangedFileSummary[] = [
  { path: "web/src/a.ts", additions: 12, deletions: 3, state: "modified" },
  { path: "notes/removed.md", additions: 0, deletions: 5, state: "deleted" },
];

function jsonResponse(status: number, payload: unknown) {
  return new Response(JSON.stringify(payload), {
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

function summaryRow(): HTMLElement | null {
  return document.querySelector<HTMLElement>("[data-file-deliveries-summary='true']");
}

async function waitFor(predicate: () => boolean, message: string) {
  for (let attempt = 0; attempt < 200 && !predicate(); attempt += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
  expect(predicate(), message).toBe(true);
}

describe("ConversationFileDeliveries rewind surface", () => {
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

  async function mount(element: React.ReactElement) {
    await act(async () => {
      root = createRoot(document.body);
      root.render(element);
    });
  }

  it("shows short file lists immediately without inventing counts for transcript-only writes", async () => {
    await mount(<ConversationFileDeliveries cells={[writeCell("a", "demo.html", "<h1>Hi</h1>")]} language="zh" />);
    expect(textContent()).toContain("已编辑 1 个文件");
    expect(textContent()).not.toContain("+0 −0");
    expect(textContent()).toContain("demo.html");
    expect(buttonByText("撤销")).toBeNull();
    expect(buttonByText("再显示")).toBeNull();
    expect(buttonByText("查看变更")?.disabled).toBe(true);
    expect(document.querySelector('[aria-label="文件操作：demo.html"]')).not.toBeNull();
  });

  it("shows three files and folds the rest while preserving the summary and row order", async () => {
    const changedFiles = Array.from({ length: 5 }, (_, index) => ({
      path: `web/src/file-${index + 1}.ts`, additions: index + 1, deletions: 0, state: "modified",
    }));
    await mount(<ConversationFileDeliveries cells={[]} language="zh" changedFiles={changedFiles} />);
    expect(textContent()).toContain("已编辑 5 个文件");
    expect(summaryRow()?.textContent).toContain("+15 −0");
    expect(document.querySelectorAll('[data-file-delivery-path]')).toHaveLength(3);
    expect(textContent()).not.toContain("file-4.ts");
    const more = buttonByText("再显示 2 个文件")!;
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await act(async () => more.click());
    expect(document.querySelectorAll('[data-file-delivery-path]')).toHaveLength(5);
    expect([...document.querySelectorAll('[data-file-delivery-path]')].map((row) => row.getAttribute('data-file-delivery-path')))
      .toEqual(changedFiles.map((file) => file.path));
    const fewer = buttonByText("收起文件")!;
    expect(fewer.getAttribute("aria-expanded")).toBe("true");
    await act(async () => fewer.click());
    expect(document.querySelectorAll('[data-file-delivery-path]')).toHaveLength(3);
  });

  it("opens recorded patches through View changes while preserving follow-up file actions", async () => {
    const patch = writeCell("patch-1", "web/src/a.ts", "");
    const call = patch.toolLifecycleModel!.toolCalls[0];
    call.rawToolName = "apply_patch_tool";
    call.arguments = { patch_text: "*** Begin Patch\n*** Update File: web/src/a.ts\n@@\n-oldValue\n+newValue\n*** End Patch" };
    const onContinue = vi.fn();
    await mount(<ConversationFileDeliveries cells={[patch]} language="zh" changedFiles={CHANGED_FILES} onContinue={onContinue} />);
    const view = buttonByText("查看变更")!;
    expect(view.disabled).toBe(false);
    await act(async () => view.click());
    expect(document.querySelector('[data-vui="conversation-patch-dialog"]')).not.toBeNull();
    expect(textContent()).toContain("newValue");
    expect(textContent()).toContain("不等于整轮净差异");
    await act(async () => document.querySelector<HTMLButtonElement>('[data-vui="dialog-close"]')!.click());
    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="文件操作：a.ts"]')!
      .dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 })));
    await waitFor(() => Boolean(document.querySelector('[role="menuitem"]')), "file menu opens");
    const followup = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((entry) => entry.textContent?.includes("继续修改"));
    expect(followup).not.toBeUndefined();
    await act(async () => followup!.click());
    expect(onContinue).toHaveBeenCalledWith("web/src/a.ts");
  });

  it("renders disk-truth counts and states aligned onto transcript rows with an explicit net-count hint", async () => {
    await mount(
      <ConversationFileDeliveries
        cells={[writeCell("a", "C:\\proj\\web\\src\\a.ts", "export const a = 1;")]}
        language="zh"
        changedFiles={CHANGED_FILES}
        sessionId="sess-1"
        turnId="turn-9"
      />,
    );
    expect(textContent()).toContain("已编辑 2 个文件");
    expect(textContent()).toContain("+12 −8");
    expect(document.querySelector('[title="本轮净行数变化"]')).not.toBeNull();
    const text = textContent();
    expect(text).toContain("+12 −3");
    expect(text).toContain("修改");
    expect(text).toContain("已删除");
    expect(text).toContain("notes/removed.md");
  });

  it("opens the existing whole-turn rewind preview without applying changes or unfolding more files", async () => {
    const fetchMock = vi.fn(() => jsonResponse(200, {
      sessionId: "sess-1", turnId: "turn-9",
      files: [{ path: "web/src/a.ts", action: "restore", classification: "safe", state: "modified", currentExists: true, currentSize: 32 }],
      canApply: true, capabilityNote: "",
    }));
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    await mount(
      <ConversationFileDeliveries
        cells={[writeCell("a", "C:\\proj\\web\\src\\a.ts", "export const a = 1;")]}
        language="zh"
        changedFiles={CHANGED_FILES}
        sessionId="sess-1"
        turnId="turn-9"
      />,
    );
    const rowsBefore = document.querySelectorAll('[data-file-delivery-path]').length;
    const entry = buttonByText("撤销");
    expect(entry).not.toBeNull();
    await act(async () => {
      entry!.click();
    });
    await waitFor(() => textContent().includes("可恢复"), "rewind dialog preview renders");
    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/rewind/turn-9"))).toBe(true);
    expect(fetchMock.mock.calls.every((call) => (call as unknown as [unknown, RequestInit?])[1]?.method !== "POST")).toBe(true);
    expect(document.querySelectorAll('[data-file-delivery-path]')).toHaveLength(rowsBefore);
  });

  it("keeps workspace-only files marked and excludes their unknown line counts", async () => {
    await mount(
      <ConversationFileDeliveries
        cells={[writeCell("w", "C:\\Users\\dev\\.worktrees\\demo\\_sweep.py", "print(1)")]}
        language="zh"
      />,
    );
    expect(textContent()).toContain("工作区脚本 · 1");
    expect(textContent()).not.toContain("+0 −0");
    const text = textContent();
    expect(document.querySelector('[data-file-delivery-path]')?.getAttribute("data-file-delivery-path"))
      .toBe("C:\\Users\\dev\\.worktrees\\demo\\_sweep.py");
    expect(text).toContain("工作区");
    expect(text).not.toContain("已编辑");
  });

  it("aggregates +/− over project files only and appends the workspace-script note", async () => {
    await mount(
      <ConversationFileDeliveries
        cells={[
          writeCell("a", "C:\\proj\\web\\src\\a.ts", "export const a = 1;"),
          writeCell("w", "C:\\Users\\dev\\.worktrees\\demo\\_narrow.py", "print(2)"),
        ]}
        language="zh"
        changedFiles={[
          { path: "web/src/a.ts", additions: 12, deletions: 3, state: "modified" },
          { path: "notes/new.md", additions: 5, deletions: 0, state: "created" },
        ]}
      />,
    );
    const text = textContent();
    // P=2 project rows (absolute tool path aligned onto its project-relative
    // summary), W=1 transcript-only workspace script; +/− never counts the script.
    expect(text).toContain("已编辑 2 个文件");
    expect(text).toContain("+17 −3");
    expect(text).toContain("另有 1 个工作区脚本");
    expect(textContent()).toContain("_narrow.py");
  });
});
