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
function TaskOwner({value,children,lang}:{value:LauncherTaskModel;children:React.ReactNode;lang:"zh"|"en"}){
 usePublishLauncherTaskNotices(value,lang);
 return <LauncherTaskContext.Provider value={value}>{children}</LauncherTaskContext.Provider>;
}
function model(overrides:Partial<LauncherTaskModel>={}):LauncherTaskModel{return {
 identity:"assistant-1",tasks:[],loading:false,unavailable:false,refreshing:false,teamUnavailable:false,
 partial:false,invalid:0,enabled:true,shown:10,hasNextPage:false,loadingMore:false,selectedId:null,
 cleanableCount:0,cleanupBusy:false,canCleanCompleted:false,refresh:vi.fn(async()=>{}),more:vi.fn(async()=>{}),
 openTask:vi.fn(),remove:vi.fn(),cleanCompleted:vi.fn(),reviewRequest:null,...overrides,
};}
async function render(value:LauncherTaskModel,lang:"zh"|"en"="zh"){await act(async()=>{
 root.render(<LauncherNotificationProvider><TaskOwner value={value} lang={lang}>
  <LauncherAssistantTaskSidebar lang={lang}/><LauncherAssistantTaskSidebar lang={lang}/><ReadNotices/>
 </TaskOwner></LauncherNotificationProvider>);
});}
beforeEach(()=>{host=document.createElement("div");document.body.append(host);root=createRoot(host);notices=[];});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});

describe("task sidebar notifications",()=>{
 it("keeps categories without a permanent task toolbar, history caveats or a false error",async()=>{
  await render(model({historyIncomplete:true,legacyUnrecoverable:2,canCleanCompleted:true,cleanableCount:2}));
  expect(host.textContent).not.toMatch(/可显示的历史有限|旧关联无法恢复|仅显示已登记/);
  expect(host.textContent).toContain("待处理 0");
  const sidebars=host.querySelectorAll('[data-assistant-task-cards]');
  expect(sidebars).toHaveLength(2);
  for(const sidebar of sidebars){
   expect(sidebar.querySelectorAll('[role="tab"]')).toHaveLength(3);
   expect(sidebar.querySelector('header,h1,h2,h3,[data-assistant-task-refresh],[data-assistant-task-bulk-cleanup]')).toBeNull();
   expect([...sidebar.querySelectorAll('button')].some(button=>['任务','刷新','清理已结束'].includes(button.textContent?.trim()??'')||button.getAttribute('aria-label')==='刷新')).toBe(false);
  }
  expect(notices).toEqual([]);
 });
 it("publishes partial and failed reads to the titlebar and withdraws after recovery",async()=>{
  const refresh=vi.fn(async()=>{});
  await render(model({partial:true,historyIncomplete:true,legacyUnrecoverable:2,refresh}));
  expect(host.textContent).not.toMatch(/部分团队关联|可显示的历史有限|旧关联无法恢复/);
  expect(notices).toHaveLength(1);
  expect(notices[0]).toMatchObject({title:"暂时查不到任务进度",description:"稍后再试一次。",features:["tasks"]});
  expect(notices[0].actions![0].label).toBe("再试一次");
  await notices[0].actions![0].run();
  expect(refresh).toHaveBeenCalledOnce();
  await render(model({teamUnavailable:true,refreshing:true,refresh}));
  expect(notices).toHaveLength(1);
  expect(notices[0].actions![0].pending).toBe(true);
  await render(model());
  expect(notices).toEqual([]);
 });
 it.each([{partial:true},{invalid:1}])("describes incomplete task reads without claiming a network outage: %o",async warning=>{
  await render(model(warning));
  expect(notices).toHaveLength(1);
  expect(notices[0]).toMatchObject({title:"暂时查不到任务进度",features:["tasks"]});
  expect(`${notices[0].title} ${notices[0].description} ${notices[0].actions![0].label}`).not.toMatch(/网络|断开|连接/);
 });
 it("keeps a failed task read visible during retry and uses plain English copy",async()=>{
  await render(model({unavailable:true}),"en");
  expect(notices[0]).toMatchObject({title:"Task progress is unavailable",description:"Try again in a moment.",features:["tasks"]});
  await render(model({unavailable:true,refreshing:true}),"en");
  expect(notices).toHaveLength(1);
  expect(notices[0].actions![0]).toMatchObject({label:"Try again",pending:true});
  await render(model(),"en");
  expect(notices).toEqual([]);
 });
});
