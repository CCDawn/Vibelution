/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LauncherNotificationProvider, useLauncherNotices, usePublishLauncherNotices } from "./LauncherNotifications";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const container = document.createElement("div");
let root = createRoot(container);
afterEach(async () => { await act(async () => root.unmount()); root = createRoot(container); });

function Producer({ value, failed = true, onRetry }: { value: string; failed?: boolean; onRetry: (value: string) => void }) {
  usePublishLauncherNotices(failed ? [{ id: "same-id", kind: "connection", tone: "warning", title: "Read failed", description: "Last known content retained",
    actions: [{ id: "retry", label: "Retry", run: () => onRetry(value) }] }] : []);
  return null;
}
function Consumer() {
  const notices = useLauncherNotices();
  return <><output>{notices.length}</output>{notices.map(notice => <button key={notice.id} onClick={() => notice.actions?.[0].run()}>{notice.id}</button>)}</>;
}

describe("Launcher notice source ownership", () => {
  it("retry uses the latest source callback even when display fields are unchanged", async () => {
    const retry = vi.fn();
    const render = (value: string, failed = true) => <LauncherNotificationProvider><Producer value={value} failed={failed} onRetry={retry}/><Consumer/></LauncherNotificationProvider>;
    await act(async () => root.render(render("old-session")));
    await act(async () => root.render(render("new-session")));
    await act(async () => container.querySelector("button")!.click());
    expect(retry).toHaveBeenCalledExactlyOnceWith("new-session");
    await act(async () => root.render(render("new-session", false)));
    expect(container.querySelector("output")?.textContent).toBe("0");
  });

  it("keeps identical notice IDs from separate owners distinct and removes an unmounted owner", async () => {
    const retry = vi.fn();
    const render = (second: boolean) => <LauncherNotificationProvider><Producer key="first" value="first" onRetry={retry}/>{second ? <Producer key="second" value="second" onRetry={retry}/> : null}<Consumer/></LauncherNotificationProvider>;
    await act(async () => root.render(render(true)));
    const ids = [...container.querySelectorAll("button")].map(button => button.textContent);
    expect(new Set(ids).size).toBe(2);
    await act(async () => root.render(render(false)));
    expect(container.querySelector("output")?.textContent).toBe("1");
  });
});
