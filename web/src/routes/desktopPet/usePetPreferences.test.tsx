// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPersonalAssistantSettings, updatePersonalAssistantSettings } from "../../api/personalAssistant";
import { DEFAULT_PET_PREFERENCES, readPetPreferences } from "./desktopPetPreferences";
import { PET_PREFERENCES_REFRESH_EVENT, usePetPreferences } from "./usePetPreferences";

vi.mock("../../api/personalAssistant", () => ({
  fetchPersonalAssistantSettings: vi.fn(), updatePersonalAssistantSettings: vi.fn(),
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement;
let first: ReturnType<typeof usePetPreferences>, second: ReturnType<typeof usePetPreferences>;
function Harness() {
  first = usePetPreferences();
  second = usePetPreferences();
  return <span>{first.preferences.characterId}/{second.preferences.characterId}</span>;
}
const settings = (preferences = DEFAULT_PET_PREFERENCES) => ({ settings: {
  displayName: "助理", preferences, preferencesConfigured: true, model: { currentModelId: "", choices: [] },
} });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 10))); }
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue(settings());
  vi.mocked(updatePersonalAssistantSettings).mockResolvedValue(settings());
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render() { await act(async () => root.render(<Harness />)); await settle(); }

describe("shared assistant preferences", () => {
  it("reads backend authority on mount and synchronizes all mounted surfaces after a local change", async () => {
    vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue(settings({ ...DEFAULT_PET_PREFERENCES, characterId: "xiaoluo" }));
    await render();
    expect(container.textContent).toBe("xiaoluo/xiaoluo");
    await act(async () => { await first.updatePreferences({ characterId: "dafeiyu" }); });
    expect(container.textContent).toBe("dafeiyu/dafeiyu");
    expect(updatePersonalAssistantSettings).toHaveBeenCalledWith({ preferences: { characterId: "dafeiyu" } });
  });
  it("handles storage events from another window", async () => {
    await render();
    await act(async () => {
      localStorage.setItem("vibelution.desktop-pet.preferences.v1", JSON.stringify({ ...DEFAULT_PET_PREFERENCES, characterId: "xiaoluo" }));
      window.dispatchEvent(new StorageEvent("storage", { key: "vibelution.desktop-pet.preferences.v1" }));
    });
    expect(container.textContent).toBe("xiaoluo/xiaoluo");
  });
  it("keeps rapid writes in order and does not replay stale snapshots to the local cache", async () => {
    await render();
    let release!: () => void;
    vi.mocked(updatePersonalAssistantSettings).mockImplementationOnce(() => new Promise(resolve => {
      release = () => resolve(settings());
    }));
    let a!: ReturnType<typeof first.updatePreferences>, b!: ReturnType<typeof first.updatePreferences>;
    await act(async () => {
      a = first.updatePreferences({ showStatus: false });
      b = first.updatePreferences({ showCompletion: false });
      await Promise.resolve();
    });
    expect(updatePersonalAssistantSettings).toHaveBeenCalledTimes(1);
    expect(readPetPreferences()).toMatchObject({ showStatus: false, showCompletion: false });
    await act(async () => { release(); await a; await b; });
    expect(updatePersonalAssistantSettings).toHaveBeenNthCalledWith(2, { preferences: { showCompletion: false } });
    expect(readPetPreferences()).toMatchObject({ showStatus: false, showCompletion: false });
  });
  it("preserves a newer edit when initial backend loading finishes late", async () => {
    let release!: () => void;
    vi.mocked(fetchPersonalAssistantSettings).mockImplementation(() => new Promise(resolve => {
      release = () => resolve(settings());
    }));
    // Use one mounted consumer so the deferred response has one owner.
    function Single() { first = usePetPreferences(); return <span>{first.preferences.characterId}</span>; }
    await act(async () => root.render(<Single />));
    await act(async () => {
      const update = first.updatePreferences({ characterId: "xiaoluo" });
      release(); await update;
    });
    expect(container.textContent).toBe("xiaoluo");
  });
  it("waits for an outstanding edit before refreshing on focus", async () => {
    await render();
    let release!: () => void;
    vi.mocked(updatePersonalAssistantSettings).mockImplementationOnce(() => new Promise(resolve => {
      release = () => resolve(settings({ ...DEFAULT_PET_PREFERENCES, showStatus: false }));
    }));
    let update!: ReturnType<typeof first.updatePreferences>;
    await act(async () => { update = first.updatePreferences({ showStatus: false }); await Promise.resolve(); });
    const reads = vi.mocked(fetchPersonalAssistantSettings).mock.calls.length;
    await act(async () => { window.dispatchEvent(new Event("focus")); await Promise.resolve(); });
    expect(fetchPersonalAssistantSettings).toHaveBeenCalledTimes(reads);
    expect(first.preferences.showStatus).toBe(false);
    vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue(settings({ ...DEFAULT_PET_PREFERENCES, showStatus: false }));
    await act(async () => { release(); await update; }); await settle();
    expect(first.preferences.showStatus).toBe(false);
    expect(readPetPreferences().showStatus).toBe(false);
  });
  it("orders first-run migration before newer partial edits", async () => {
    vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue({ ...settings(), settings: { ...settings().settings, preferencesConfigured: false } });
    let release!: () => void;
    vi.mocked(updatePersonalAssistantSettings).mockImplementationOnce(() => new Promise(resolve => {
      release = () => resolve(settings());
    }));
    function Single() { first = usePetPreferences(); return null; }
    await act(async () => root.render(<Single />)); await settle();
    let update!: ReturnType<typeof first.updatePreferences>;
    await act(async () => { update = first.updatePreferences({ characterId: "xiaoluo" }); await Promise.resolve(); });
    expect(updatePersonalAssistantSettings).toHaveBeenCalledTimes(1);
    await act(async () => { release(); await update; });
    expect(updatePersonalAssistantSettings).toHaveBeenNthCalledWith(2, { preferences: { characterId: "xiaoluo" } });
    expect(readPetPreferences().characterId).toBe("xiaoluo");
  });
  it("refreshes tool changes without running first-run migration again", async () => {
    await render();
    vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue({ settings: {
      ...settings().settings, preferencesConfigured: false,
      preferences: { ...DEFAULT_PET_PREFERENCES, characterId: "xiaoluo" },
    } });
    await act(async () => { window.dispatchEvent(new Event(PET_PREFERENCES_REFRESH_EVENT)); });
    await settle();
    expect(container.textContent).toBe("xiaoluo/xiaoluo");
    expect(updatePersonalAssistantSettings).not.toHaveBeenCalled();
  });
  it("keeps an edit newer than an in-flight tool refresh", async () => {
    function Single() { first = usePetPreferences(); return <span>{first.preferences.characterId}</span>; }
    await act(async () => root.render(<Single />)); await settle();
    let release!: () => void;
    vi.mocked(fetchPersonalAssistantSettings).mockImplementationOnce(() => new Promise(resolve => {
      release = () => resolve(settings());
    }));
    await act(async () => { window.dispatchEvent(new Event(PET_PREFERENCES_REFRESH_EVENT)); await Promise.resolve(); });
    let update!: ReturnType<typeof first.updatePreferences>;
    await act(async () => {
      update = first.updatePreferences({ characterId: "xiaoluo" });
      release(); await update;
    });
    expect(container.textContent).toBe("xiaoluo");
    expect(readPetPreferences().characterId).toBe("xiaoluo");
  });
  it("queues a tool refresh behind pending local edits", async () => {
    await render();
    let release!: () => void;
    vi.mocked(updatePersonalAssistantSettings).mockImplementationOnce(() => new Promise(resolve => {
      release = () => resolve(settings({ ...DEFAULT_PET_PREFERENCES, showStatus: false }));
    }));
    let update!: ReturnType<typeof first.updatePreferences>;
    await act(async () => { update = first.updatePreferences({ showStatus: false }); await Promise.resolve(); });
    const reads = vi.mocked(fetchPersonalAssistantSettings).mock.calls.length;
    await act(async () => { window.dispatchEvent(new Event(PET_PREFERENCES_REFRESH_EVENT)); await Promise.resolve(); });
    expect(fetchPersonalAssistantSettings).toHaveBeenCalledTimes(reads);
    vi.mocked(fetchPersonalAssistantSettings).mockResolvedValue(settings({ ...DEFAULT_PET_PREFERENCES, showStatus: false, characterId: "xiaoluo" }));
    await act(async () => { release(); await update; }); await settle();
    expect(first.preferences).toMatchObject({ showStatus: false, characterId: "xiaoluo" });
  });
  it("reports offline backend saving while keeping local preferences usable", async () => {
    await render();
    vi.mocked(updatePersonalAssistantSettings).mockRejectedValue(new Error("offline"));
    let result;
    await act(async () => { result = await first.updatePreferences({ showStatus: false }); });
    expect(result).toEqual({ local: true, backend: false });
    expect(first.preferences.showStatus).toBe(false);
  });
});
