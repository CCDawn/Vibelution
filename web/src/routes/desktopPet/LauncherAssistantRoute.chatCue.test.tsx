// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => createElement("div", { "data-testid": "pet-character" }) }));
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: () => createElement("div", { "data-testid": "native-conversation" }),
}));

const launcherCss = readFileSync(resolve(import.meta.dirname, "../../design/route-css/desktop-pet.tailwind.css"), "utf8");

let root: Root | undefined;
let container: HTMLDivElement;
let presentation: HTMLStyleElement | undefined;
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  container?.remove(); presentation?.remove(); presentation = undefined;
  vi.unstubAllGlobals(); vi.clearAllMocks();
});
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); }); }

async function renderCollapsedFloat() {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  const invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" } };
      case "config": return { language: "zh" };
      case "detail": return { id: "s", agentId: "a", status: "ready", messages: [] };
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  // No `embedded`: the floating window boots collapsed into the pet stage.
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute))));
  await settle(); await settle();
  return invoke;
}

it("keeps the collapsed chat cue reachable only through stage hover or keyboard focus", async () => {
  const invoke = await renderCollapsedFloat();
  const stage = container.querySelector<HTMLElement>(".desktop-pet-stage");
  const cue = container.querySelector<HTMLButtonElement>(".desktop-assistant-chat-cue");
  // The DOM contract the stylesheet gates on: collapsed float, cue inside the
  // stage, and no JS-level lock on the button itself.
  expect(container.querySelector('[data-vui-domain-recipe="launcher-assistant"][data-expanded="false"]')).toBeTruthy();
  expect(stage).toBeTruthy();
  expect(cue?.textContent).toContain("聊一聊");
  expect(cue?.disabled).toBe(false);
  expect(stage?.contains(cue ?? null)).toBe(true);

  // Restored-window non-hover state, evaluated against the real stylesheet
  // (happy-dom can never match :hover/:focus-within, which is exactly the
  // "mouse has not entered the stage yet" case): the cue is designedly
  // invisible and click-transparent.
  presentation = document.createElement("style");
  presentation.textContent = launcherCss.replace(/^@(import|source)\s[^\n]+/gm, "");
  document.head.append(presentation);
  expect(getComputedStyle(cue!).opacity).toBe("0");
  expect(getComputedStyle(cue!).pointerEvents).toBe("none");

  // Pointer entry synthesizes no state in a DOM emulator, and the route keeps
  // no JS hover gate either: the button stays enabled, so in a real browser
  // the CSS :hover flip alone restores clickability without a re-render.
  for (const type of ["pointerenter", "mouseenter"]) {
    await act(async () => { stage?.dispatchEvent(new MouseEvent(type)); });
  }
  expect(cue?.disabled).toBe(false);
  expect(container.querySelector('[data-testid="pet-character"]')).toBeTruthy();
  expect(invoke.mock.calls.some(([request]) => request.operation === "openLauncher")).toBe(false);

  // The recovery half of the contract lives in the stylesheet: the dimming and
  // click-transparent rules only exist inside the hover-capable media query,
  // and only while the stage is neither hovered nor keyboard-focused — so a
  // hover, a keyboard focus, or a touch-only device always keeps the cue live.
  const hoverMedia = launcherCss.match(/@media \(hover: hover\) and \(pointer: fine\) \{([\s\S]*?)\n\}/)?.[1] ?? "";
  expect(hoverMedia).toContain(".desktop-pet-stage:not(:hover):not(:focus-within)");
  expect(hoverMedia).toContain(".desktop-assistant-chat-cue");
  expect(hoverMedia).toContain("opacity: 0");
  expect(hoverMedia).toContain("pointer-events: none");
  // The cue's own base block never hides or blocks itself unconditionally.
  const cueBase = launcherCss.match(/\.desktop-assistant-chat-cue \{([^}]+)\}/)?.[1] ?? "";
  expect(cueBase).not.toContain("opacity");
  expect(cueBase).not.toContain("pointer-events");
});
