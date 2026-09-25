import { describe, expect, it } from "vitest";

import {
  buildConfigApplyRequestPayload,
  isConfigBaselineStaleErrorMessage,
  shouldImmediateApplyConfigPath,
  shouldImmediateApplyFieldKind,
} from "./configApplyModel";

describe("configApplyModel", () => {
  it("detects baseline stale messages in zh and en", () => {
    expect(isConfigBaselineStaleErrorMessage("配置基线已过期，请刷新后重试")).toBe(true);
    expect(isConfigBaselineStaleErrorMessage("edit baseline is stale")).toBe(true);
    expect(isConfigBaselineStaleErrorMessage("network failed")).toBe(false);
  });

  it("immediately applies appearance paths and leaves tooling for explicit save", () => {
    expect(shouldImmediateApplyConfigPath("ui")).toBe(true);
    expect(shouldImmediateApplyConfigPath("ui.workbench_theme")).toBe(true);
    expect(shouldImmediateApplyConfigPath("pet.name")).toBe(true);
    expect(shouldImmediateApplyConfigPath("security")).toBe(false);
    expect(shouldImmediateApplyConfigPath("context_compression")).toBe(false);
  });

  it("declares boolean/select kinds immediate and everything else draft", () => {
    expect(shouldImmediateApplyFieldKind("boolean")).toBe(true);
    expect(shouldImmediateApplyFieldKind("select")).toBe(true);
    expect(shouldImmediateApplyFieldKind("number")).toBe(false);
    expect(shouldImmediateApplyFieldKind("string_list")).toBe(false);
    expect(shouldImmediateApplyFieldKind("json")).toBe(false);
    expect(shouldImmediateApplyFieldKind("text")).toBe(false);
    expect(shouldImmediateApplyFieldKind("multiline")).toBe(false);
    expect(shouldImmediateApplyFieldKind("secret")).toBe(false);
    expect(shouldImmediateApplyFieldKind(undefined)).toBe(false);
  });

  it("prefers frozen baseline hash when applying a draft override", () => {
    const payload = buildConfigApplyRequestPayload({
      draftOverride: {
        publicConfig: { language: "zh" } as never,
        draftMeta: { pendingSecrets: {} } as never,
        baseHash: "draft-content-hash",
      },
      draftConfig: { language: "en" } as never,
      draftMeta: { pendingSecrets: {} } as never,
      applyBaseHash: "frozen-baseline",
      applyBaseConfig: { language: "zh" } as never,
      editorText: "{}",
      hasEditorChanges: false,
      editorSections: [],
      loadFailedMessage: "load failed",
    });

    expect(payload.baseHash).toBe("frozen-baseline");
    expect(payload.baseConfig).toEqual({ language: "zh" });
    expect(payload.publicConfig).toEqual({ language: "zh" });
  });

  it("uses snapshot apply when baseline config is missing", () => {
    const payload = buildConfigApplyRequestPayload({
      draftConfig: { language: "zh", workbench: {} } as never,
      draftMeta: { pendingSecrets: {} } as never,
      applyBaseHash: "hash-1",
      applyBaseConfig: null,
      editorText: JSON.stringify({ language: "zh" }),
      hasEditorChanges: false,
      editorSections: [],
      loadFailedMessage: "load failed",
    });

    expect(payload.baseHash).toBe("hash-1");
    expect(payload.baseConfig).toBeNull();
    expect(payload.publicConfig).toBeTruthy();
  });
});
