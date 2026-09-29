// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import styles from "./ConversationView.styles";
import { ConversationMarkdownRenderer } from "./ConversationMarkdownRenderer";
import { ConversationMarkdownWorkspaceFileLink } from "./conversationMarkdownWorkspaceFileLink";
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

function renderLink(path: string, language: "zh" | "en" = "zh") {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(
      <ConversationMarkdownWorkspaceFileLink path={path} className="lnk" language={language}>
        {path}
      </ConversationMarkdownWorkspaceFileLink>,
    );
  });
  return { host, unmount: () => {
    act(() => {
      root.unmount();
    });
    host.remove();
  } };
}

describe("ConversationMarkdownWorkspaceFileLink", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    actions.openWorkspaceFile.mockReset();
    actions.revealWorkspaceFile.mockReset();
    actions.copyWorkspaceFilePath.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("opens the workspace file through the primary click without falling back", async () => {
    actions.openWorkspaceFile.mockResolvedValue("done");
    const { host, unmount } = renderLink("C:\\repo\\a.md");
    try {
      const anchor = host.querySelector<HTMLAnchorElement>("a[data-markdown-workspace-file-link]");
      expect(anchor).not.toBeNull();
      expect(anchor!.getAttribute("title")).toBe("C:\\repo\\a.md");
      await act(async () => {
        anchor!.click();
        await Promise.resolve();
      });
      expect(actions.openWorkspaceFile).toHaveBeenCalledWith("C:\\repo\\a.md");
      expect(actions.copyWorkspaceFilePath).not.toHaveBeenCalled();
      expect(host.querySelector('[role="status"]')).toBeNull();
    } finally {
      unmount();
    }
  });

  it("falls back to copying the path with a light hint when the open action is unavailable", async () => {
    actions.openWorkspaceFile.mockResolvedValue("unavailable");
    actions.copyWorkspaceFilePath.mockResolvedValue(true);
    const { host, unmount } = renderLink("C:\\repo\\b.md");
    try {
      const anchor = host.querySelector<HTMLAnchorElement>("a[data-markdown-workspace-file-link]");
      await act(async () => {
        anchor!.click();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(actions.copyWorkspaceFilePath).toHaveBeenCalledWith("C:\\repo\\b.md");
      const hint = host.querySelector('[role="status"]');
      expect(hint?.textContent).toBe("路径已复制");

      // The hint self-dismisses.
      await act(async () => {
        vi.advanceTimersByTime(2500);
      });
      expect(host.querySelector('[role="status"]')).toBeNull();
    } finally {
      unmount();
    }
  });

  it("localizes the fallback hint", async () => {
    actions.openWorkspaceFile.mockResolvedValue("unavailable");
    actions.copyWorkspaceFilePath.mockResolvedValue(true);
    const { host, unmount } = renderLink("/tmp/c.md", "en");
    try {
      const anchor = host.querySelector<HTMLAnchorElement>("a[data-markdown-workspace-file-link]");
      await act(async () => {
        anchor!.click();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(host.querySelector('[role="status"]')?.textContent).toBe("Path copied");
    } finally {
      unmount();
    }
  });

  it("wires the open-with context menu through VDropdownMenu with bilingual items", () => {
    const source = readFileSync(
      resolve(import.meta.dirname, "conversationMarkdownWorkspaceFileLink.tsx"),
      "utf8",
    );
    expect(source).toContain("VDropdownMenu");
    expect(source).toContain("position={menuPosition}");
    expect(source).toContain('aria-label={zh ? "打开方式" : "Open with"}');
    expect(source).toContain('label: zh ? "打开（系统默认）" : "Open (system default)"');
    expect(source).toContain('label: zh ? "在文件夹中显示" : "Show in folder"');
    expect(source).toContain('label: zh ? "复制路径" : "Copy path"');
    expect(source).toContain("onContextMenu");
    expect(source).toContain("revealWorkspaceFile(path)");
    expect(source).toContain("copyWorkspaceFilePath(path)");
  });
});

describe("ConversationMarkdownRenderer workspace-file link routing", () => {
  beforeEach(() => {
    actions.openWorkspaceFile.mockReset();
    actions.revealWorkspaceFile.mockReset();
    actions.copyWorkspaceFilePath.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders workspace-file hrefs as clickable open links when a workspace root is given", () => {
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content="参见 [规格说明](docs/spec.md) 与 [入口](/src/index.ts)。"
        classNames={styles}
        workspaceRoot="C:\\repo"
        language="zh"
      />,
    );
    expect((html.match(/data-markdown-workspace-file-link="true"/g) ?? []).length).toBe(2);
    expect(html).toContain('title="C:\\repo\\docs\\spec.md"');
    expect(html).toContain('title="C:\\repo\\src\\index.ts"');
    // Workspace links carry no navigable href — the desktop bridge handles them.
    expect(html).not.toContain('href="docs/spec.md"');
    expect(html).toContain("规格说明");
  });

  it("keeps external and unresolvable hrefs on the legacy anchor path", () => {
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["[外链](https://example.com/x)", "[规格](docs/spec.md)"].join("\n\n")}
        classNames={styles}
      />,
    );
    expect(html).toContain('href="https://example.com/x"');
    expect(html).toContain('href="docs/spec.md"');
    expect(html).not.toContain("data-markdown-workspace-file-link");
  });

  it("keeps unsafe hrefs inert while routing workspace links", () => {
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content="[bad](javascript:alert(1))"
        classNames={styles}
        workspaceRoot="C:\\repo"
      />,
    );
    expect(html).toContain("bad");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("data-markdown-workspace-file-link");
  });
});
