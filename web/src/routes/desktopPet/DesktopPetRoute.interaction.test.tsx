// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DesktopPetRoute } from "./DesktopPetRoute";

const mocks = vi.hoisted(() => ({ open: vi.fn(), query: {
  data: { aggregateTone: "running", animationState: "thinking", activeCount: 1, attentionCount: 0,
    sessions: [{ sessionId: "s1", title: "Private task", agentDisplayName: "Private agent", tone: "running", phase: "thinking" }] },
  isError: false,
} }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => mocks.query }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: ({ name }: { name: string }) => <span>{name}</span> }));
vi.mock("./desktopPetModel", async (original) => ({ ...await original<object>(), openSessionFromDesktopPet: mocks.open }));

let host: HTMLDivElement;
let root: Root;
beforeEach(async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear(); mocks.open.mockReset(); mocks.query.isError = false;
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<DesktopPetRoute />));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function click(label: string) {
  const button = host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
  expect(button).not.toBeNull();
  await act(async () => button!.click());
}

it("keeps the HUD open with feedback on failure, closes only on successful navigation", async () => {
  await click("展开实时对话");
  mocks.open.mockResolvedValue(false);
  await act(async () => host.querySelector<HTMLButtonElement>("button[data-tone='running']")!.click());
  expect(host.textContent).toContain("未能打开对话");
  expect(host.querySelector("section[aria-label='实时对话']")).not.toBeNull();
  mocks.open.mockResolvedValue(true);
  await act(async () => host.querySelector<HTMLButtonElement>("button[data-tone='running']")!.click());
  expect(host.querySelector("section[aria-label='实时对话']")).toBeNull();
});

it("restores the selected character and hidden titles after reopening", async () => {
  await click("切换到大肥鲸");
  await click("桌宠设置");
  const checkbox = [...host.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')]
    .find((input) => input.closest("label")?.textContent?.includes("显示会话标题"));
  expect(checkbox).toBeDefined();
  await act(async () => checkbox!.click());
  await act(async () => { root.unmount(); root = createRoot(host); root.render(<DesktopPetRoute />); });
  expect(host.querySelector("main")?.getAttribute("aria-label")).toBe("DeepSeek 大肥鲸");
  await click("展开实时对话");
  expect(host.textContent).not.toContain("Private");
  expect(host.textContent).toContain("会话 1");
});
