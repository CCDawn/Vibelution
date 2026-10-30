/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LauncherStartupSettings } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { LauncherRoute } from "../routes/LauncherRoute";
import { LauncherShell } from "./LauncherShell";

vi.mock("./LauncherNavigation", () => ({
  LauncherNavigation: ({ lang }: { lang: string }) => <nav data-testid="language-navigation">{lang}</nav>,
}));
vi.mock("./LauncherTitlebar", () => ({
  LauncherTitlebar: ({ lang }: { lang: string }) => <output data-testid="language-topbar">{lang}</output>,
}));
vi.mock("./browserTelemetry", () => ({ collectBrowserPageSnapshot: () => ({}), postBrowserTelemetry: vi.fn() }));
vi.mock("./useWorkbenchLifecycleActions", () => ({ useWorkbenchLifecycleActions: () => ({ request: vi.fn() }) }));
vi.mock("../routes/LauncherBranchInstancesPanel", () => ({ LauncherBranchInstancesPanel: () => null }));
vi.mock("../routes/LauncherStartupSettingsPanel", () => ({
  LauncherStartupSettingsPanel: ({ setting, copy, onSave }: {
    setting?: LauncherStartupSettings;
    copy: { interfaceLanguage: string };
    onSave: (next: LauncherStartupSettings) => Promise<unknown>;
  }) => setting ? <button data-testid="save-language" type="button" onClick={() => {
    void onSave({ ...setting, interface: { ...setting.interface, language: setting.interface.language === "en" ? "zh" : "en" } });
  }}>{copy.interfaceLanguage}</button> : null,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Only fields consumed by this route and the real startup-settings transport.
function startup(language: "zh" | "en"): LauncherStartupSettings {
  return {
    launcher: { controlPort: 0, effectiveControlPort: 0, controlPortEnvOverride: 0 },
    runtime: { profile: "safe_local", preflightDoctor: true, requireVenv: true, profileOptions: [] },
    workbench: {
      backendPort: 8000, frontendPort: 5173, effectiveBackendPort: 8000, effectiveFrontendPort: 5173,
      backendPortEnvOverride: 0, frontendPortEnvOverride: 0,
      windowMode: "fullscreen", effectiveWindowMode: "fullscreen", windowModeEnvOverride: "", windowModeOptions: [],
      windowSize: "auto", effectiveWindowSize: "auto", windowSizeEnvOverride: "", windowSizeOptions: [],
    },
    interface: { language, languageOptions: ["zh", "en"] },
    configPath: "test-config.toml", configHash: "test-hash", restartRequired: true,
  };
}

describe("Launcher local settings language", () => {
  let root: Root;
  let container: HTMLDivElement;
  let client: QueryClient;
  let setting: LauncherStartupSettings;
  let listener: (() => void) | undefined;
  let fetchMock: ReturnType<typeof vi.fn>;
  let invoke: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    setting = startup("en");
    listener = undefined;
    fetchMock = vi.fn().mockRejectedValue(new Error("Workbench backend is offline"));
    vi.stubGlobal("fetch", fetchMock);
    invoke = vi.fn(async ({ path, init }: { path: string; init?: { body?: { interface?: { language?: "zh" | "en" } } } }) => {
      if (path === "status") return { ok: true, payload: { settings: { startup: setting } } };
      if (path === "branch-instances") return { ok: true, payload: { currentId: "main", items: [] } };
      if (path === "settings/startup") {
        setting = startup(init?.body?.interface?.language ?? "zh");
        return { ok: true, payload: { ok: true, setting } };
      }
      throw new Error(`Unexpected Launcher IPC path: ${path}`);
    });
    vi.stubGlobal("vibelutionLauncher", {
      launcherInvoke: invoke,
      getLauncherState: () => new Promise(() => undefined),
      onLauncherStateChanged: (next: () => void) => { listener = next; return () => { listener = undefined; }; },
    });
    client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    client.clear();
    container.remove();
    vi.unstubAllGlobals();
  });

  async function mount() {
    const router = createMemoryRouter([{
      element: <LauncherShell />,
      children: [{ path: "/launcher", element: <LauncherRoute /> }],
    }], { initialEntries: ["/launcher?view=settings"] });
    await act(async () => root.render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>));
  }

  async function expectLanguage(language: "zh" | "en") {
    await act(async () => {
      await vi.waitFor(() => {
        expect(container.querySelector("[data-testid='language-navigation']")?.textContent).toBe(language);
        expect(container.querySelector("[data-testid='language-topbar']")?.textContent).toBe(language);
        expect(container.querySelector("[data-testid='save-language']")?.textContent).toBe(language === "en" ? "Interface language" : "界面语言");
        expect(document.documentElement.lang).toBe(language === "en" ? "en" : "zh-CN");
      });
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(client.getQueryState(queryKeys.configPublic())).toBeUndefined();
  }

  it("starts in English with an empty cache and an offline workbench", async () => {
    expect(client.getQueryCache().getAll()).toHaveLength(0);
    await mount();
    await expectLanguage("en");
    expect(invoke).toHaveBeenCalledWith(expect.objectContaining({ path: "status" }));
  });

  it("follows saved settings in both directions without a config query", async () => {
    await mount();
    await expectLanguage("en");
    for (const language of ["zh", "en"] as const) {
      await act(async () => container.querySelector<HTMLButtonElement>("[data-testid='save-language']")?.click());
      await expectLanguage(language);
    }
    expect(invoke.mock.calls.filter(([request]) => request.path === "settings/startup")).toHaveLength(2);
  });

  it("follows state events and refetches while ignoring stale workbench language", async () => {
    client.setQueryData(queryKeys.configPublic(), { language: "zh" });
    await mount();
    // The stale workbench cache is unrelated to Launcher settings.
    await act(async () => { await vi.waitFor(() => expect(document.documentElement.lang).toBe("en")); });
    setting = startup("zh");
    await act(async () => listener?.());
    await act(async () => { await vi.waitFor(() => expect(document.documentElement.lang).toBe("zh-CN")); });
    setting = startup("en");
    await act(async () => { await client.refetchQueries({ queryKey: queryKeys.launcherStatus() }); });
    await act(async () => { await vi.waitFor(() => expect(document.documentElement.lang).toBe("en")); });
    expect(client.getQueryState(queryKeys.configPublic())?.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
