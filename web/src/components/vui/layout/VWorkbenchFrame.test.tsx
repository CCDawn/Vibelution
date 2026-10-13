/** @vitest-environment happy-dom */
import React, { act, useMemo, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Link, MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { VWorkbenchFrame } from "./VWorkbenchFrame";
import { VWorkbenchPage } from "./VWorkbenchPage";
import { VSplitWorkspace } from "./VSplitWorkspace";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root | undefined;
let renders = 0;
function Page() {
  renders += 1;
  const [count, setCount] = useState(0);
  return <VWorkbenchPage fill><button onClick={() => setCount(count + 1)}>Content {count}</button></VWorkbenchPage>;
}
function Layout() {
  const [poll, setPoll] = useState(0);
  const content = useMemo(() => <Outlet />, []);
  return <><button onClick={() => setPoll(poll + 1)}>Poll {poll}</button><Link to="/other">Other</Link><VWorkbenchFrame>{content}</VWorkbenchFrame></>;
}
afterEach(() => { if (root) act(() => root?.unmount()); root = undefined; host?.remove(); });
function mount(element: React.ReactNode) {
  host = document.createElement("div"); document.body.append(host);
  root = createRoot(host); act(() => root?.render(element));
}
function click(selector: string) { act(() => (host.querySelector(selector) as HTMLElement).click()); }

describe("persistent workbench chrome", () => {
  it("isolates parent polling while preserving navigation and local content updates", () => {
    renders = 0;
    mount(<MemoryRouter initialEntries={["/"]}><Routes><Route element={<Layout />}><Route index element={<Page />} /><Route path="other" element={<VWorkbenchPage>Other page</VWorkbenchPage>} /></Route></Routes></MemoryRouter>);
    const frame = host.querySelector('[data-vui="workbench-frame"]');
    const initialRenders = renders;
    for (let index = 0; index < 3; index += 1) click("button");
    expect(host.textContent).toContain("Poll 3");
    expect(renders).toBe(initialRenders);
    click('[data-vui="workbench-page"] button');
    expect(host.textContent).toContain("Content 1");
    expect(renders).toBe(initialRenders + 1);
    click("a");
    expect(host.textContent).toContain("Other page");
    expect(host.textContent).not.toContain("Content 1");
    expect(host.querySelector('[data-vui="workbench-frame"]')).toBe(frame);
  });
  it("keeps explicit page/pane roles without styling nested editor splits", () => {
    mount(<VWorkbenchFrame><VWorkbenchPage chrome="workspace" fill><VSplitWorkspace chrome="workbench" sidebar="Index" main={<VSplitWorkspace chrome="workbench" main="Nested editor" />} /></VWorkbenchPage></VWorkbenchFrame>);
    expect(host.querySelector('[data-vui="workbench-page"]')?.getAttribute("data-vui-page")).toBe("workspace");
    const splits = host.querySelectorAll('[data-vui="split-workspace"]');
    expect(splits[0].getAttribute("data-vui-split-chrome")).toBe("workbench");
    expect(splits[1].getAttribute("data-vui-split-chrome")).toBe("embedded");
  });
});
