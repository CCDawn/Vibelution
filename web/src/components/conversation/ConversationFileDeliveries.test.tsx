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

  it("keeps transcript-only behaviour identical without the new props", async () => {
    await mount(<ConversationFileDeliveries cells={[writeCell("a", "C:\\proj\\demo.html", "<h1>Hi</h1>")]} language="zh" />);
    const text = textContent();
    expect(text).toContain("C:\\proj\\demo.html");
    expect(text).toContain("查看内容");
    expect(text).toContain("本轮文件 · 1");
    expect(buttonByText("回退本轮文件")).toBeNull();
  });

  it("renders disk-truth badges and states, aligned onto transcript rows", async () => {
    await mount(
      <ConversationFileDeliveries
        cells={[writeCell("a", "C:\\proj\\web\\src\\a.ts", "export const a = 1;")]}
        language="zh"
        changedFiles={CHANGED_FILES}
        sessionId="sess-1"
        turnId="turn-9"
      />,
    );
    const text = textContent();
    expect(text).toContain("+12 −3");
    expect(text).toContain("修改");
    expect(text).toContain("已删除");
    expect(text).toContain("notes/removed.md");
  });

  it("opens the rewind dialog from the header entry and previews the server plan", async () => {
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
    const entry = buttonByText("回退本轮文件");
    expect(entry).not.toBeNull();
    await act(async () => {
      entry!.click();
    });
    await waitFor(() => textContent().includes("可恢复"), "rewind dialog preview renders");
    expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/rewind/turn-9"))).toBe(true);
  });
});
