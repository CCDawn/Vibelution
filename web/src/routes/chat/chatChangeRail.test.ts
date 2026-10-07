import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { GitFileDiff } from "../../api/types";
import { ChatChangeRail } from "./ChatChangeRail";
import { buildChatChangeRail } from "./chatChangeRailModel";

const here = dirname(fileURLToPath(import.meta.url));

const base = {
  companion: false,
  finance: false,
  group: false,
  changedFiles: [] as string[],
  openTabs: [] as string[],
  activeTab: "agent",
};

function rail(overrides: Partial<Parameters<typeof buildChatChangeRail>[0]>) {
  return buildChatChangeRail({ ...base, ...overrides });
}

describe("buildChatChangeRail", () => {
  it("stays hidden for companion, finance, and group surfaces", () => {
    const files = ["web/src/app.ts"];
    expect(rail({ companion: true, changedFiles: files }).show).toBe(false);
    expect(rail({ finance: true, changedFiles: files }).show).toBe(false);
    expect(rail({ group: true, changedFiles: files }).show).toBe(false);
  });

  it("stays hidden when the session has no real file path", () => {
    expect(rail({}).show).toBe(false);
    expect(rail({
      changedFiles: ["", "agent"],
      openTabs: ["cli-agent-run:run-1"],
    })).toEqual({ show: false, paths: [], selectedPath: null });
  });

  it("lists changed files first and selects the first one while the conversation stays open", () => {
    expect(rail({
      changedFiles: ["web/src/a.ts", "web/src/b.ts"],
      activeTab: "agent",
    })).toEqual({
      show: true,
      paths: ["web/src/a.ts", "web/src/b.ts"],
      selectedPath: "web/src/a.ts",
    });
  });

  it("keeps an open file selected and appends other open files after the changes", () => {
    expect(rail({
      changedFiles: ["web/src/a.ts"],
      openTabs: ["web/src/b.ts", "agent", "cli-agent-run:run-1"],
      activeTab: "web/src/b.ts",
    })).toEqual({
      show: true,
      paths: ["web/src/a.ts", "web/src/b.ts"],
      selectedPath: "web/src/b.ts",
    });
  });

  it("normalizes slashes and drops duplicate paths", () => {
    expect(rail({
      changedFiles: ["web\\src\\a.ts", "web/src/a.ts"],
      openTabs: ["web/src/a.ts"],
      activeTab: "web\\src\\a.ts",
    })).toEqual({
      show: true,
      paths: ["web/src/a.ts"],
      selectedPath: "web/src/a.ts",
    });
  });
});

describe("ChatChangeRail", () => {
  it("lists this turn's files while the diff is still loading", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatChangeRail, {
        className: "status-rail",
        lang: "zh",
        paths: ["web/src/a.ts", "notes/readme.md"],
        selectedPath: "web/src/a.ts",
        changedPaths: new Set(["web/src/a.ts"]),
        diff: undefined,
        diffLoading: true,
        hasDiff: false,
        file: null,
        fileLoading: false,
        fileError: "",
        sourceLabel: "当前会话",
        onSelect: () => undefined,
      }),
    );

    expect(html).toContain("本轮改动");
    expect(html).toContain("a.ts");
    expect(html).toContain("notes/readme.md");
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("正在打开文件");
    expect(html).toContain('id="chat-status-pane"');
  });

  it("falls back to the file preview when there is no diff text", () => {
    const html = renderToStaticMarkup(
      React.createElement(ChatChangeRail, {
        className: "status-rail",
        lang: "zh",
        paths: ["web/src/a.ts"],
        selectedPath: "web/src/a.ts",
        changedPaths: new Set(["web/src/a.ts"]),
        diff: emptyDiff,
        diffLoading: false,
        hasDiff: false,
        file: null,
        fileLoading: false,
        fileError: "无法读取这个文件",
        sourceLabel: "当前会话",
        onSelect: () => undefined,
      }),
    );

    expect(html).toContain("无法读取这个文件");
    expect(html).toContain('role="alert"');
    expect(html).not.toContain("正在打开文件");
  });
});

const emptyDiff: GitFileDiff = {
  available: false,
  error: "",
  path: "web/src/a.ts",
  status: "",
  statusLabel: "",
  summary: "",
  diff: "",
  content: "",
  language: "",
  truncated: false,
  binary: false,
};

describe("chat change rail wiring", () => {
  const workbench = readFileSync(resolve(here, "ChatCodingRouteWorkbench.tsx"), "utf8");

  it("keeps the center conversation open while the right column shows the file", () => {
    expect(workbench).toContain("buildChatChangeRail");
    expect(workbench).toContain("conversationWorkspaceTab");
    expect(workbench).toContain('activeCliAgentRunId || !changeRail.show');
    expect(workbench).toContain("workspaceActiveTab={conversationWorkspaceTab}");
    expect(workbench).toContain("activeTab={workspace.activeTab}");
    expect(workbench).toContain("openPreviewTab(activeSessionId, path)");
  });
});
