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
afterEach(async()=>{await act(async()=>root.unmount());host.remove();client.clear();});
async function settle(){await act(async()=>new Promise(resolve=>setTimeout(resolve,25)));}
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
