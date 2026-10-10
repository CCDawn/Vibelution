// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DevTeamTaskChanges, DevTeamTaskList } from "../../api/devTeamTasks";
import { VuiProvider } from "../../components/vui/VuiProvider";
import { ChatGroupArtifactDialog, resolveTaskWorkspaceFilePath } from "./ChatGroupArtifactDialog";

const api = vi.hoisted(() => ({
  listTasks: vi.fn(),
  listChanges: vi.fn(),
  fetchFileContent: vi.fn(),
}));

vi.mock("../../api/devTeamTasks", () => ({
  listDevTeamTasks: api.listTasks,
  listDevTeamTaskChanges: api.listChanges,
}));

vi.mock("../../api/files", () => ({ fetchFileContent: api.fetchFileContent }));

vi.mock("./ChatFilePreviewPanel", () => ({
  ChatFilePreviewPanel: (props: {
    errorMessage: string;
    file?: { content: string } | null;
    loadingLabel: string;
  }) => (
    <div data-testid="chat-file-preview-panel">
      {props.errorMessage || props.file?.content || props.loadingLabel}
    </div>
  ),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: Error) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function taskList(
  tasks: Array<{
    id: string;
    subject: string;
    workspacePath?: string;
    workspaceBranch?: string;
  }>,
  teamId = "team-1",
): DevTeamTaskList {
  return {
    schemaVersion: 1,
    teamId,
    updatedAt: "",
    tasks: tasks.map((task) => ({
      id: task.id,
      revision: 1,
      subject: task.subject,
      description: "",
      status: "in_progress",
      ownerMemberId: "",
      ownerName: "",
      ownerRole: "",
      blockedBy: [],
      writeScopes: [],
      reviewNote: "",
      ready: true,
      writeScopeWarnings: [],
      workspacePath: task.workspacePath ?? `.worktrees/${task.id}`,
      workspaceBranch: task.workspaceBranch ?? `codex/${task.id}`,
      updatedAt: "",
    })),
  };
}

function changes(
  entries: Array<{ path: string; status: string }>,
  options: { available?: boolean; workspace?: boolean; truncated?: number } = {},
): DevTeamTaskChanges {
  return {
    available: options.available ?? true,
    workspace: options.workspace ?? true,
    truncated: options.truncated ?? 0,
    changes: entries,
  };
}

let mounted: Array<{ host: HTMLElement; root: Root; client: QueryClient }> = [];

async function mountDialog(overrides: Partial<React.ComponentProps<typeof ChatGroupArtifactDialog>> = {}) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  mounted.push({ host, root, client });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <VuiProvider>
          <ChatGroupArtifactDialog
            teamId="team-1"
            taskIds={["task-1"]}
            lang="zh"
            open
            onOpenChange={() => undefined}
            {...overrides}
          />
        </VuiProvider>
      </QueryClientProvider>,
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return { host, client };
}

async function flushQueryUpdates() {
  for (let index = 0; index < 3; index += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

describe("ChatGroupArtifactDialog", () => {
  beforeEach(() => {
    api.listTasks.mockReset();
    api.listChanges.mockReset();
    api.fetchFileContent.mockReset();
  });

  afterEach(async () => {
    for (const item of mounted.splice(0)) {
      await act(async () => {
        item.root.unmount();
      });
      item.client.clear();
      item.host.remove();
    }
    document.body.innerHTML = "";
  });

  it("only builds project-relative paths from a matching task workspace and safe API path", () => {
    expect(resolveTaskWorkspaceFilePath("web/src/App.tsx", ".worktrees/task-1", "codex/task-1"))
      .toBe(".worktrees/task-1/web/src/App.tsx");
    expect(resolveTaskWorkspaceFilePath("../outside.md", ".worktrees/task-1", "codex/task-1")).toBeNull();
    expect(resolveTaskWorkspaceFilePath("/outside.md", ".worktrees/task-1", "codex/task-1")).toBeNull();
    expect(resolveTaskWorkspaceFilePath("C:\\outside.md", ".worktrees/task-1", "codex/task-1")).toBeNull();
    expect(resolveTaskWorkspaceFilePath("safe.md", "C:\\repo\\task-1", "codex/task-1")).toBeNull();
    expect(resolveTaskWorkspaceFilePath("safe.md", ".worktrees/task-1", "codex/other-task")).toBeNull();
  });

  it("previews current API changes in the dialog and returns to the file list", async () => {
    api.listTasks.mockResolvedValue(taskList([{ id: "task-1", subject: "更新工作台" }]));
    api.listChanges.mockResolvedValue(changes([
      { path: "web/src/App.tsx", status: "modified" },
      { path: "removed.md", status: "deleted" },
    ], { truncated: 2 }));
    api.fetchFileContent.mockResolvedValue({
      path: ".worktrees/task-1/web/src/App.tsx",
      language: "typescript",
      content: "const currentWorkspace = true;",
      truncated: false,
    });

    await mountDialog();
    await flushQueryUpdates();

    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("当前任务改动");
    expect(dialog?.textContent).toContain("不是历史版本");
    expect(dialog?.textContent).toContain("更新工作台");
    expect(dialog?.textContent).toContain("还有 2 个文件未列出");
    expect(dialog?.querySelector('a[href]')).toBeNull();

    const fileButton = dialog?.querySelector<HTMLButtonElement>('button[aria-label="预览 web/src/App.tsx"]');
    expect(fileButton).not.toBeNull();
    await act(async () => {
      fileButton?.click();
      await Promise.resolve();
    });
    await flushQueryUpdates();

    expect(api.fetchFileContent).toHaveBeenCalledWith(".worktrees/task-1/web/src/App.tsx");
    expect(document.body.textContent).toContain("const currentWorkspace = true;");
    const backButton = document.body.querySelector<HTMLButtonElement>('[data-vui="chat-group-artifact-back"]');
    expect(backButton?.textContent).toContain("返回文件列表");
    await act(async () => {
      backButton?.click();
      await Promise.resolve();
    });
    expect(document.body.textContent).toContain("web/src/App.tsx");
    expect(document.body.textContent).not.toContain("const currentWorkspace = true;");
    const refreshedFile = deferred<{ path: string; language: string; content: string; truncated: boolean }>();
    api.fetchFileContent.mockReturnValueOnce(refreshedFile.promise);
    await act(async () => {
      document.body.querySelector<HTMLButtonElement>('button[aria-label="预览 web/src/App.tsx"]')?.click();
    });
    await flushQueryUpdates();
    expect(document.body.textContent).toContain("正在读取文件");
    expect(document.body.textContent).not.toContain("const currentWorkspace = true;");
    await act(async () => refreshedFile.resolve({
      path: ".worktrees/task-1/web/src/App.tsx", language: "typescript", content: "UPDATED-CONTENT", truncated: false,
    }));
    await flushQueryUpdates();
    expect(document.body.textContent).toContain("UPDATED-CONTENT");
  });

  it("keeps deleted file names as text and never requests their contents", async () => {
    api.listTasks.mockResolvedValue(taskList([{ id: "task-1", subject: "清理旧文件" }]));
    api.listChanges.mockResolvedValue(changes([{ path: "removed.md", status: "deleted" }]));

    await mountDialog();
    await flushQueryUpdates();

    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain("removed.md");
    expect(dialog?.querySelector('button[aria-label="预览 removed.md"]')).toBeNull();
    expect(api.fetchFileContent).not.toHaveBeenCalled();
  });

  it("shows only a summary when the task list belongs to another team", async () => {
    api.listTasks.mockResolvedValue(taskList([{ id: "task-1", subject: "其他团队任务" }], "team-2"));

    await mountDialog();
    await flushQueryUpdates();

    expect(document.body.textContent).toContain("团队信息不一致，无法读取任务改动。");
    expect(api.listChanges).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("其他团队任务");
  });

  it("hides paths when the workspace is not a verified task worktree", async () => {
    api.listTasks.mockResolvedValue(taskList([{
      id: "task-1",
      subject: "路径异常任务",
      workspacePath: "C:\\repo\\.worktrees\\task-1",
      workspaceBranch: "codex/task-1",
    }]));
    api.listChanges.mockResolvedValue(changes([{ path: "src/private.ts", status: "modified" }]));

    await mountDialog();
    await flushQueryUpdates();

    expect(document.body.textContent).toContain("工作区信息无法验证，明细已隐藏");
    expect(document.body.textContent).not.toContain("src/private.ts");
    expect(document.body.querySelector('[data-vui="chat-group-artifact-file"]')).toBeNull();
    expect(api.fetchFileContent).not.toHaveBeenCalled();
  });

  it("hides the full file list when a changes response contains an unsafe path", async () => {
    api.listTasks.mockResolvedValue(taskList([{ id: "task-1", subject: "异常文件清单" }]));
    api.listChanges.mockResolvedValue(changes([
      { path: "src/App.tsx", status: "modified" },
      { path: "../outside.md", status: "modified" },
    ]));

    await mountDialog();
    await flushQueryUpdates();

    expect(document.body.textContent).toContain("文件路径无法验证，明细已隐藏");
    expect(document.body.textContent).not.toContain("src/App.tsx");
    expect(document.body.textContent).not.toContain("../outside.md");
    expect(document.body.querySelector('[data-vui="chat-group-artifact-file"]')).toBeNull();
  });

  it("announces loading and failure for the per-task changes query", async () => {
    const pendingChanges = deferred<DevTeamTaskChanges>();
    api.listTasks.mockResolvedValue(taskList([{ id: "task-1", subject: "延迟任务" }]));
    api.listChanges.mockReturnValue(pendingChanges.promise);

    await mountDialog();
    await flushQueryUpdates();
    expect(document.body.textContent).toContain("正在读取当前改动…");
    await act(async () => {
      pendingChanges.reject(new Error("changes unavailable"));
      await pendingChanges.promise.catch(() => undefined);
    });
    await flushQueryUpdates();
    expect(document.body.textContent).toContain("当前改动读取失败。");

    api.listTasks.mockRejectedValue(new Error("task list unavailable"));
    await mountDialog({ taskIds: ["task-2"] });
    await flushQueryUpdates();
    expect(document.body.textContent).toContain("任务信息加载失败。");
  });

  it("does not query task data while closed", async () => {
    await mountDialog({ open: false });
    await flushQueryUpdates();
    expect(api.listTasks).not.toHaveBeenCalled();
    expect(api.listChanges).not.toHaveBeenCalled();
  });
});
