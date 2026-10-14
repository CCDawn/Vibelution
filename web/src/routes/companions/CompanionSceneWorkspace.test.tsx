// @vitest-environment happy-dom
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VirtualHumanCompanion } from "../../api/types";
import { CompanionSceneWorkspace } from "./CompanionSceneWorkspace";

vi.mock("./CompanionPortrait", () => ({ CompanionPortrait: () => <span data-test-portrait /> }));
vi.mock("./CompanionConversationHeader", () => ({ CompanionConversationHeader: ({ companion }: { companion: VirtualHumanCompanion }) => <div>{companion.displayName}</div> }));
vi.mock("./CompanionLifeRail", () => ({ CompanionLifeRail: ({ onOpenLifeSteward }: { onOpenLifeSteward: (id: string) => void }) => <button onClick={() => onOpenLifeSteward("exact-steward-session")}>生活管理</button> }));
vi.mock("../../components/conversation/ConversationShareExportButton", () => ({ ConversationShareExportButton: () => <button>导出</button> }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const steward = vi.fn();
const back = vi.fn();
function companion(location = "home", background = ""): VirtualHumanCompanion {
  return { agentId: "companion-a", displayName: "测试人物", snapshot: { state: { currentLocation: location, timezone: "Asia/Shanghai", locationStatus: "moving", movingTo: "park" }, causal: { embodiment: { sceneKey: "home-day", assetRefs: { background } } } } } as VirtualHumanCompanion;
}
function NativeDraft() {
  const [draft, setDraft] = useState("");
  return <><button onClick={() => setDraft("尚未发送的草稿")}>填写原生草稿</button><div className="composerFieldCodex"><textarea aria-label="原生草稿" placeholder="编程示例" value={draft} onChange={event => setDraft(event.currentTarget.value)} /></div><textarea aria-label="编辑旧消息" placeholder="编辑原内容" /></>;
}
async function render(person = companion(), showBack = false) {
  await act(async () => root.render(<MemoryRouter><CompanionSceneWorkspace companion={person} conversation={<NativeDraft />} sessionId="direct-session" messages={[]} lang="zh" onOpenLifeSteward={steward} onReturnToConversation={showBack ? back : undefined} /></MemoryRouter>));
}
beforeEach(() => { container = document.createElement("div"); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.clearAllMocks(); });

describe("CompanionSceneWorkspace", () => {
  it("does not let an authorized but mismatched legacy home projection override actual location", async () => {
    await render(companion("library", "/home-background.png"));
    expect(container.querySelector(".companion-scene-background")?.getAttribute("src")).toContain("library-background-v1.png");
    await render(companion("unknown-place", "/home-background.png"));
    expect(container.querySelector(".companion-scene-background")).toBeNull();
  });
  it("falls back from an authorized failed asset to the current-place image, then a neutral surface", async () => {
    await render(companion("home", "/authorized-background.png"));
    const image = () => container.querySelector<HTMLImageElement>(".companion-scene-background");
    expect(image()?.getAttribute("src")).toBe("/authorized-background.png");
    await act(async () => image()!.dispatchEvent(new Event("error")));
    expect(image()?.getAttribute("src")).toContain("room-background-v1.png");
    await act(async () => image()!.dispatchEvent(new Event("error")));
    expect(image()).toBeNull();
    expect(container.querySelector("textarea")).not.toBeNull();
    await render(companion("park"));
    expect(image()?.getAttribute("src")).toContain("park-background-v1.png");
  });
  it("preserves the native conversation draft while current location changes and shows arrival intent separately", async () => {
    await render();
    const textarea = container.querySelector("textarea")!;
    expect(textarea.getAttribute("placeholder")).toBe("发送消息…");
    expect(container.querySelector('[aria-label="编辑旧消息"]')?.getAttribute("placeholder")).toBe("编辑原内容");
    await act(async () => [...container.querySelectorAll("button")].find(button => button.textContent === "填写原生草稿")!.click());
    expect(textarea.value).toBe("尚未发送的草稿");
    expect(container.querySelector("[data-companion-scene]")?.getAttribute("data-companion-scene")).toBe("home");
    expect(container.textContent).toContain("→");
    await render(companion("library"));
    expect(container.querySelector("textarea")).toBe(textarea);
    expect(textarea.value).toBe("尚未发送的草稿");
    expect(container.querySelector("[data-companion-scene]")?.getAttribute("data-companion-scene")).toBe("library");
  });
  it("uses a neutral surface for an unknown location and leaves return/export and exact steward routing available", async () => {
    await render(companion("unknown-place"), true);
    expect(container.querySelector(".companion-scene-background")).toBeNull();
    const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === label)!;
    await act(async () => button("返回对话").click());
    expect(back).toHaveBeenCalledOnce();
    expect(button("导出")).toBeTruthy();
    await act(async () => button("生活").click());
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    await act(async () => button("生活管理").click());
    expect(steward).toHaveBeenCalledWith("exact-steward-session");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });
});
