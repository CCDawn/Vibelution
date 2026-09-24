// @vitest-environment happy-dom
import React, {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConfigSettingsIndex} from "./ConfigSettingsIndex";
import type {ConfigSettingsGroup} from "./ConfigSettingsNavigation";
const control = vi.fn();
const groups: ConfigSettingsGroup[] = [{id:"avatar-pet",title:"个人资料与陪伴体",summary:"",pages:[{id:"identity-profile",title:"个人资料",summary:"",memberSectionIds:["user-profile","pet"]}]}];
const sections = [{id:"user-profile",title:"个人资料",summary:"头像与名称"},{id:"pet",title:"陪伴体设置",summary:"陪伴偏好"}];
let root: Root; let host: HTMLDivElement;
const navigate = vi.fn();
beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);
  vi.stubGlobal("vibelutionLauncher",{controlDesktopPet:control});
  control.mockReset().mockResolvedValue({open:false,busyElsewhere:false}); navigate.mockReset();
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
  await act(async()=>root.render(<ConfigSettingsIndex groups={groups} sections={sections} language="zh" onNavigate={navigate}/>));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
function button(text:string){return [...host.querySelectorAll<HTMLButtonElement>("button")].find(b=>b.textContent?.includes(text))!;}
it("renders one entry per existing feature and navigates without replacing its editor", async()=>{
  expect(host.querySelectorAll("button")).toHaveLength(3);
  await act(async()=>button("个人资料").click());
  expect(navigate).toHaveBeenCalledWith("avatar-pet","identity-profile","user-profile");
});
it("uses actual pet state and can reopen after a close", async()=>{
  expect(button("桌面宠物").textContent).toContain("已关闭");
  control.mockResolvedValue({open:true,busyElsewhere:false});
  await act(async()=>button("桌面宠物").click());
  expect(control).toHaveBeenLastCalledWith(true);
  expect(button("桌面宠物").textContent).toContain("已开启");
  control.mockResolvedValue({open:false,busyElsewhere:false});
  await act(async()=>button("桌面宠物").click());
  expect(control).toHaveBeenLastCalledWith(false);
  expect(button("桌面宠物").textContent).toContain("已关闭");
});
it("reports failure without falsely changing the toggle", async()=>{
  control.mockRejectedValue(new Error("unavailable"));
  await act(async()=>button("桌面宠物").click());
  expect(host.textContent).toContain("操作失败");
  expect(button("桌面宠物").getAttribute("aria-pressed")).toBe("false");
});
it("does not close another workspace's pet", async()=>{
  control.mockResolvedValue({open:false,busyElsewhere:true});
  await act(async()=>window.dispatchEvent(new Event("focus")));
  expect(button("桌面宠物").disabled).toBe(true);
  expect(host.textContent).toContain("其他工作区使用中");
});
