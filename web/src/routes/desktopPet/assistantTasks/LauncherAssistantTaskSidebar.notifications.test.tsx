// @vitest-environment happy-dom
import React, {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {LauncherNotificationProvider,useLauncherNotices,type LauncherNotice} from "../../../app/LauncherNotifications";
import {LauncherAssistantTaskSidebar} from "./LauncherAssistantTaskSidebar";
import {LauncherTaskContext,usePublishLauncherTaskNotices,type LauncherTaskModel} from "./LauncherTaskContext";

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
let root:Root,host:HTMLDivElement,notices:LauncherNotice[];
function ReadNotices(){notices=useLauncherNotices();return null;}
function TaskOwner({value,children}:{value:LauncherTaskModel;children:React.ReactNode}){
 usePublishLauncherTaskNotices(value,"zh");
 return <LauncherTaskContext.Provider value={value}>{children}</LauncherTaskContext.Provider>;
}
function model(overrides:Partial<LauncherTaskModel>={}):LauncherTaskModel{return {
 identity:"assistant-1",tasks:[],loading:false,unavailable:false,refreshing:false,teamUnavailable:false,
 partial:false,invalid:0,enabled:true,shown:10,hasNextPage:false,loadingMore:false,selectedId:null,
 cleanableCount:0,cleanupBusy:false,canCleanCompleted:false,refresh:vi.fn(async()=>{}),more:vi.fn(async()=>{}),
 openTask:vi.fn(),remove:vi.fn(),cleanCompleted:vi.fn(),reviewRequest:null,...overrides,
};}
async function render(value:LauncherTaskModel){await act(async()=>{
 root.render(<LauncherNotificationProvider><TaskOwner value={value}>
  <LauncherAssistantTaskSidebar/><LauncherAssistantTaskSidebar/><ReadNotices/>
 </TaskOwner></LauncherNotificationProvider>);
});}
beforeEach(()=>{host=document.createElement("div");document.body.append(host);root=createRoot(host);notices=[];});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});

describe("task sidebar notifications",()=>{
 it("keeps task controls without permanent history caveats or a false error",async()=>{
  await render(model({historyIncomplete:true,legacyUnrecoverable:2}));
  expect(host.textContent).not.toMatch(/可显示的历史有限|旧关联无法恢复|仅显示已登记/);
  expect(host.textContent).toContain("待处理 0");
  expect(host.querySelector('[data-assistant-task-refresh]')).not.toBeNull();
  expect(notices).toEqual([]);
 });
 it("publishes partial and failed reads to the titlebar and withdraws after recovery",async()=>{
  const refresh=vi.fn(async()=>{});
  await render(model({partial:true,historyIncomplete:true,legacyUnrecoverable:2,refresh}));
  expect(host.textContent).not.toMatch(/部分团队关联|可显示的历史有限|旧关联无法恢复/);
  expect(notices).toHaveLength(1);
  expect(notices[0].title).toBe("任务状态未更新");
  await notices[0].actions![0].run();
  expect(refresh).toHaveBeenCalledOnce();
  await render(model({teamUnavailable:true,refreshing:true,refresh}));
  expect(notices).toHaveLength(1);
  expect(notices[0].actions![0].pending).toBe(true);
  await render(model());
  expect(notices).toEqual([]);
 });
});
