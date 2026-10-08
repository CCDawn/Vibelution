/** @vitest-environment happy-dom */

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TeamMember } from "../../api/types";
import { DevTeamTaskBoard } from "./DevTeamTaskBoard";

const listDevTeamTasks = vi.fn();
const listDevTeamTaskChanges = vi.fn();
const createDevTeamTask = vi.fn();
const mutateDevTeamTask = vi.fn();

vi.mock("../../api/devTeamTasks", () => ({
  listDevTeamTasks: (...args: unknown[]) => listDevTeamTasks(...args),
  listDevTeamTaskChanges: (...args: unknown[]) => listDevTeamTaskChanges(...args),
  createDevTeamTask: (...args: unknown[]) => createDevTeamTask(...args),
  mutateDevTeamTask: (...args: unknown[]) => mutateDevTeamTask(...args),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const members = [
  { memberId: "m-plan", role: "规划师", agentName: "规划师", agentId: "a1", agentCode: "plan", agentStatus: "active", purpose: "" },
  { memberId: "m-a", role: "开发工程师 A", agentName: "工程师A", agentId: "a2", agentCode: "dev-a", agentStatus: "active", purpose: "" },
  { memberId: "m-rev", role: "评审员", agentName: "评审员", agentId: "a3", agentCode: "rev", agentStatus: "active", purpose: "" },
] as TeamMember[];

const readyTask = {
  id: "task-1",
  revision: 1,
  subject: "补任务板",
  description: "只改团队页",
  status: "pending",
  ownerMemberId: "",
  ownerName: "",
  ownerRole: "",
  blockedBy: [],
  writeScopes: ["web/src/routes/teams"],
  reviewNote: "",
  ready: true,
  writeScopeWarnings: ["与 task-2 的写范围重叠"],
  updatedAt: "",
};

let host: HTMLDivElement | null = null;
let root: Root | null = null;

function setNativeValue(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const prototype = Object.getPrototypeOf(element);
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

async function renderBoard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(
      <QueryClientProvider client={client}>
        <DevTeamTaskBoard lang="zh" teamId="team-1" members={members} />
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await listDevTeamTasks.mock.results[0]?.value;
  });
}

describe("DevTeamTaskBoard", () => {
  afterEach(() => {
    listDevTeamTasks.mockReset();
    listDevTeamTaskChanges.mockReset();
    createDevTeamTask.mockReset();
    mutateDevTeamTask.mockReset();
    act(() => root?.unmount());
    host?.remove();
    host = null;
    root = null;
  });

  it("lets an engineer claim a ready task and shows the overlap warning", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    mutateDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    await renderBoard();
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.textContent).toContain("与 task-2 的写范围重叠");
      });
    });
    const actor = host?.querySelector<HTMLSelectElement>('select[aria-label="当前身份"]');
    expect(actor).toBeTruthy();
    await act(async () => {
      if (actor) {
        setNativeValue(actor, "m-a");
      }
    });
    const claim = host?.querySelector<HTMLButtonElement>('button[aria-label="认领 task-1"]');
    expect(claim).toBeTruthy();
    await act(async () => {
      claim?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(mutateDevTeamTask).toHaveBeenCalledWith("team-1", "task-1", {
      actorMemberId: "m-a",
      action: "claim",
      expectedRevision: 1,
    });
    expect(host?.textContent).not.toContain("工作区");
    expect(host?.querySelector('button[aria-label="保存修改 task-1"]')).toBeNull();
  });

  it("shows the opened workspace branch on the task card", async () => {
    listDevTeamTasks.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      tasks: [{ ...readyTask, status: "in_progress", ready: false, workspaceBranch: "codex/dev-team-1", workspacePath: ".worktrees/dev-team-1" }],
      updatedAt: "",
    });
    await renderBoard();
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.textContent).toContain("工作区 codex/dev-team-1");
      });
    });
  });

  it("shows the task workspace changes to the reviewer", async () => {
    listDevTeamTasks.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      tasks: [{ ...readyTask, status: "in_progress", ready: false, workspaceBranch: "codex/dev-team-1" }],
      updatedAt: "",
    });
    listDevTeamTaskChanges.mockResolvedValue({
      available: true,
      workspace: true,
      truncated: 1,
      changes: [{ path: "web/src/routes/login.tsx", status: "modified" }],
    });
    await renderBoard();
    const actor = host?.querySelector<HTMLSelectElement>('select[aria-label="当前身份"]');
    await act(async () => {
      if (actor) {
        setNativeValue(actor, "m-rev");
      }
    });
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.textContent).toContain("修改 web/src/routes/login.tsx");
        expect(host?.textContent).toContain("还有 1 个文件没有列在这里。");
      });
    });
    expect(listDevTeamTaskChanges).toHaveBeenCalledWith("team-1", "task-1", expect.anything());
    expect(host?.textContent).toContain("完成");
    expect(host?.textContent).toContain("退回");
  });

  it("lets the planner change the subject and write scopes", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    mutateDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    await renderBoard();
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.querySelector('input[aria-label="修改主题 task-1"]')).toBeTruthy();
      });
    });
    const subject = host?.querySelector<HTMLInputElement>('input[aria-label="修改主题 task-1"]');
    const scopes = host?.querySelector<HTMLInputElement>('input[aria-label="修改写范围 task-1"]');
    expect(subject?.value).toBe("补任务板");
    expect(scopes?.value).toBe("web/src/routes/teams");
    await act(async () => {
      if (subject) {
        setNativeValue(subject, "改过的主题");
      }
      if (scopes) {
        setNativeValue(scopes, "web/src/routes/login");
      }
    });
    const save = host?.querySelector<HTMLButtonElement>('button[aria-label="保存修改 task-1"]');
    expect(save?.disabled).toBe(false);
    await act(async () => {
      save?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(mutateDevTeamTask).toHaveBeenCalledWith("team-1", "task-1", {
      actorMemberId: "m-plan",
      action: "update",
      expectedRevision: 1,
      subject: "改过的主题",
      description: "只改团队页",
      writeScopes: ["web/src/routes/login"],
      blockedBy: [],
    });
  });

  it("lets the planner change the description and dependencies", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    mutateDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    await renderBoard();
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.querySelector('textarea[aria-label="修改说明 task-1"]')).toBeTruthy();
      });
    });
    const description = host?.querySelector<HTMLTextAreaElement>('textarea[aria-label="修改说明 task-1"]');
    const blockers = host?.querySelector<HTMLInputElement>('input[aria-label="修改依赖 task-1"]');
    const save = host?.querySelector<HTMLButtonElement>('button[aria-label="保存修改 task-1"]');
    expect(description?.value).toBe("只改团队页");
    expect(blockers?.value).toBe("");
    expect(save?.disabled).toBe(true);
    await act(async () => {
      if (description) {
        setNativeValue(description, "改过的说明");
      }
      if (blockers) {
        setNativeValue(blockers, "task-2");
      }
    });
    expect(save?.disabled).toBe(false);
    await act(async () => {
      save?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(mutateDevTeamTask).toHaveBeenCalledWith("team-1", "task-1", {
      actorMemberId: "m-plan",
      action: "update",
      expectedRevision: 1,
      subject: "补任务板",
      description: "改过的说明",
      writeScopes: ["web/src/routes/teams"],
      blockedBy: ["task-2"],
    });
  });

  it("does not offer subject edits on a completed task", async () => {
    listDevTeamTasks.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      tasks: [{ ...readyTask, status: "completed", ready: false }],
      updatedAt: "",
    });
    await renderBoard();
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.textContent).toContain("补任务板");
      });
    });
    expect(host?.querySelector('button[aria-label="保存修改 task-1"]')).toBeNull();
  });

  it("lets the planner add a task without writing it into the room", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    createDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    await renderBoard();

    const subject = host?.querySelector<HTMLInputElement>('input[aria-label="任务主题"]');
    expect(subject).toBeTruthy();
    await act(async () => {
      if (subject) {
        setNativeValue(subject, "补任务板");
      }
    });
    const form = subject?.closest("form");
    await act(async () => {
      form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(createDevTeamTask).toHaveBeenCalledWith("team-1", expect.objectContaining({
      actorMemberId: "m-plan",
      subject: "补任务板",
    }));
  });
});
