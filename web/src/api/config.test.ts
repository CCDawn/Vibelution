import { beforeEach, describe, expect, it, vi } from "vitest";

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
  beforeEach(() => vi.mocked(fetchJson).mockReset());

  it("reads bootstrap data without requiring diagnostics and forwards cancellation", async () => {
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
