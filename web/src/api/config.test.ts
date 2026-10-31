import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "./client";
import { fetchConfigBootstrap, fetchPublicConfig } from "./config";
import type { ConfigBootstrap, ConfigSummary } from "./types";

vi.mock("./client", () => ({ fetchJson: vi.fn() }));

const bootstrap: ConfigBootstrap = {
  hash: "config-hash",
  language: "zh",
  runtimeProfile: "balanced",
  defaultMode: "chat",
  defaultRoute: "/chat",
  intakeMode: "manual_review",
  modeAvailability: { chat: true, self_evolution: true, supervised_evolution: true },
  domainAvailability: { chat: true, evolution: true, config: true },
  modelLibraryCount: 1,
  modelLabels: { model: "Model" },
  modelImageInputSupport: { model: true },
  themeBackgroundImagePath: "",
  themeBackgroundImageUrl: "",
  themeBackgroundReadability: "standard",
};

describe("Config bootstrap transport", () => {
  beforeEach(() => {
    vi.mocked(fetchJson).mockReset();
    vi.stubGlobal("window", { location: new URL("vibelution-launcher://launcher/launcher-assistant") });
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each(["/", "/chat", "/launcher-other"])("uses workbench HTTP at %s even when the assistant bridge is not ready", async path => {
    vi.stubGlobal("window", { location: new URL(`http://127.0.0.1:8000${path}`) });
    const invoke = vi.fn().mockRejectedValue(new Error("ASSISTANT_NOT_READY"));
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    vi.mocked(fetchJson).mockResolvedValue(bootstrap);

    await expect(fetchConfigBootstrap()).resolves.toBe(bootstrap);
    expect(fetchJson).toHaveBeenCalledWith("/api/config/bootstrap", { signal: undefined });
    expect(invoke).not.toHaveBeenCalled();
  });

  it.each(["/launcher", "/launcher/assistant"])("uses the assistant bridge at the HTTP Launcher development path %s", async path => {
    vi.stubGlobal("window", { location: new URL(`http://127.0.0.1:9000${path}`) });
    const invoke = vi.fn().mockResolvedValue(bootstrap);
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });

    await expect(fetchConfigBootstrap()).resolves.toBe(bootstrap);
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "config" });
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it("preserves assistant errors without HTTP fallback at the development Launcher route", async () => {
    vi.stubGlobal("window", { location: new URL("http://127.0.0.1:9000/launcher/assistant") });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockRejectedValue(new Error("ASSISTANT_NOT_READY")) });
    await expect(fetchConfigBootstrap()).rejects.toThrow("ASSISTANT_NOT_READY");
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it("uses HTTP on a Launcher path without a native assistant bridge", async () => {
    vi.stubGlobal("window", { location: new URL("http://127.0.0.1:9000/launcher") });
    vi.mocked(fetchJson).mockResolvedValue(bootstrap);
    await expect(fetchConfigBootstrap()).resolves.toBe(bootstrap);
    expect(fetchJson).toHaveBeenCalledWith("/api/config/bootstrap", { signal: undefined });
  });

  it("does not fall back to HTTP when the launcher window has no assistant bridge", async () => {
    vi.stubGlobal("vibelutionLauncherAssistant", undefined);
    await expect(fetchConfigBootstrap()).rejects.toThrow("Launcher");
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it("uses the dedicated assistant bridge and preserves future bootstrap fields without HTTP", async () => {
    const native = { ...bootstrap, language: "en", futureField: { enabled: true } };
    const invoke = vi.fn().mockResolvedValue(native);
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });

    await expect(fetchConfigBootstrap()).resolves.toBe(native);
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "config" });
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it.each([null, {}, { invoke: false }])("rejects a malformed dedicated bridge without HTTP fallback: %j", async bridge => {
    vi.stubGlobal("vibelutionLauncherAssistant", bridge);
    await expect(fetchConfigBootstrap()).rejects.toThrow("Launcher");
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it.each([[], null, {}, { language: "fr" }, { language: ["en"] }])("rejects malformed native config without HTTP fallback: %j", async value => {
    const invoke = vi.fn().mockResolvedValue(value);
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(fetchConfigBootstrap()).rejects.toThrow("Launcher");
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it("keeps native rejection and cancellation on the assistant transport", async () => {
    const invoke = vi.fn().mockRejectedValueOnce(new Error("native unavailable"));
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(fetchConfigBootstrap()).rejects.toThrow("native unavailable");
    const controller = new AbortController();
    controller.abort();
    await expect(fetchConfigBootstrap({ signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
    expect(invoke).toHaveBeenCalledTimes(1);
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it("rejects an aborted native read even if its original IPC eventually succeeds", async () => {
    let acknowledge!: (value: unknown) => void;
    const invoke = vi.fn().mockImplementation(() => new Promise(resolve => { acknowledge = resolve; }));
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const controller = new AbortController();
    const pending = fetchConfigBootstrap({ signal: controller.signal });
    controller.abort();
    acknowledge(bootstrap);
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchJson).not.toHaveBeenCalled();
  });

  it("reads bootstrap data without requiring diagnostics and forwards cancellation", async () => {
    vi.stubGlobal("window", { location: new URL("http://127.0.0.1:8000/") });
    const signal = new AbortController().signal;
    vi.mocked(fetchJson).mockResolvedValue(bootstrap);

    await expect(fetchConfigBootstrap({ signal })).resolves.toBe(bootstrap);
    expect(fetchJson).toHaveBeenCalledWith("/api/config/bootstrap", { signal });
  });

  it("keeps the public summary endpoint and diagnostic fields available", async () => {
    const summary: ConfigSummary = {
      ...bootstrap,
      blockingCount: 1,
      warningCount: 2,
      sections: [{ id: "ui", title: "UI", summary: "Appearance" }],
    };
    vi.mocked(fetchJson).mockResolvedValue(summary);

    await expect(fetchPublicConfig()).resolves.toBe(summary);
    expect(fetchJson).toHaveBeenCalledWith("/api/config/public", { signal: undefined });
  });
});
