// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LauncherAssistantStatus, LauncherManagementPermission } from "../../api/launcherAssistant";
import type { AgentPermissionPreset } from "../../api/types";
import {
  readLauncherManagementStatus, reconcileLauncherManagementPermission, useLauncherManagementPermission,
  type LauncherManagementPermissionControlState,
} from "./useLauncherManagementPermission";
import { LauncherManagementPermissionControl } from "./LauncherManagementPermissionControl";

const key = ["launcher-assistant", "status"];
let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let state: LauncherManagementPermissionControlState;
let server: LauncherAssistantStatus;
let invoke: ReturnType<typeof vi.fn>;
let write: (request: { preset: AgentPermissionPreset; expectedRevision: number }) => Promise<unknown>;
const status = (permission?: LauncherManagementPermission): LauncherAssistantStatus => ({
  assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" },
  settings: { ok: true, preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" },
    displayName: "Assistant", modelId: "model", ...(permission ? { managementPermission: permission } : {}) },
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function settle() { await act(async () => { await new Promise(done => setTimeout(done, 10)); }); }
async function renderPermission(initial = status({ preset: "request_approval", revision: 0 })) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  server = initial;
  write = async request => {
    const permission = { preset: request.preset, revision: request.expectedRevision + 1 };
    server = status(permission);
    return permission;
  };
  invoke = vi.fn(async request => {
    if (request.operation === "status") return server;
    if (request.operation === "setManagementPermissionPreset") return write(request);
    throw new Error("unexpected operation");
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(key, initial);
  function Harness() {
    const query = useQuery({ queryKey: key, queryFn: () => readLauncherManagementStatus(() => client.getQueryData(key)) });
    state = useLauncherManagementPermission(query.data, "zh");
    return <LauncherManagementPermissionControl state={state} lang="zh" />;
  }
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>));
  await settle();
}
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined; client?.clear(); container?.remove(); vi.unstubAllGlobals();
});

describe("Launcher management-permission state", () => {
  it("keeps old hosts disabled with no invented selected preset", async () => {
    await renderPermission(status());
    expect(state.value).toBeNull();
    expect(container.textContent).toContain("当前版本暂不支持");
    expect(container.querySelector<HTMLButtonElement>("button")?.disabled).toBe(true);
    await act(async () => state.choose("full_access"));
    expect(invoke).not.toHaveBeenCalled();
    expect(state.confirmationOpen).toBe(false);
  });

  it("updates the selection only after a verified receipt and suppresses duplicate writes", async () => {
    await renderPermission();
    const receipt = deferred<LauncherManagementPermission>();
    write = () => receipt.promise;
    await act(async () => { state.choose("auto_review"); state.choose("full_access"); });
    expect(state.pending).toBe(true); expect(state.value).toBe("request_approval");
    expect(invoke.mock.calls.filter(([request]) => request.operation === "setManagementPermissionPreset")).toHaveLength(1);
    server = status({ preset: "auto_review", revision: 1 });
    await act(async () => receipt.resolve({ preset: "auto_review", revision: 1 }));
    await settle();
    expect(state.value).toBe("auto_review"); expect(state.pending).toBe(false);
    expect(invoke.mock.calls.some(([request]) => request.operation === "status")).toBe(true);
  });

  it("requires explicit full-access confirmation and cancellation sends nothing", async () => {
    await renderPermission();
    await act(async () => state.choose("full_access"));
    expect(state.confirmationOpen).toBe(true);
    expect(document.body.textContent).toContain("直接执行重启、永久删除等管理操作");
    expect(document.body.textContent).toContain("不会增加项目或私人资料的访问权限");
    expect(document.body.textContent).not.toContain("toolPolicy");
    expect(invoke).not.toHaveBeenCalled();
    await act(async () => state.closeConfirmation());
    expect(invoke).not.toHaveBeenCalled();
    await act(async () => state.choose("full_access"));
    const confirm = [...document.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === "启用完全访问")!;
    await act(async () => confirm.click()); await settle();
    expect(state.value).toBe("full_access");
    expect(invoke.mock.calls.filter(([request]) => request.operation === "setManagementPermissionPreset")).toHaveLength(1);
  });

  it("disables a host that advertises settings but lacks the mutation capability", async () => {
    await renderPermission();
    write = async () => { throw new Error("ASSISTANT_REQUEST_INVALID"); };
    await act(async () => state.choose("auto_review")); await settle();
    expect(state.value).toBe("request_approval"); expect(state.disabled).toBe(true);
    expect(state.error).toContain("更新 Launcher");
    await act(async () => state.choose("full_access"));
    expect(state.confirmationOpen).toBe(false);
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("keeps a temporarily unavailable settings service retryable and succeeds on a later explicit choice", async () => {
    await renderPermission();
    const availableWrite = write;
    write = async () => { throw new Error("ASSISTANT_PERMISSION_UNAVAILABLE"); };
    await act(async () => state.choose("auto_review")); await settle();
    expect(state.value).toBe("request_approval"); expect(state.disabled).toBe(false);
    expect(state.error).toBe("权限设置暂不可用，请稍后重试。");
    expect(container.textContent).not.toContain("更新 Launcher");
    write = availableWrite;
    await act(async () => state.choose("auto_review")); await settle();
    expect(state.value).toBe("auto_review"); expect(state.disabled).toBe(false); expect(state.error).toBe("");
    expect(invoke.mock.calls.filter(([request]) => request.operation === "setManagementPermissionPreset")).toHaveLength(2);
  });

  it("re-reads a conflict without retrying the rejected escalation", async () => {
    await renderPermission();
    write = async () => { server = status({ preset: "auto_review", revision: 1 }); throw new Error("ASSISTANT_PERMISSION_CONFLICT"); };
    await act(async () => state.choose("full_access"));
    await act(async () => state.confirmFullAccess()); await settle();
    expect(state.value).toBe("auto_review"); expect(state.error).toContain("请重新选择");
    expect(container.querySelector('[role="alert"]')).toBeTruthy();
    expect(invoke.mock.calls.filter(([request]) => request.operation === "setManagementPermissionPreset")).toHaveLength(1);
    expect(invoke.mock.calls.filter(([request]) => request.operation === "status")).toHaveLength(1);
  });

  it.each(["transport", "bad revision", "same revision"])("retains the current level when the result is %s", async mode => {
    await renderPermission();
    write = async () => {
      if (mode === "transport") throw new Error("ASSISTANT_TRANSPORT_FAILED");
      return { preset: "auto_review", revision: mode === "same revision" ? 0 : 20 };
    };
    await act(async () => state.choose("auto_review")); await settle();
    expect(state.value).toBe("request_approval"); expect(state.error).toContain("保存尚未确认");
    expect(state.pending).toBe(false);
  });

  it("rejects a confirmation whose revision changed while the dialog was open", async () => {
    await renderPermission();
    await act(async () => state.choose("full_access"));
    await act(async () => client.setQueryData(key, status({ preset: "auto_review", revision: 1 })));
    await settle();
    await act(async () => state.confirmFullAccess());
    expect(state.error).toContain("重新选择"); expect(invoke).not.toHaveBeenCalled();
  });

  it("reads the current cache after an old status request resolves and keeps revisions monotonic", async () => {
    await renderPermission();
    const old = deferred<LauncherAssistantStatus>();
    invoke.mockImplementationOnce(() => old.promise);
    const pending = readLauncherManagementStatus(() => client.getQueryData(key));
    await act(async () => state.choose("auto_review")); await settle();
    expect(state.value).toBe("auto_review");
    old.resolve(status({ preset: "request_approval", revision: 0 }));
    const reconciled = await pending;
    expect(reconciled.settings?.managementPermission).toEqual({ preset: "auto_review", revision: 1 });
    const newer = status({ preset: "request_approval", revision: 2 });
    expect(reconcileLauncherManagementPermission(newer, reconciled)).toBe(newer);
    const another = { ...status({ preset: "request_approval", revision: 0 }), assistant: { agentId: "b", directSessionId: "other", displayName: "Other" } };
    expect(reconcileLauncherManagementPermission(another, reconciled)).toBe(another);
    expect(reconcileLauncherManagementPermission(status(), reconciled).settings?.managementPermission).toBeUndefined();
  });
});
