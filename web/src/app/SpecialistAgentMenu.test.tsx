// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SpecialistAgentMenu, specialistAgentSection } from "./SpecialistAgentMenu";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
let navigate: NavigateFunction;
const selected = vi.fn();
const openFinance = vi.fn();
function Harness({ enabled = true }: { enabled?: boolean }) {
  navigate = useNavigate();
  const location = useLocation();
  return <><SpecialistAgentMenu lang="zh" enabled={enabled} className="normal" activeClassName="active"
    onNavigate={(to) => { selected(to); if (location.pathname !== to) navigate(to); }}
    onOpenFinance={openFinance} />
    <output>{location.pathname}{location.search}</output></>;
}
beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); selected.mockClear(); openFinance.mockClear(); });
async function render(path = "/chat", enabled = true) {
  await act(async () => root.render(<MemoryRouter initialEntries={[path]}><Harness enabled={enabled} /></MemoryRouter>));
}
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 15))); }
function trigger() { return container.querySelector("button")!; }
async function pointer(target: Element) {
  await act(async () => { target.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerType: "mouse" })); });
  await settle();
}
async function key(target: Element, value: string) {
  await act(async () => target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: value })));
  await settle();
}

describe("specialist agent menu", () => {
  it("opens downward with two choices and closes on Escape without changing route", async () => {
    await render(); await pointer(trigger());
    const menu = document.querySelector('[role="menu"]');
    expect(menu?.getAttribute("data-side")).toBe("bottom");
    expect([...document.querySelectorAll('[role="menuitem"]')].map((e) => e.textContent)).toEqual(["炒股智能体", "虚拟人智能体"]);
    await key(menu!, "Escape");
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(container.querySelector("output")?.textContent).toBe("/chat");
  });
  it("closes on outside pointer and repeated trigger click", async () => {
    await render(); await pointer(trigger());
    await pointer(document.body);
    expect(document.querySelector('[role="menu"]')).toBeNull();
    await pointer(trigger()); await pointer(trigger());
    expect(document.querySelector('[role="menu"]')).toBeNull();
  });
  it("supports keyboard selection and browser back with route-driven highlight", async () => {
    await render(); trigger().focus(); await key(trigger(), "ArrowDown");
    const items = [...document.querySelectorAll('[role="menuitem"]')];
    expect(items.length).toBe(2);
    items[0].dispatchEvent(new FocusEvent("focus"));
    (items[0] as HTMLElement).focus();
    await key(items[0], "ArrowDown");
    expect(document.activeElement?.textContent).toContain("虚拟人智能体");
    await key(document.activeElement!, "Enter");
    expect(container.querySelector("output")?.textContent).toBe("/companions");
    expect(trigger().getAttribute("data-agent-section")).toBe("companions");
    expect(document.querySelector('[role="menu"]')).toBeNull();
    await act(async () => navigate(-1));
    expect(container.querySelector("output")?.textContent).toBe("/chat");
    expect(trigger().getAttribute("aria-current")).toBeNull();
  });
  it("selects finance, preserves active state on refresh, and closes on external navigation", async () => {
    await render("/finance");
    expect(trigger().className).toContain("active");
    await pointer(trigger());
    await act(async () => (document.querySelector('[role="menuitem"]') as HTMLElement).click());
    await settle();
    expect(openFinance).toHaveBeenCalledTimes(1);
    expect(selected).not.toHaveBeenCalled();
    expect(container.querySelector("output")?.textContent).toBe("/finance");
    await pointer(trigger()); await act(async () => navigate("/companions"));
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(trigger().getAttribute("data-agent-section")).toBe("companions");
  });
  it("leaves old companion deep links untouched and honors disabled chat", async () => {
    await render("/chat?session=existing&companion=person", false);
    expect(trigger().disabled).toBe(true);
    expect(container.querySelector("output")?.textContent).toBe("/chat?session=existing&companion=person");
    expect(specialistAgentSection("/finance-malicious")).toBe("");
    expect(specialistAgentSection("/companions/profile")).toBe("companions");
  });
});
