/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LauncherNotificationTopbar } from "./LauncherNotificationTopbar";
import { LauncherNotificationProvider, usePublishLauncherNotices, type LauncherNotice } from "./LauncherNotifications";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

function Source({ notices }: { notices: LauncherNotice[] }) {
  usePublishLauncherNotices(notices);
  return null;
}

async function render(notices: LauncherNotice[] = [], lang: "zh" | "en" = "zh") {
  await act(async () => {
    root.render(<LauncherNotificationProvider><Source notices={notices} /><LauncherNotificationTopbar lang={lang} /></LauncherNotificationProvider>);
  });
}

async function click(button: HTMLButtonElement) {
  await act(async () => { button.click(); await new Promise(resolve => setTimeout(resolve, 10)); });
}

function trigger() {
  return host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!;
}

function panel() {
  return document.querySelector<HTMLDivElement>('[role="dialog"][aria-label]');
}

function button(label: string) {
  const found = [...document.querySelectorAll<HTMLButtonElement>("button")]
    .find(item => item.getAttribute("aria-label") === label || item.textContent?.trim() === label);
  expect(found, `button: ${label}`).toBeTruthy();
  return found!;
}

const connection: LauncherNotice = {
  id: "connection", kind: "connection", tone: "warning", title: "部分状态未更新",
  description: "连接响应超时，当前保留上次内容。", labels: ["会话刷新", "任务状态"], details: "ASSISTANT_REQUEST_TIMEOUT",
};
const appearance: LauncherNotice = {
  id: "appearance", kind: "appearance", tone: "info", title: "外观图片未加载", description: "暂时使用默认外观，不影响聊天。",
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

describe("Launcher notification topbar", () => {
  it("counts warning and info together and opens the real popover with warnings first", async () => {
    await render([appearance, connection]);
    expect(trigger().getAttribute("aria-label")).toContain("连接异常, 2 项提醒");
    expect(panel()).toBeNull();
    await click(trigger());
    expect(panel()?.textContent).toContain("运行提醒");
    const items = [...panel()!.querySelectorAll("li")];
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain(connection.title);
    expect(items[1].textContent).toContain(appearance.title);
    expect(items[1].querySelector('[data-tone="info"]')).toBeTruthy();
    expect(panel()?.textContent).toContain("会话刷新");
    const details = panel()!.querySelector("details")!;
    expect(details.open).toBe(false);
    await act(async () => { details.querySelector("summary")!.click(); });
    expect(details.open).toBe(true);
    expect(details.textContent).toContain("ASSISTANT_REQUEST_TIMEOUT");
  });

  it("closes with Escape and with the explicit close button", async () => {
    await render([connection]);
    await click(trigger());
    expect(panel()).toBeTruthy();
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    expect(panel()).toBeNull();
    expect(trigger().getAttribute("aria-expanded")).toBe("false");
    await click(trigger());
    await click(button("关闭运行提醒"));
    expect(panel()).toBeNull();
  });

  it("locks pending recovery across closing and reopening, and retains the notice after failure", async () => {
    let reject!: (reason: Error) => void;
    const retry = vi.fn(() => new Promise<void>((_, fail) => { reject = fail; }));
    await render([{ ...connection, actions: [{ id: "retry", label: "重新连接", run: retry }] }]);
    await click(trigger());
    await act(async () => { button("重新连接").click(); button("重新连接").click(); });
    expect(retry).toHaveBeenCalledOnce();
    expect(button("重新连接").disabled).toBe(true);
    await click(button("关闭运行提醒"));
    await click(trigger());
    expect(button("重新连接").disabled).toBe(true);
    await act(async () => { reject(new Error("still offline")); });
    expect(button("重新连接").disabled).toBe(false);
    expect(panel()?.textContent).toContain(connection.title);
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
  });

  it("honors a producer's pending action and clears counts only when the source recovers", async () => {
    const retry = vi.fn();
    await render([{ ...connection, actions: [{ id: "retry", label: "检查连接", run: retry, pending: true }] }, appearance]);
    await click(trigger());
    expect(button("检查连接").disabled).toBe(true);
    await click(button("检查连接"));
    expect(retry).not.toHaveBeenCalled();
    await render([appearance]);
    expect(trigger().getAttribute("aria-label")).toContain("1 项提醒");
    expect(panel()?.textContent).not.toContain(connection.title);
    await render([]);
    expect(trigger().textContent).toContain("暂无异常");
    expect(panel()?.textContent).toContain("当前没有异常");
  });

  it("provides English labels without claiming a verified connection in the empty state", async () => {
    await render([], "en");
    expect(trigger().getAttribute("aria-label")).toContain("No issues reported, 0 notices, View details");
    await click(trigger());
    expect(panel()?.getAttribute("aria-label")).toBe("Runtime notices");
    expect(panel()?.textContent).toContain("No current issues");
    expect(button("Close runtime notices")).toBeTruthy();
  });

  it("keeps keyboard focus on a live control when a focused retry becomes pending or disappears", async () => {
    let resolve!: () => void;
    await render([{ ...connection, actions: [{ id: "retry", label: "重新连接", run: () => new Promise<void>(done => { resolve = done; }) }] }]);
    await click(trigger());
    const retry = button("重新连接");
    retry.focus();
    await click(retry);
    expect(document.activeElement).toBe(trigger());
    await render([]);
    await act(async () => resolve());
    expect(document.activeElement).toBe(trigger());
    expect(panel()?.textContent).toContain("当前没有异常");
  });
});
