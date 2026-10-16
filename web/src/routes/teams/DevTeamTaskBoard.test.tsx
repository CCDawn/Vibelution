/** @vitest-environment happy-dom */

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TeamMember } from "../../api/types";
import type { DevTeamTaskList } from "../../api/devTeamTasks";
import { DevTeamTaskBoard, speakingTeamMemberId, speakingTeamMemberIdFromRoom } from "./DevTeamTaskBoard";

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
let client: QueryClient | null = null;

function setNativeValue(element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const prototype = Object.getPrototypeOf(element);
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

let showOperations = true;
function boardElement(speakingMemberId = "") {
  if (!client) {
    throw new Error("query client missing");
  }
  return (
    <QueryClientProvider client={client}>
      <DevTeamTaskBoard lang="zh" teamId="team-1" members={members} speakingMemberId={speakingMemberId}
        renderWorkspace={({display,operations}) => <><main data-task-display>{display}</main>{showOperations ? <aside data-task-operations>{operations}</aside> : null}</>} />
    </QueryClientProvider>
  );
}

async function renderBoard(speakingMemberId = "", selectFirst = true) {
  showOperations = true;
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(boardElement(speakingMemberId));
  });
  await act(async () => {
    await listDevTeamTasks.mock.results[0]?.value;
  });
  if (selectFirst) await selectTask();
}

async function setSpeaker(speakingMemberId: string) {
  await act(async () => {
    root?.render(boardElement(speakingMemberId));
  });
}

async function selectTask(taskId = "task-1") {
  await act(async () => {
    await vi.waitFor(() => expect(host?.querySelector(`button[aria-label="选择任务 ${taskId}"]`)).toBeTruthy());
    host?.querySelector<HTMLButtonElement>(`button[aria-label="选择任务 ${taskId}"]`)?.click();
  });
}

async function openEditor(taskId = "task-1") {
  await selectTask(taskId);
  await act(async () => {
    await vi.waitFor(() => expect(host?.querySelector(`button[aria-label="编辑 ${taskId}"]`)).toBeTruthy());
    host?.querySelector<HTMLButtonElement>(`button[aria-label="编辑 ${taskId}"]`)?.click();
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
    client = null;
  });

  it("keeps cards read-only and moves selected task editing to the operations slot", async () => {
    listDevTeamTasks.mockResolvedValue({schemaVersion:1,teamId:"team-1",tasks:[readyTask],updatedAt:""});
    await renderBoard("", false);
    expect(host?.querySelector('[data-task-operations]')?.textContent).toContain("选择任务后");
    expect(host?.querySelector('button[aria-label="编辑 task-1"]')).toBeNull();
    await openEditor();
    expect(host?.querySelector('[data-task-display] input,[data-task-display] textarea')).toBeNull();
    expect(host?.querySelector('input[aria-label="修改主题 task-1"]')?.closest('[data-task-operations]')).toBeTruthy();
    expect(host?.querySelector('[role="dialog"]')).toBeNull();
  });

  it("preserves the edit draft and revision across a responsive pane unmount", async () => {
    listDevTeamTasks.mockResolvedValue({schemaVersion:1,teamId:"team-1",tasks:[readyTask],updatedAt:""});
    mutateDevTeamTask.mockResolvedValue({schemaVersion:1,teamId:"team-1",tasks:[],updatedAt:""});
    await renderBoard(); await openEditor();
    await act(async()=>{setNativeValue(host!.querySelector('input[aria-label="修改主题 task-1"]')!,"抽屉草稿");});
    showOperations=false;await setSpeaker("");
    expect(host?.querySelector('input[aria-label="修改主题 task-1"]')).toBeNull();
    listDevTeamTasks.mockResolvedValue({schemaVersion:1,teamId:"team-1",tasks:[{...readyTask,revision:2,subject:"远端刷新"}],updatedAt:""});
    await act(async()=>{await client?.refetchQueries({queryKey:["teams","team-1","dev-tasks"],exact:true});});
    showOperations=true;await setSpeaker("");
    expect(host?.querySelector<HTMLInputElement>('input[aria-label="修改主题 task-1"]')?.value).toBe("抽屉草稿");
    await act(async()=>{host?.querySelector<HTMLButtonElement>('button[aria-label="保存修改 task-1"]')?.click();});
    expect(mutateDevTeamTask).toHaveBeenCalledWith("team-1","task-1",expect.objectContaining({expectedRevision:1,subject:"抽屉草稿"}));
  });

  it("does not discard a different task draft when an earlier save finishes", async () => {
    const other={...readyTask,id:"task-2",subject:"另一个任务"};
    listDevTeamTasks.mockResolvedValue({schemaVersion:1,teamId:"team-1",tasks:[readyTask,other],updatedAt:""});
    const saved=deferred<DevTeamTaskList>();mutateDevTeamTask.mockReturnValue(saved.promise);
    await renderBoard();await openEditor();
    await act(async()=>{setNativeValue(host!.querySelector('input[aria-label="修改主题 task-1"]')!,"A已提交");host?.querySelector<HTMLButtonElement>('button[aria-label="保存修改 task-1"]')?.click();});
    await openEditor("task-2");
    await act(async()=>{setNativeValue(host!.querySelector('input[aria-label="修改主题 task-2"]')!,"B本地草稿");});
    await act(async()=>{saved.resolve({schemaVersion:1,teamId:"team-1",tasks:[{...readyTask,revision:2,subject:"A已提交"},other],updatedAt:""});await saved.promise;});
    expect(host?.querySelector<HTMLInputElement>('input[aria-label="修改主题 task-2"]')?.value).toBe("B本地草稿");
  });

  it("lets an engineer claim a ready task and shows the overlap warning", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    mutateDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    await renderBoard("m-a");
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.textContent).toContain("与 task-2 的写范围重叠");
      });
    });
    expect(host?.querySelector('select[aria-label="当前身份"]')).toBeNull();
    expect(host?.querySelector('[aria-label="当前身份"]')?.textContent).toBe("工程师A · 开发工程师 A");
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
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.textContent).toContain("0 个任务");
        expect(host?.querySelector('button[aria-label="认领 task-1"]')).toBeNull();
      });
    });
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
    await renderBoard("m-rev");
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
    await openEditor();
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
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask, { ...readyTask, id: "task-2", subject: "准备接口", status: "completed" }], updatedAt: "" });
    mutateDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    await renderBoard();
    await openEditor();
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.querySelector('textarea[aria-label="修改说明 task-1"]')).toBeTruthy();
      });
    });
    const description = host?.querySelector<HTMLTextAreaElement>('textarea[aria-label="修改说明 task-1"]');
    const blockers = host?.querySelector<HTMLButtonElement>('button[aria-label="修改依赖 task-1"]');
    const save = host?.querySelector<HTMLButtonElement>('button[aria-label="保存修改 task-1"]');
    expect(description?.value).toBe("只改团队页");
    expect(blockers?.textContent).toContain("搜索并选择依赖任务");
    expect(save?.disabled).toBe(true);
    await act(async () => {
      if (description) {
        setNativeValue(description, "改过的说明");
      }
      blockers?.click();
    });
    await act(async () => {
      document.querySelector<HTMLInputElement>('input[aria-label="task-2 · 准备接口 · 完成"]')?.click();
      Array.from(document.querySelectorAll("button")).find((button) => button.textContent === "完成选择")?.click();
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

  it("filters tasks without hiding dependency choices or allowing a self dependency", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [
      readyTask,
      { ...readyTask, id: "task-2", subject: "准备接口", status: "completed", ready: false },
    ], updatedAt: "" });
    await renderBoard();
    await act(async () => {
      await vi.waitFor(() => expect(host?.querySelectorAll("article").length).toBe(2));
      Array.from(host?.querySelectorAll("button[aria-pressed]") ?? []).find((button) => button.textContent?.startsWith("待办"))?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(host?.querySelectorAll("article").length).toBe(1);
    await openEditor();
    await act(async () => { host?.querySelector<HTMLButtonElement>('button[aria-label="修改依赖 task-1"]')?.click(); });
    expect(document.querySelector('input[aria-label="task-2 · 准备接口 · 完成"]')).toBeTruthy();
    expect(document.querySelector('input[aria-label="task-1 · 补任务板 · 待办"]')).toBeNull();
    await act(async () => {
      const search = document.querySelector<HTMLInputElement>('input[aria-label="搜索依赖任务"]');
      if (search) setNativeValue(search, "不存在的任务");
    });
    expect(document.body.textContent).toContain("没有匹配的任务");
    await act(async () => {
      Array.from(document.querySelectorAll("button")).find((button) => button.textContent === "完成选择")?.click();
      Array.from(host?.querySelectorAll("button[aria-pressed]") ?? []).find((button) => button.textContent?.startsWith("退回"))?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(host?.textContent).toContain("没有符合筛选条件的任务");
    await act(async () => {
      Array.from(host?.querySelectorAll("button") ?? []).find((button) => button.textContent === "清除筛选")?.click();
    });
    expect(host?.querySelectorAll("article").length).toBe(2);
  });

  it("lets the planner add a task without writing it into the room", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    createDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    await renderBoard("", false);

    expect(host?.querySelector('input[aria-label="任务主题"]')).toBeNull();
    await act(async () => {
      Array.from(host?.querySelectorAll("button") ?? []).find((button) => button.textContent === "新建任务")?.click();
    });
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
    await act(async () => {
      await vi.waitFor(() => expect(host?.querySelector('input[aria-label="任务主题"]')).toBeNull());
    });
  });

  it("keeps planning forms folded and shows owner, dependencies and output", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [
      { ...readyTask, ownerMemberId: "m-a", ownerName: "工程师A", ownerRole: "开发工程师 A", blockedBy: ["task-2"], ready: false },
      { ...readyTask, id: "task-2", subject: "准备接口", status: "completed", workspaceBranch: "codex/api", ready: false },
    ], updatedAt: "" });
    await renderBoard();
    await act(async () => {
      await vi.waitFor(() => expect(host?.textContent).toContain("task-2 · 准备接口 (完成)"));
    });
    expect(host?.querySelector('input[aria-label="修改主题 task-1"]')).toBeNull();
    expect(host?.querySelector('input[aria-label="任务主题"]')).toBeNull();
    expect(host?.querySelector('[aria-label="任务概览"]')?.textContent).toContain("完成 1");
    expect(host?.textContent).toContain("工程师A · 开发工程师 A");
    expect(host?.querySelector("[data-task-display] input, [data-task-display] textarea")).toBeNull();
    expect(host?.textContent).toContain("工作区 codex/api");
    expect(listDevTeamTaskChanges).not.toHaveBeenCalled();
  });

  it("preserves a draft and its original revision when tasks refresh, and keeps it after a conflict", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    mutateDevTeamTask.mockRejectedValue(new Error("任务已更新，请重新读取"));
    await renderBoard();
    await openEditor();
    const subject = host?.querySelector<HTMLInputElement>('input[aria-label="修改主题 task-1"]');
    await act(async () => { if (subject) setNativeValue(subject, "本地草稿"); });
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [{ ...readyTask, revision: 2, subject: "远端新主题" }], updatedAt: "" });
    await act(async () => { await client?.refetchQueries({ queryKey: ["teams", "team-1", "dev-tasks"], exact: true }); });
    expect(subject?.value).toBe("本地草稿");
    await act(async () => { host?.querySelector<HTMLButtonElement>('button[aria-label="保存修改 task-1"]')?.click(); });
    expect(mutateDevTeamTask).toHaveBeenCalledWith("team-1", "task-1", expect.objectContaining({ expectedRevision: 1, subject: "本地草稿" }));
    await act(async () => { await vi.waitFor(() => expect(host?.querySelector('[role="alert"]')?.textContent).toContain("任务已更新，请重新读取")); });
    expect(subject?.value).toBe("本地草稿");
  });

  it.each(["claim", "create"] as const)("cancels reads before and during %s so late GETs cannot replace the mutation result", async (action) => {
    const original: DevTeamTaskList = { schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" };
    const authoritative: DevTeamTaskList = {
      ...original,
      tasks: action === "claim"
        ? [{ ...readyTask, revision: 2, status: "in_progress", ready: false, ownerMemberId: "m-a", ownerRole: "开发工程师 A" }]
        : [readyTask, { ...readyTask, id: "task-created", subject: "新任务" }],
    };
    const readBeforeWrite = deferred<DevTeamTaskList>();
    const readDuringWrite = deferred<DevTeamTaskList>();
    const write = deferred<DevTeamTaskList>();
    const signals: AbortSignal[] = [];
    listDevTeamTasks.mockResolvedValueOnce(original)
      .mockImplementationOnce((_teamId: string, init: RequestInit) => {
        signals.push(init.signal as AbortSignal);
        return readBeforeWrite.promise;
      })
      .mockImplementationOnce((_teamId: string, init: RequestInit) => {
        signals.push(init.signal as AbortSignal);
        return readDuringWrite.promise;
      });
    mutateDevTeamTask.mockReturnValue(write.promise);
    createDevTeamTask.mockReturnValue(write.promise);
    await renderBoard(action === "claim" ? "m-a" : "m-plan");
    await act(async () => {
      await vi.waitFor(() => expect(host?.querySelector('article[aria-label="补任务板"]')).toBeTruthy());
    });
    if (action === "create") {
      await act(async () => {
        Array.from(host?.querySelectorAll("button") ?? []).find((button) => button.textContent === "新建任务")?.click();
      });
      await act(async () => {
        const subject = host?.querySelector<HTMLInputElement>('input[aria-label="任务主题"]');
        if (subject) setNativeValue(subject, "新任务");
      });
    }
    const key = { queryKey: ["teams", "team-1", "dev-tasks"], exact: true };
    let beforeRefetch: Promise<void> | undefined;
    let duringRefetch: Promise<void> | undefined;
    await act(async () => { beforeRefetch = client?.refetchQueries(key); });
    expect(signals[0]?.aborted).toBe(false);
    await act(async () => {
      if (action === "claim") host?.querySelector<HTMLButtonElement>('button[aria-label="认领 task-1"]')?.click();
      else host?.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await act(async () => {
      await vi.waitFor(() => expect(action === "claim" ? mutateDevTeamTask : createDevTeamTask).toHaveBeenCalledOnce());
    });
    expect(signals[0]?.aborted).toBe(true);
    // A polling read can also start while the POST is still pending.
    await act(async () => { duringRefetch = client?.refetchQueries(key); });
    expect(signals[1]?.aborted).toBe(false);
    await act(async () => { write.resolve(authoritative); });
    await act(async () => {
      await vi.waitFor(() => expect(client?.getQueryData(key.queryKey)).toEqual(authoritative));
    });
    expect(signals[1]?.aborted).toBe(true);
    // Ignore the abort in the mocked transport and deliver both stale responses late.
    await act(async () => {
      readBeforeWrite.resolve(original);
      readDuringWrite.resolve(original);
      await Promise.all([beforeRefetch, duringRefetch]);
    });
    expect(client?.getQueryData(key.queryKey)).toEqual(authoritative);
    await act(async () => {
      await vi.waitFor(() => {
        if (action === "claim") expect(host?.querySelector('button[aria-label="认领 task-1"]')).toBeNull();
        else expect(host?.querySelector('article[aria-label="新任务"]')).toBeTruthy();
      });
    });
  });

  it("uses the current revision and review note when a reviewer sends work back", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [{ ...readyTask, status: "in_progress", revision: 7 }], updatedAt: "" });
    listDevTeamTaskChanges.mockResolvedValue({ available: true, workspace: false, truncated: 0, changes: [] });
    mutateDevTeamTask.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [], updatedAt: "" });
    await renderBoard("m-rev");
    await act(async () => {
      await vi.waitFor(() => expect(host?.querySelector('input[aria-label="退回说明 task-1"]')).toBeTruthy());
      const note = host?.querySelector<HTMLInputElement>('input[aria-label="退回说明 task-1"]');
      if (note) setNativeValue(note, "补齐验收结果");
    });
    await act(async () => { Array.from(host?.querySelectorAll("button") ?? []).find((button) => button.textContent === "退回")?.click(); });
    expect(mutateDevTeamTask).toHaveBeenCalledWith("team-1", "task-1", expect.objectContaining({ actorMemberId: "m-rev", action: "rework", expectedRevision: 7, reviewNote: "补齐验收结果" }));
    expect(host?.querySelector('button[aria-label="编辑 task-1"]')).toBeNull();
  });

  it("follows the speaking member and keeps that identity when speaking stops", async () => {
    listDevTeamTasks.mockResolvedValue({ schemaVersion: 1, teamId: "team-1", tasks: [readyTask], updatedAt: "" });
    await renderBoard("m-a");
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.querySelector('[aria-label="当前身份"]')?.textContent).toBe("工程师A · 开发工程师 A");
        expect(host?.querySelector('button[aria-label="认领 task-1"]')).toBeTruthy();
      });
    });
    expect(host?.querySelector('button[aria-label="保存修改 task-1"]')).toBeNull();

    await setSpeaker("");
    expect(host?.querySelector('[aria-label="当前身份"]')?.textContent).toBe("工程师A · 开发工程师 A");
    expect(host?.querySelector('button[aria-label="认领 task-1"]')).toBeTruthy();

    await setSpeaker("m-rev");
    await act(async () => {
      await vi.waitFor(() => {
        expect(host?.querySelector('[aria-label="当前身份"]')?.textContent).toBe("评审员 · 评审员");
      });
    });
    expect(host?.querySelector('button[aria-label="认领 task-1"]')).toBeNull();
    expect(host?.querySelector('button[aria-label="保存修改 task-1"]')).toBeNull();
  });
});

describe("speaking team member", () => {
  const roomMembers = members;

  it("uses the running speaker ahead of an earlier turn", () => {
    const participants = [
      { participantId: "p-plan", agentId: "a1", teamRole: "规划师" },
      { participantId: "p-a", agentId: "a2", teamRole: "开发工程师 A" },
      { participantId: "p-rev", agentId: "a3", teamRole: "评审员" },
    ];
    expect(speakingTeamMemberId(roomMembers, participants, {
      status: "running",
      speakerProgress: [
        { participantId: "p-plan", state: "queued", updatedAt: "2026-10-08T00:00:03Z" },
        { participantId: "p-a", state: "running", updatedAt: "2026-10-08T00:00:01Z" },
        { participantId: "p-rev", state: "settled", updatedAt: "2026-10-08T00:00:02Z" },
      ],
    })).toBe("m-a");
    expect(speakingTeamMemberId(roomMembers, participants, {
      status: "running",
      speakerProgress: [
        { participantId: "p-a", state: "running", updatedAt: "2026-10-08T00:00:01Z" },
        { participantId: "p-rev", state: "running", updatedAt: "2026-10-08T00:00:02Z" },
      ],
    })).toBe("m-rev");
  });

  it("matches a speaker by role when the agent id is missing", () => {
    expect(speakingTeamMemberId(members, [
      { participantId: "p-rev", teamRole: "评审员" },
    ], {
      status: "stopping",
      speakerProgress: [{ participantId: "p-rev", state: "running" }],
    })).toBe("m-rev");
  });

  it("returns nobody when the round is idle or the speaker is not on the team", () => {
    const participants = [{ participantId: "p-a", agentId: "a2", teamRole: "开发工程师 A" }];
    expect(speakingTeamMemberId(members, participants, {
      status: "completed",
      speakerProgress: [{ participantId: "p-a", state: "running" }],
    })).toBe("");
    expect(speakingTeamMemberId(members, participants, {
      status: "queued",
      speakerProgress: [{ participantId: "p-a", state: "queued" }],
    })).toBe("");
    expect(speakingTeamMemberId(members, participants, {
      status: "running",
      speakerProgress: [{ participantId: "p-missing", state: "running" }],
    })).toBe("");
    expect(speakingTeamMemberIdFromRoom(members, {
      activeRoundId: "round-live",
      participants,
      rounds: [
        { roundId: "round-old", status: "completed", speakerProgress: [{ participantId: "p-a", state: "running" }] },
        { roundId: "round-live", status: "running", speakerProgress: [{ participantId: "p-a", state: "running" }] },
      ],
    })).toBe("m-a");
    expect(speakingTeamMemberIdFromRoom(members, null)).toBe("");
  });

  it("uses the last speaker of a finished round when nobody is speaking", () => {
    const participants = [
      { participantId: "p-plan", agentId: "a1", teamRole: "规划师" },
      { participantId: "p-a", agentId: "a2", teamRole: "开发工程师 A" },
      { participantId: "p-rev", agentId: "a3", teamRole: "评审员" },
    ];
    const finished = {
      roundId: "round-done",
      status: "completed",
      messages: [
        { participantId: "p-plan", timestamp: "2026-10-08T00:00:01Z" },
        { participantId: "p-rev", timestamp: "2026-10-08T00:00:02Z" },
      ],
      speakerProgress: [
        { participantId: "p-plan", state: "settled", status: "completed", updatedAt: "2026-10-08T00:00:01Z" },
        { participantId: "p-rev", state: "settled", status: "completed", updatedAt: "2026-10-08T00:00:02Z" },
        { participantId: "p-a", state: "settled", status: "stopped", updatedAt: "2026-10-08T00:00:03Z" },
      ],
    };
    expect(speakingTeamMemberId(members, participants, finished)).toBe("m-rev");
    expect(speakingTeamMemberId(members, participants, {
      status: "completed",
      messages: [
        { participantId: "p-rev" },
        { participantId: "user-1" },
      ],
    })).toBe("m-rev");
    expect(speakingTeamMemberId(members, participants, {
      status: "running",
      messages: [{ participantId: "p-a" }],
      speakerProgress: [
        { participantId: "p-a", state: "settled", status: "completed", updatedAt: "2026-10-08T00:00:01Z" },
        { participantId: "p-plan", state: "queued", updatedAt: "2026-10-08T00:00:02Z" },
      ],
    })).toBe("m-a");
    expect(speakingTeamMemberId(members, participants, {
      status: "completed",
      speakerProgress: [
        { participantId: "p-rev", state: "settled", status: "completed", updatedAt: "2026-10-08T00:00:02Z" },
        { participantId: "p-a", state: "settled", status: "stopped", updatedAt: "2026-10-08T00:00:03Z" },
      ],
    })).toBe("m-rev");
    expect(speakingTeamMemberIdFromRoom(members, {
      participants,
      rounds: [
        { roundId: "round-old", status: "completed", messages: [{ participantId: "p-plan" }] },
        finished,
      ],
    })).toBe("m-rev");
  });
});
