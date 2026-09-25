// @vitest-environment happy-dom
import React, {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConfigSettingsIndex} from "./ConfigSettingsIndex";
import {ConfigDesktopPetSettings} from "./ConfigDesktopPetSettings";
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
function button(text:string){return [...host.querySelectorAll<HTMLButtonElement>("button")].find(b=>b.textContent?.includes(text) || b.getAttribute("aria-label") === text)!;}
it("renders one entry per existing feature and navigates without replacing its editor", async()=>{
  expect(host.querySelectorAll("button")).toHaveLength(3);
  await act(async()=>button("个人资料").click());
  expect(navigate).toHaveBeenCalledWith("avatar-pet","identity-profile","user-profile");
});
it("uses actual pet state and can reopen after a close", async()=>{
  expect(host.textContent).toContain("已关闭");
  control.mockResolvedValue({open:true,busyElsewhere:false});
  await act(async()=>button("桌面宠物").click());
  expect(control).toHaveBeenLastCalledWith(true);
  expect(host.textContent).toContain("已开启");
  control.mockResolvedValue({open:false,busyElsewhere:false});
  await act(async()=>button("桌面宠物").click());
  expect(control).toHaveBeenLastCalledWith(false);
  expect(host.textContent).toContain("已关闭");
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
it("uses the same working control when mounted directly in the category", async()=>{
  await act(async()=>root.render(<ConfigDesktopPetSettings language="zh"/>));
  expect(host.querySelector('[data-vui="settings-row"]')).not.toBeNull();
  expect(button("桌面宠物").textContent).toContain("启动桌宠");
  control.mockResolvedValue({open:true,busyElsewhere:false});
  await act(async()=>button("桌面宠物").click());
  expect(control).toHaveBeenLastCalledWith(true);
  expect(button("桌面宠物").textContent).toContain("关闭桌宠");
});
it("disables the control without a desktop bridge", async()=>{
  vi.stubGlobal("vibelutionLauncher", undefined);
  await act(async()=>root.render(<ConfigDesktopPetSettings language="zh"/>));
  expect(button("桌面宠物").disabled).toBe(true);
  expect(host.textContent).toContain("请在支持此功能的桌面版中打开设置");
});
it("prevents double toggles while waiting for the desktop shell", async()=>{
  let resolve!: (state: {open:boolean;busyElsewhere:boolean})=>void;
  control.mockReturnValue(new Promise(r=>{resolve=r;}));
  const before=control.mock.calls.length;
  await act(async()=>{button("桌面宠物").click();button("桌面宠物").click();});
  expect(control.mock.calls.length).toBe(before+1);
  expect(button("桌面宠物").disabled).toBe(true);
  await act(async()=>resolve({open:true,busyElsewhere:false}));
  expect(button("桌面宠物").getAttribute("aria-pressed")).toBe("true");
});
