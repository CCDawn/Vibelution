/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LauncherNotificationTopbar } from "./LauncherNotificationTopbar";
import { LauncherNotificationProvider, usePublishLauncherNotices, type LauncherNotice } from "./LauncherNotifications";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;

function Source({ notices }: { notices: LauncherNotice[] }) { usePublishLauncherNotices(notices); return null; }
async function render(notices: LauncherNotice[] = [], lang: "zh" | "en" = "zh") {
  await act(async () => {
    root.render(<LauncherNotificationProvider><Source notices={notices} /><LauncherNotificationTopbar lang={lang} /></LauncherNotificationProvider>);
  });
}
async function click(button: HTMLButtonElement) {
  await act(async () => { button.click(); await new Promise(resolve => setTimeout(resolve, 10)); });
}
function trigger() { return host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!; }
function panel() { return document.querySelector<HTMLDivElement>('[role="dialog"][aria-label]'); }
function button(label: string) {
  const found = [...document.querySelectorAll<HTMLButtonElement>("button")]
    .find(item => item.getAttribute("aria-label") === label || item.textContent?.trim() === label);
  expect(found, `button: ${label}`).toBeTruthy();
  return found!;
}

const connection: LauncherNotice = {
  id: "connection", kind: "connection", tone: "warning", title: "聊天没能刷新", features: ["conversation", "tasks"],
  description: "已有内容仍可查看。", details: "ASSISTANT_REQUEST_TIMEOUT",
};
const appearance: LauncherNotice = {
  id: "appearance", kind: "appearance", tone: "info", title: "外观图片未加载", description: "暂时使用默认外观，不影响聊天。",
};
const retryAction = (run: () => unknown | Promise<unknown>) => ({ id: "retry", label: "再试一次", run });

beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });

describe("Launcher notification topbar", () => {
  it("opens compact rows with warnings first and reveals affected features and diagnostics only on demand", async () => {
    await render([appearance, connection]);
    expect(trigger().getAttribute("aria-label")).toContain("刷新没成功, 2 项提醒");
    expect(panel()).toBeNull();
    await click(trigger());
    const items = [...panel()!.querySelectorAll("li")];
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("聊天和任务进度没刷新");
    expect(items[0].getAttribute("data-tone")).toBe("warning");
    expect(items[1].getAttribute("data-tone")).toBe("info");
    expect(panel()?.textContent).not.toContain("恢复后自动移除提醒");
    expect(panel()?.textContent).not.toContain(connection.description);
    expect(panel()?.textContent).not.toContain(connection.details);
    expect(panel()?.textContent).not.toContain(appearance.description);
    await click(button("聊天和任务进度没刷新"));
    expect(button("聊天和任务进度没刷新").getAttribute("aria-expanded")).toBe("true");
    expect(panel()?.textContent).toContain("聊天记录");
    expect(panel()?.textContent).toContain("任务进度");
    const details = panel()!.querySelector("details")!;
    expect(details.open).toBe(false);
    await act(async () => details.querySelector("summary")!.click());
    expect(details.open).toBe(true);
    expect(details.textContent).toContain("ASSISTANT_REQUEST_TIMEOUT");
    await click(button("外观图片未加载"));
    expect(panel()?.textContent).toContain(appearance.description);
  });

  it("closes with Escape and the explicit close button", async () => {
    await render([connection]); await click(trigger());
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    expect(panel()).toBeNull();
    expect(trigger().getAttribute("aria-expanded")).toBe("false");
    await click(trigger()); await click(button("关闭运行提醒"));
    expect(panel()).toBeNull();
  });

  it("locks retries across closing and reopening and keeps the warning after a failed read", async () => {
    let reject!: (reason: Error) => void;
    const retry = vi.fn(() => new Promise<void>((_, fail) => { reject = fail; }));
    await render([{ ...connection, actions: [retryAction(retry)] }]); await click(trigger());
    const retryButton = button("再试一次");
    await act(async () => { retryButton.click(); retryButton.click(); });
    expect(retry).toHaveBeenCalledOnce();
    expect(button("请稍等").disabled).toBe(true);
    await click(button("关闭运行提醒")); await click(trigger());
    expect(button("请稍等").disabled).toBe(true);
    await act(async () => reject(new Error("read failed")));
    expect(button("再试一次").disabled).toBe(false);
    expect(panel()?.textContent).toContain("聊天和任务进度没刷新");
  });

  it("honors source pending or disabled state and only clears recovered sources", async () => {
    const retry = vi.fn();
    await render([{ ...connection, actions: [{ ...retryAction(retry), pending: true }] }, appearance]);
    await click(trigger());
    expect(button("请稍等").disabled).toBe(true);
    await click(button("请稍等")); expect(retry).not.toHaveBeenCalled();
    await render([{ ...connection, actions: [{ ...retryAction(retry), disabled: true }] }]);
    expect(button("再试一次").disabled).toBe(true);
    await click(button("再试一次")); expect(retry).not.toHaveBeenCalled();
    await render([appearance]);
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    expect(panel()?.textContent).not.toContain("聊天和任务进度没刷新");
    await render([]);
    expect(trigger().textContent).toContain("暂无异常");
    expect(panel()?.textContent).toContain("当前没有异常");
  });

  it("groups independent read owners, waits for every retry to settle, and retains a partially recovered task warning", async () => {
    let rejectChat!: (reason: Error) => void;
    let resolveTasks!: () => void;
    const chatRetry = vi.fn(() => new Promise<void>((_, reject) => { rejectChat = reject; }));
    const taskRetry = vi.fn(() => new Promise<void>(resolve => { resolveTasks = resolve; }));
    const chat: LauncherNotice = { ...connection, id: "chat", features: ["conversation", "approvals"], actions: [retryAction(chatRetry)] };
    const tasks: LauncherNotice = { ...connection, id: "tasks", features: ["tasks"], actions: [retryAction(taskRetry)] };
    await render([chat, tasks]); await click(trigger());
    expect(panel()?.querySelectorAll("li")).toHaveLength(1);
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    await click(button("再试一次"));
    expect(chatRetry).toHaveBeenCalledOnce(); expect(taskRetry).toHaveBeenCalledOnce();
    await act(async () => rejectChat(new Error("chat still unavailable")));
    expect(button("请稍等").disabled).toBe(true);
    await click(button("请稍等")); expect(taskRetry).toHaveBeenCalledOnce();
    await render([tasks]);
    expect(button("请稍等").disabled).toBe(true);
    await act(async () => resolveTasks());
    expect(panel()?.textContent).toContain("暂时查不到任务进度");
    expect(panel()?.textContent).not.toContain("聊天和任务进度没刷新");
    await click(button("暂时查不到任务进度"));
    expect(panel()?.querySelectorAll("dt")).toHaveLength(1);
    expect(panel()?.querySelector("dt")?.textContent).toBe("任务进度");
    await render([]);
    expect(panel()?.textContent).toContain("当前没有异常");
  });

  it("provides English copy without turning an empty warning list into a verified connection", async () => {
    await render([], "en");
    expect(trigger().getAttribute("aria-label")).toContain("No issues reported, 0 notices, View details");
    await click(trigger());
    expect(panel()?.getAttribute("aria-label")).toBe("Runtime notices");
    expect(panel()?.textContent).toContain("No current issues");
    expect(button("Close runtime notices")).toBeTruthy();
    await render([{ ...connection, actions: [retryAction(vi.fn())] }], "en");
    expect(panel()?.textContent).toContain("Chat and task progress could not refresh");
    expect(button("Try again")).toBeTruthy();
  });

  it("keeps keyboard focus on a live control when a retry becomes pending or disappears", async () => {
    let resolve!: () => void;
    await render([{ ...connection, actions: [retryAction(() => new Promise<void>(done => { resolve = done; }))] }]);
    await click(trigger());
    const retry = button("再试一次"); retry.focus(); await click(retry);
    expect(document.activeElement).toBe(trigger());
    await render([]); await act(async () => resolve());
    expect(document.activeElement).toBe(trigger());
    expect(panel()?.textContent).toContain("当前没有异常");
  });
});
