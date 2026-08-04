import { describe, expect, it } from "vitest";

import {
  classifyProviderQuickSetupErrorKind,
  formatProviderPinBusyMessage,
  formatProviderPinErrorMessage,
  formatProviderPinSuccessMessage,
  isProviderModelAlreadyPinnedErrorMessage,
} from "./configProviderActionModel";

describe("configProviderActionModel", () => {
  it("classifies already-pinned messages", () => {
    expect(isProviderModelAlreadyPinnedErrorMessage("model already pinned")).toBe(true);
    expect(isProviderModelAlreadyPinnedErrorMessage("模型已存在")).toBe(true);
    expect(isProviderModelAlreadyPinnedErrorMessage("network timeout")).toBe(false);
  });

  it("classifies quick-setup error kinds", () => {
    expect(classifyProviderQuickSetupErrorKind("401 unauthorized api key")).toBe("auth");
    expect(classifyProviderQuickSetupErrorKind("cannot connect to base_url endpoint")).toBe("endpoint");
    expect(classifyProviderQuickSetupErrorKind("upstream models empty")).toBe("discovery");
  });

  it("formats pin busy / success / error copy", () => {
    expect(formatProviderPinBusyMessage({ modelCount: 1, firstModelRef: "p/m1" })).toContain("p/m1");
    expect(formatProviderPinBusyMessage({ modelCount: 3, completed: 2, total: 3 })).toContain("2/3");
    expect(formatProviderPinSuccessMessage({ pinnedCount: 2, skippedTotal: 1 })).toContain("新固定 2");
    expect(formatProviderPinSuccessMessage({ pinnedCount: 2, skippedTotal: 1 })).toContain("跳过已存在 1");
    expect(formatProviderPinErrorMessage({ pinnedCount: 0, errorMessage: "boom" })).toBe("固定失败：boom");
    expect(formatProviderPinErrorMessage({ pinnedCount: 1, errorMessage: "boom" })).toContain("已固定 1");
  });
});
