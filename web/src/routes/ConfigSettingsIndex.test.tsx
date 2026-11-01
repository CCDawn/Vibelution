// @vitest-environment happy-dom
import React, {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConfigSettingsIndex} from "./ConfigSettingsIndex";
import type {ConfigSettingsGroup} from "./ConfigSettingsNavigation";
const groups: ConfigSettingsGroup[] = [{id:"avatar-pet",title:"个人资料与陪伴体",summary:"",pages:[{id:"identity-profile",title:"个人资料",summary:"",memberSectionIds:["user-profile","pet"]}]}];
const sections = [{id:"user-profile",title:"个人资料",summary:"头像与名称"},{id:"pet",title:"陪伴体设置",summary:"陪伴偏好"}];
let root: Root; let host: HTMLDivElement;
const navigate = vi.fn();
beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);
  navigate.mockReset();
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
  await act(async()=>root.render(<MemoryRouter><ConfigSettingsIndex groups={groups} sections={sections} language="zh" onNavigate={navigate}/></MemoryRouter>));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
function button(text:string){return [...host.querySelectorAll<HTMLButtonElement>("button")].find(b=>b.textContent?.includes(text) || b.getAttribute("aria-label") === text)!;}
it("does not duplicate usage inside unrelated settings categories", async()=>{
  await act(async()=>root.render(<MemoryRouter><ConfigSettingsIndex groups={groups} sections={sections} language="zh" onNavigate={navigate} showUsage={false}/></MemoryRouter>));
  expect(host.querySelector('a[href="/usage"]')).toBeNull();
});
it("renders one entry per existing feature and navigates without replacing its editor", async()=>{
  expect(host.querySelectorAll("button")).toHaveLength(2);
  await act(async()=>button("个人资料").click());
  expect(navigate).toHaveBeenCalledWith("avatar-pet","identity-profile","user-profile");
});
it("keeps usage statistics as its own settings row linking to the existing usage page",()=>{
  const link=host.querySelector<HTMLAnchorElement>('a[href="/usage"]');
  expect(host.textContent).toContain("使用与诊断");
  expect(link?.textContent).toContain("用量统计");
  expect(link?.textContent).toContain("查看 Token 用量与请求统计");
});
it("no longer mounts the retired desktop assistant toggle in the category",()=>{
  // The floating-window toggle died with the /desktop-assistant surface; the
  // category now lists only its modeled feature sections.
  expect(host.querySelector('input[role="switch"]')).toBeNull();
  expect(host.textContent).not.toContain("已关闭");
  expect(host.textContent).not.toContain("打开个人助理");
  expect(button("陪伴体设置")).toBeTruthy();
});
