// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLauncherBranchInstances, selectLauncherProject } from "../../api/launcher";
import { getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus } from "../../api/launcherAssistant";
import { LauncherAssistantWorkspaceRoute } from "./LauncherAssistantWorkspaceRoute";

vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
vi.mock("../../api/launcher", () => ({
  getLauncherBranchInstances: vi.fn(), selectLauncherProject: vi.fn(),
  isLauncherProjectNotSelected: (error: unknown) => error instanceof Error && error.message === "not-selected",
}));
vi.mock("../../api/launcherAssistant", () => ({ getLauncherAssistantStatus: vi.fn(), getLauncherAssistantDetail: vi.fn(), getLauncherAssistantDispatches: vi.fn() }));
vi.mock("./LauncherAssistantRoute", () => ({ LauncherAssistantRoute: (props: any) => <div data-computer-requested={String(Boolean(props.computerRequested))}>native dialogue<input aria-label="对话草稿" />{props.entryIntent ? <><button>{props.entryIntent.label}</button><output data-task-entry>{props.entryIntent.message}</output></> : null}</div> }));
vi.mock("./assistantTasks/LauncherAssistantTaskCards", () => ({ LauncherAssistantTaskCards: ({ onReview, onApproval }: any) => <>
  <button onClick={() => onReview({ projectId: "project-1", dispatchId: "dispatch-1" })}>核对示例任务</button>
  <button onClick={() => onApproval()}>处理示例授权</button>
</> }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root, container: HTMLDivElement, client: QueryClient;
let navigate: NavigateFunction;
function Workspace() { navigate = useNavigate(); return <LauncherAssistantWorkspaceRoute />; }
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getLauncherAssistantStatus).mockResolvedValue({ assistant: { agentId: "agent", directSessionId: "session", displayName: "小鲸" } });
  vi.mocked(getLauncherAssistantDetail).mockResolvedValue({ id: "session", messages: [{ id: "one" }, { id: "two" }] } as Awaited<ReturnType<typeof getLauncherAssistantDetail>>);
  vi.mocked(getLauncherAssistantDispatches).mockResolvedValue([]);
  vi.mocked(getLauncherBranchInstances).mockResolvedValue({ items: [] } as Awaited<ReturnType<typeof getLauncherBranchInstances>>);
  vi.mocked(selectLauncherProject).mockResolvedValue({ connected: true });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  window.vibelutionLauncherBrowser = { invoke: vi.fn(async () => ({ pages: [], activePageId: null, takeover: false })), onChanged: () => () => {} };
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); delete window.vibelutionLauncherBrowser; });
async function render(panel: string) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/launcher/assistant?panel=${panel}`]}>
    <Workspace />
  </MemoryRouter></QueryClientProvider>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 50)));
}

describe("Launcher assistant workspace", () => {
  it("opens task cards without replacing the conversation or losing its draft", async () => {
    await render("dialogue");
    const draft = container.querySelector<HTMLInputElement>('input[aria-label="对话草稿"]')!;
    draft.value = "保留当前输入";
    await act(async () => { await navigate("/launcher/assistant?panel=tasks"); });
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("核对示例任务");
    expect(container.querySelector('input[aria-label="对话草稿"]')).toBe(draft);
    await act(async () => { [...document.querySelectorAll("button")].find(node => node.textContent === "核对示例任务")!.click(); });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('input[aria-label="对话草稿"]')).toBe(draft);
    expect(draft.value).toBe("保留当前输入");
    expect(container.querySelector("[data-task-entry]")?.textContent).toContain('"dispatchId":"dispatch-1"');
    expect(container.querySelector("[data-task-entry]")?.textContent).toContain("不要重试、重派、停止、重启、部署或修改任何内容");
    expect(getLauncherAssistantDetail).not.toHaveBeenCalled();
    expect(selectLauncherProject).not.toHaveBeenCalled();
  });

  it("returns to the existing approval conversation without submitting a decision", async () => {
    await render("tasks");
    await act(async () => { [...document.querySelectorAll("button")].find(node => node.textContent === "处理示例授权")!.click(); });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(container.textContent).toContain("native dialogue");
    expect(container.querySelector("[data-task-entry]")).toBeNull();
    expect(getLauncherAssistantDispatches).not.toHaveBeenCalled();
  });

  it("uses one mounted conversation across dialogue and legacy browser URLs", async () => {
    await render("dialogue");
    const draft = container.querySelector<HTMLInputElement>('input[aria-label="对话草稿"]')!;
    draft.value = "未发出的内容";
    expect(container.querySelector('button[aria-label="打开网页"]')).toBeTruthy();
    await act(async () => { await navigate("/launcher/assistant?panel=browser"); });
    expect(container.querySelector('input[aria-label="对话草稿"]')).toBe(draft);
    expect(container.querySelector('button[aria-label="打开网页"]')).toBeNull();
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="收起网页"]')!.click());
    await act(async () => { await navigate("/launcher/assistant"); });
    expect(container.querySelector('input[aria-label="对话草稿"]')).toBe(draft);
    expect(draft.value).toBe("未发出的内容");
    expect(container.querySelector('button[aria-label="打开网页"]')).toBeTruthy();
  });
  it.each(["overview", "dispatches"])("falls back to dialogue for the removed %s page without its queries", async panel => {
    await render(panel);
    expect(container.textContent).toContain("native dialogue");
    expect(getLauncherAssistantStatus).not.toHaveBeenCalled();
    expect(getLauncherAssistantDetail).not.toHaveBeenCalled();
    expect(getLauncherAssistantDispatches).not.toHaveBeenCalled();
    expect(getLauncherBranchInstances).not.toHaveBeenCalled();
    expect(selectLauncherProject).not.toHaveBeenCalled();
  });
  it.each([
    ["affairs", "查看我的待办与提醒"],
    ["preferences", "查看当前对话偏好"],
    ["assistant-settings", "查看助理设置"],
    ["computer", "native dialogue"],
  ])("moves the legacy %s link into the conversation without loading its old page", async (panel, expected) => {
    await render(panel);
    expect(container.textContent).toContain(expected);
    expect(container.textContent).toContain("native dialogue");
    expect(getLauncherAssistantStatus).not.toHaveBeenCalled();
    expect(getLauncherAssistantDispatches).not.toHaveBeenCalled();
    expect(getLauncherBranchInstances).not.toHaveBeenCalled();
    expect(container.querySelector('[data-computer-requested="true"]') !== null).toBe(panel === "computer");
  });
});
