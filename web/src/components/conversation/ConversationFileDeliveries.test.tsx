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

async function toggleExpanded() {
  const row = summaryRow();
  expect(row, "summary row renders").not.toBeNull();
  await act(async () => {
    row!.click();
  });
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

  it("collapses to a one-row summary by default and expands on click, transcript-only still working", async () => {
    await mount(<ConversationFileDeliveries cells={[writeCell("a", "demo.html", "<h1>Hi</h1>")]} language="zh" />);
    expect(textContent()).toContain("本轮文件 · 1");
    expect(textContent()).toContain("+0 −0");
    // Collapsed: no per-file cards leak out.
    expect(textContent()).not.toContain("demo.html");
    expect(textContent()).not.toContain("查看内容");
    expect(buttonByText("回退本轮文件")).toBeNull();
    expect(summaryRow()!.getAttribute("aria-expanded")).toBe("false");

    await toggleExpanded();
    expect(summaryRow()!.getAttribute("aria-expanded")).toBe("true");
    expect(textContent()).toContain("demo.html");
    expect(textContent()).toContain("查看内容");
    expect(textContent()).toContain("项目改动 · 1");

    await toggleExpanded();
    expect(textContent()).not.toContain("查看内容");
  });

  it("renders disk-truth badges and states after expanding, aligned onto transcript rows", async () => {
    await mount(
      <ConversationFileDeliveries
        cells={[writeCell("a", "C:\\proj\\web\\src\\a.ts", "export const a = 1;")]}
        language="zh"
        changedFiles={CHANGED_FILES}
        sessionId="sess-1"
        turnId="turn-9"
      />,
    );
    // Collapsed aggregate covers every project row: 2 files, +12 −8.
    expect(textContent()).toContain("本轮文件 · 2");
    expect(textContent()).toContain("+12 −8");
    await toggleExpanded();
    const text = textContent();
    expect(text).toContain("+12 −3");
    expect(text).toContain("修改");
    expect(text).toContain("已删除");
    expect(text).toContain("notes/removed.md");
  });

  it("keeps the rewind entry on the collapsed row and never expands through it", async () => {
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
    expect(summaryRow()!.getAttribute("aria-expanded")).toBe("false");
    const entry = buttonByText("回退本轮文件");
    expect(entry).not.toBeNull();
    await act(async () => {
      entry!.click();
    });
    await waitFor(() => textContent().includes("可恢复"), "rewind dialog preview renders");
    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/rewind/turn-9"))).toBe(true);
    // The rewind press must not unfold the file list.
    expect(summaryRow()!.getAttribute("aria-expanded")).toBe("false");
    expect(textContent()).not.toContain("查看内容");
  });

  it("labels a workspace-only turn as 工作区脚本 and marks the group in the expanded list", async () => {
    await mount(
      <ConversationFileDeliveries
        cells={[writeCell("w", "C:\\Users\\dev\\.worktrees\\demo\\_sweep.py", "print(1)")]}
        language="zh"
      />,
    );
    expect(textContent()).toContain("工作区脚本 · 1");
    expect(textContent()).not.toContain("+0 −0");
    await toggleExpanded();
    const text = textContent();
    expect(text).toContain("C:\\Users\\dev\\.worktrees\\demo\\_sweep.py");
    expect(text).toContain("Agent 工作区内的文件");
    expect(text).not.toContain("项目改动");
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
    expect(text).toContain("本轮文件 · 2");
    expect(text).toContain("+17 −3");
    expect(text).toContain("另有 1 个工作区脚本");
    await toggleExpanded();
    const expanded = textContent();
    expect(expanded).toContain("项目改动 · 2");
    expect(expanded).toContain("工作区脚本 · 1");
    expect(expanded).toContain("_narrow.py");
  });
});
