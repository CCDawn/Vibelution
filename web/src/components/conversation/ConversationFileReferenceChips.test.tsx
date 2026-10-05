// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { ConversationFileReferenceChips } from "./ConversationFileReferenceChips";
import type { WorkspaceFileActionResult } from "./conversationMarkdownWorkspaceFileActions";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const actions = vi.hoisted(() => ({
  openWorkspaceFile: vi.fn<(path: string) => Promise<WorkspaceFileActionResult>>(),
  revealWorkspaceFile: vi.fn<(path: string) => Promise<WorkspaceFileActionResult>>(),
  copyWorkspaceFilePath: vi.fn<(path: string) => Promise<boolean>>(),
}));

vi.mock("./conversationMarkdownWorkspaceFileActions", () => ({
  openWorkspaceFile: actions.openWorkspaceFile,
  revealWorkspaceFile: actions.revealWorkspaceFile,
  copyWorkspaceFilePath: actions.copyWorkspaceFilePath,
}));

const ROOT = "C:\\workspace\\sessions\\abc";
const BODY = "产物已生成：\n```text\nC:\\out\\report.html\n```\n图片 C:\\out\\chart.png。";

function renderChips(props: { text: string; workspaceRoot?: string; language?: "zh" | "en" }) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(
      <ConversationFileReferenceChips
        text={props.text}
        workspaceRoot={props.workspaceRoot}
        language={props.language ?? "zh"}
      />,
    );
  });
  return { host, unmount: () => {
    act(() => {
      root.unmount();
    });
    host.remove();
  } };
}

function chipElements(host: HTMLElement): HTMLElement[] {
  return [...host.querySelectorAll("[data-conversation-file-reference-chip]")].filter(
    (node): node is HTMLElement => node instanceof HTMLElement,
  );
}

describe("ConversationFileReferenceChips", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    actions.openWorkspaceFile.mockReset();
    actions.revealWorkspaceFile.mockReset();
    actions.copyWorkspaceFilePath.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders one lightweight chip per deduplicated reference with extension badge", () => {
    const { host, unmount } = renderChips({ text: BODY, workspaceRoot: ROOT });
    const chips = chipElements(host);
    expect(chips).toHaveLength(2);
    expect(chips[0].getAttribute("data-file-extension")).toBe("html");
    expect(chips[1].getAttribute("data-file-extension")).toBe("png");
    expect(chips[0].textContent).toContain("report.html");
    expect(host.querySelector("[data-conversation-file-references]")).not.toBeNull();
    unmount();
  });

  it("renders nothing when the text has no whitelisted references", () => {
    const { host, unmount } = renderChips({
      text: "只有普通文本与 `C:\\scripts\\run.py` 脚本路径。",
      workspaceRoot: ROOT,
    });
    expect(host.querySelector("[data-conversation-file-references]")).toBeNull();
    unmount();
  });

  it("opens the file with the system default program on click", async () => {
    actions.openWorkspaceFile.mockResolvedValue("done");
    const { host, unmount } = renderChips({ text: BODY, workspaceRoot: ROOT });
    const chip = chipElements(host)[0];
    expect(chip).toBeDefined();
    await act(async () => {
      chip!.click();
    });
    expect(actions.openWorkspaceFile).toHaveBeenCalledWith("C:\\out\\report.html");
    expect(actions.copyWorkspaceFilePath).not.toHaveBeenCalled();
    unmount();
  });

  it("falls back to copying the path when the desktop bridge is unavailable", async () => {
    actions.openWorkspaceFile.mockResolvedValue("unavailable");
    actions.copyWorkspaceFilePath.mockResolvedValue(true);
    const { host, unmount } = renderChips({ text: BODY, workspaceRoot: ROOT });
    const chip = chipElements(host)[0];
    await act(async () => {
      chip!.click();
    });
    expect(actions.copyWorkspaceFilePath).toHaveBeenCalledWith("C:\\out\\report.html");
    expect(host.querySelector("[role='status']")?.textContent).toContain("路径已复制");
    await act(async () => {
      vi.advanceTimersByTime(2600);
    });
    expect(host.querySelector("[role='status']")).toBeNull();
    unmount();
  });

  it("wires the open-with context menu through VDropdownMenu with bilingual items", () => {
    // Radix menu portals are covered by vuiDropdownMenuContract; the wiring
    // contract here keeps 打开 / 在文件夹中显示 / 复制路径 semantics identical
    // to the inline markdown workspace-file link.
    const source = readFileSync(
      resolve(import.meta.dirname, "ConversationFileReferenceChips.tsx"),
      "utf8",
    );
    expect(source).toContain("VDropdownMenu");
    expect(source).toContain("onContextMenu");
    expect(source).toContain('aria-label={zh ? "打开方式" : "Open with"}');
    expect(source).toContain('label: zh ? "打开（系统默认）" : "Open (system default)"');
    expect(source).toContain('label: zh ? "在文件夹中显示" : "Show in folder"');
    expect(source).toContain('label: zh ? "复制路径" : "Copy path"');
    expect(source).toContain("revealWorkspaceFile(path)");
    expect(source).toContain("copyWorkspaceFilePath(path)");
    expect(source).toContain("openWorkspaceFile(path)");
  });
});
