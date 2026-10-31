/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LauncherShell } from "./LauncherShell";
import { queryKeys } from "../api/queryKeys";
const api = vi.hoisted(()=>({getLauncherBranchInstances:vi.fn(),getLauncherFreshness:vi.fn(),getLauncherStatus:vi.fn(),hasLauncherStateBridge:()=>false,onLauncherStateChanged:()=>()=>{},getLauncherState:vi.fn()}));
vi.mock("../api/launcher",()=>api);
vi.mock("../i18n/useLauncherLanguage",()=>({useLauncherLanguage:()=>"zh"}));
vi.mock("./LauncherTitlebar",()=>({LauncherTitlebar:()=>null}));
vi.mock("./LauncherNavigation",()=>({LauncherNavigation:({updateAvailable}:{updateAvailable:boolean})=><output data-update-badge>{String(updateAvailable)}</output>}));
vi.mock("./browserTelemetry",()=>({collectBrowserPageSnapshot:()=>({}),postBrowserTelemetry:vi.fn()}));
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
let root:Root, host:HTMLDivElement, client:QueryClient;
beforeEach(()=>{
  vi.clearAllMocks();api.getLauncherBranchInstances.mockResolvedValue({items:[]});api.getLauncherFreshness.mockResolvedValue({updateAvailable:true,current:false});
  host=document.createElement("div");document.body.appendChild(host);root=createRoot(host);client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:Infinity}}});
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();client.clear();delete window.vibelutionLauncherBrowser;});
async function settle(){await act(async()=>new Promise(resolve=>setTimeout(resolve,25)));}
describe("Launcher browser show navigation", () => {
  it("navigates only on explicit show and removes its subscription on unmount", async () => {
    let show: (() => void) | undefined;
    const unsubscribe = vi.fn();
    const invoke = vi.fn().mockResolvedValue({ pages: [{ id: "existing" }], activePageId: "existing", takeover: false });
    const onChanged = vi.fn(() => () => {});
    window.vibelutionLauncherBrowser = { invoke, onChanged, onShow: listener => { show = listener; return unsubscribe; } };
    const router = createMemoryRouter([{ path: "/launcher", element: <LauncherShell />, children: [
      { path: "assistant", element: <div>assistant</div> }, { path: "updates", element: <div>updates</div> },
    ] }], { initialEntries: ["/launcher/updates"] });
    await act(async () => root.render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>));
    expect(router.state.location.pathname).toBe("/launcher/updates");
    expect(invoke).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
    await act(async () => show?.());
    expect(router.state.location.pathname + router.state.location.search).toBe("/launcher/assistant?panel=browser");
    await act(async () => root.unmount());
    expect(unsubscribe).toHaveBeenCalledOnce();
    root = createRoot(host);
  });
});
describe("Launcher sidebar update watcher",()=>{
  it.each(["/launcher/updates","/launcher/updates/"])("keeps update reminders on ordinary pages and yields polling to %s",async updatePath=>{
    const router=createMemoryRouter([{path:"/launcher",element:<LauncherShell/>,children:[{path:"assistant",element:<div>chat</div>},{path:"updates",element:<div>updates</div>}]}],{initialEntries:["/launcher/assistant"]});
    await act(async()=>root.render(<QueryClientProvider client={client}><RouterProvider router={router}/></QueryClientProvider>));await settle();
    expect(api.getLauncherFreshness).toHaveBeenCalledTimes(1);expect(host.querySelector("[data-update-badge]")?.textContent).toBe("true");
    await act(async()=>router.navigate(updatePath));
    await act(async()=>client.invalidateQueries({queryKey:queryKeys.launcherFreshness()}));await settle();
    expect(api.getLauncherFreshness).toHaveBeenCalledTimes(1);
    api.getLauncherFreshness.mockResolvedValue({updateAvailable:false,current:true});
    await act(async()=>router.navigate("/launcher/assistant"));await settle();
    expect(api.getLauncherFreshness).toHaveBeenCalledTimes(2);expect(host.querySelector("[data-update-badge]")?.textContent).toBe("false");
  });
});
