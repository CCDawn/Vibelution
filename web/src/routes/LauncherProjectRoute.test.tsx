// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLauncherBranchInstances, selectLauncherProject } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { LauncherProjectRoute } from "./LauncherProjectRoute";

vi.mock("../api/launcher", async importOriginal => ({
  ...await importOriginal<typeof import("../api/launcher")>(),
  getLauncherBranchInstances: vi.fn(), selectLauncherProject: vi.fn(),
}));
vi.mock("../i18n/useLauncherLanguage", () => ({ useLauncherLanguage: () => "zh" }));
vi.mock("./LauncherRoute", () => ({ LauncherRoute: () => <div>项目管理页面</div> }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root, host: HTMLDivElement, client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); client.clear(); });
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}><LauncherProjectRoute /></QueryClientProvider>));
  await vi.waitFor(() => { expect(getLauncherBranchInstances).toHaveBeenCalled(); });
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
}
function selectButton() {
  const button = [...host.querySelectorAll("button")].find(node => node.textContent?.includes("选择项目"));
  if (!button) throw new Error("Missing select project button");
  return button;
}

describe("Launcher project selection", () => {
  it("keeps the unselected state without invalidating data when the selection is cancelled", async () => {
    vi.mocked(getLauncherBranchInstances).mockRejectedValue(new Error("LAUNCHER_PROJECT_NOT_SELECTED"));
    vi.mocked(selectLauncherProject).mockResolvedValue({ connected: false });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await render();
    expect(host.textContent).toContain("选择一个本地项目");
    await act(async () => selectButton().click());
    expect(selectLauncherProject).toHaveBeenCalledOnce();
    expect(invalidate).not.toHaveBeenCalled();
    expect(host.textContent).toContain("选择一个本地项目");
    expect(host.textContent).not.toContain("项目管理页面");
  });
  it("refreshes branch and status data once the selected project is connected", async () => {
    vi.mocked(getLauncherBranchInstances).mockRejectedValueOnce(new Error("LAUNCHER_PROJECT_NOT_SELECTED"))
      .mockResolvedValueOnce({ items: [] } as Awaited<ReturnType<typeof getLauncherBranchInstances>>);
    vi.mocked(selectLauncherProject).mockResolvedValue({ connected: true });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await render();
    await act(async () => selectButton().click());
    await vi.waitFor(() => expect(host.textContent).toContain("项目管理页面"));
    expect(selectLauncherProject).toHaveBeenCalledOnce();
    expect(invalidate.mock.calls.map(([filters]) => filters?.queryKey)).toEqual(expect.arrayContaining([
      queryKeys.launcherBranchInstances(), queryKeys.launcherStatus(),
    ]));
    expect(getLauncherBranchInstances).toHaveBeenCalledTimes(2);
  });
  it("does not present a real project read error as an unselected project", async () => {
    vi.mocked(getLauncherBranchInstances).mockRejectedValue(new Error("registry unavailable"));
    await render();
    expect(host.textContent).toContain("项目管理页面");
    expect(host.textContent).not.toContain("选择一个本地项目");
    expect(selectLauncherProject).not.toHaveBeenCalled();
  });
});
