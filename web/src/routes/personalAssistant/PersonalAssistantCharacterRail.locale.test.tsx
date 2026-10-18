// @vitest-environment happy-dom
import React, { act, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import { PersonalAssistantCharacterRail } from "./PersonalAssistantCharacterRail";

const { updatePreferences } = vi.hoisted(() => ({ updatePreferences: vi.fn() }));
vi.mock("../desktopPet/usePetPreferences", () => ({ usePetPreferences: () => ({
  preferences: { characterId: "dafeiyu", showCompletion: true, idleMessage: "" }, updatePreferences,
}) }));
vi.mock("../desktopPet/DesktopPetCharacter", () => ({ DesktopPetCharacter: ({ name }: { name: string }) => <span>{name}</span> }));
vi.mock("./useAssistantActivity", () => ({ useAssistantActivity: () => ({ tone: "idle", statusText: "Ready", unreadCount: 1, markRead: vi.fn() }) }));
vi.mock("./PersonalAssistantSettings", () => ({ PersonalAssistantSettings: ({ open, children }: { open: boolean; children: ReactNode }) => open ? <div role="dialog">{children}</div> : null }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("switches interface and existing save feedback without renaming the assistant or saving again", async () => {
  updatePreferences.mockResolvedValue({ local: true, backend: false });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(queryKeys.configPublic(), { language: "en" });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><PersonalAssistantCharacterRail
      assistant={{ agentId: "assistant", directSessionId: "session", displayName: "我的私人助理", status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" }}
      desktopPending={false} onOpenDesktop={vi.fn()} /></QueryClientProvider>));
    expect(container.querySelector('aside[aria-label="Assistant character"]')).not.toBeNull();
    expect(container.querySelector("h2")?.textContent).toBe("我的私人助理");
    expect(container.textContent).toContain("View 1 new message");
    const settings = [...container.querySelectorAll("button")].find(button => button.textContent === "Assistant settings")!;
    await act(async () => settings.click());
    await act(async () => (container.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("Settings are saved on this device but have not synced to the assistant.");
    await act(async () => { client.setQueryData(queryKeys.configPublic(), { language: "zh" }); });
    await act(async () => new Promise(resolve => setTimeout(resolve, 0)));
    expect(container.querySelector('aside[aria-label="个人助理角色"]')).not.toBeNull();
    expect(container.querySelector("h2")?.textContent).toBe("我的私人助理");
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("设置已暂存本机，尚未同步到助理。");
    expect(updatePreferences).toHaveBeenCalledTimes(1);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    client.clear();
  }
});
