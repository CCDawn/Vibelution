// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SETTINGS_FOCUS_INTENT_EVENT,
  SETTINGS_FOCUS_INTENT_STORAGE_KEY,
  SETTINGS_LAST_SECTION_STORAGE_KEY,
  consumeSettingsFocusIntent,
  notifySettingsContentReady,
  onSettingsContentReady,
  peekSettingsFocusIntent,
  readLastSettingsLocation,
  requestSettingsFocus,
  resolveSettingsEntry,
  subscribeSettingsFocus,
  writeLastSettingsLocation,
} from "./settingsNavigation";

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

afterEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe("settingsNavigation", () => {
  it("stores and consumes the focus intent exactly once", () => {
    expect(peekSettingsFocusIntent()).toBeNull();
    requestSettingsFocus({ groupId: "models-profiles", sectionId: "models", fieldId: "x.y" });
    expect(window.sessionStorage.getItem(SETTINGS_FOCUS_INTENT_STORAGE_KEY)).toContain("models-profiles");
    expect(consumeSettingsFocusIntent()).toEqual({
      groupId: "models-profiles",
      pageId: "",
      sectionId: "models",
      fieldId: "x.y",
    });
    // 一次性：消费后清除。
    expect(consumeSettingsFocusIntent()).toBeNull();
    expect(peekSettingsFocusIntent()).toBeNull();
  });

  it("drops malformed or empty intent payloads instead of throwing", () => {
    window.sessionStorage.setItem(SETTINGS_FOCUS_INTENT_STORAGE_KEY, "{not json");
    expect(consumeSettingsFocusIntent()).toBeNull();
    window.sessionStorage.setItem(SETTINGS_FOCUS_INTENT_STORAGE_KEY, JSON.stringify({ groupId: "", fieldId: " " }));
    expect(peekSettingsFocusIntent()).toBeNull();
  });

  it("broadcasts a hot-switch event that current subscribers receive", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeSettingsFocus(listener);
    const target = { groupId: "tooling-diagnostics", pageId: "tooling-health", sectionId: "log" };
    requestSettingsFocus(target);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(target);
    unsubscribe();
    requestSettingsFocus({ groupId: "overview-apply" });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("names the broadcast event with the vibelution settings namespace", () => {
    expect(SETTINGS_FOCUS_INTENT_EVENT).toBe("vibelution:settings-focus-intent");
  });

  it("persists and reads the last visited group and page", () => {
    expect(readLastSettingsLocation()).toBeNull();
    writeLastSettingsLocation({ groupId: "workbench-interface", pageId: "workbench-shortcuts" });
    expect(readLastSettingsLocation()).toEqual({ groupId: "workbench-interface", pageId: "workbench-shortcuts" });
    expect(window.localStorage.getItem(SETTINGS_LAST_SECTION_STORAGE_KEY)).toContain("workbench-interface");
    // 空 groupId 不写入。
    writeLastSettingsLocation({ groupId: "  " });
    expect(readLastSettingsLocation()).toEqual({ groupId: "workbench-interface", pageId: "workbench-shortcuts" });
  });

  it("ignores corrupted last-location records", () => {
    window.localStorage.setItem(SETTINGS_LAST_SECTION_STORAGE_KEY, "not-json");
    expect(readLastSettingsLocation()).toBeNull();
    window.localStorage.setItem(SETTINGS_LAST_SECTION_STORAGE_KEY, JSON.stringify({ pageId: "no-group" }));
    expect(readLastSettingsLocation()).toBeNull();
  });

  it("resolves the entry target with url > intent > last > default priority", () => {
    writeLastSettingsLocation({ groupId: "workbench-interface", pageId: "workbench-interface" });

    // 显式 URL 最高，且不消费意图。
    requestSettingsFocus({ groupId: "models-profiles" });
    expect(
      resolveSettingsEntry({ urlGroupId: "avatar-pet", urlPageId: "identity-profile", urlSectionId: "pet", urlFieldId: "" }),
    ).toEqual({
      groupId: "avatar-pet",
      pageId: "identity-profile",
      sectionId: "pet",
      fieldId: "",
      source: "url",
    });
    expect(peekSettingsFocusIntent()).not.toBeNull();

    // 无 URL 时意图次之，且消费即清除。
    expect(resolveSettingsEntry({ urlGroupId: "", urlPageId: "", urlSectionId: "", urlFieldId: "" })).toEqual({
      groupId: "models-profiles",
      pageId: "",
      sectionId: "",
      fieldId: "",
      source: "intent",
    });
    expect(peekSettingsFocusIntent()).toBeNull();

    // 无 URL 无意图时用上次停留。
    expect(resolveSettingsEntry({ urlGroupId: "", urlPageId: "", urlSectionId: "", urlFieldId: "" })).toEqual({
      groupId: "workbench-interface",
      pageId: "workbench-interface",
      sectionId: "",
      fieldId: "",
      source: "last",
    });

    // 全空 → default（消费方保持现状默认行为）。
    window.localStorage.removeItem(SETTINGS_LAST_SECTION_STORAGE_KEY);
    expect(resolveSettingsEntry({ urlGroupId: "", urlPageId: "", urlSectionId: "", urlFieldId: "" })).toEqual({
      groupId: "",
      pageId: "",
      sectionId: "",
      fieldId: "",
      source: "default",
    });
  });

  it("treats a url field target without group as an explicit url entry", () => {
    expect(resolveSettingsEntry({ urlGroupId: "", urlPageId: "", urlSectionId: "", urlFieldId: "ui.language" })).toEqual({
      groupId: "",
      pageId: "",
      sectionId: "",
      fieldId: "ui.language",
      source: "url",
    });
  });

  it("delivers content-ready pulses to the registered focus executor", () => {
    const notifier = vi.fn();
    const unsubscribe = onSettingsContentReady(notifier);
    notifySettingsContentReady();
    notifySettingsContentReady();
    expect(notifier).toHaveBeenCalledTimes(2);
    unsubscribe();
    // 退订后不再收到脉冲。
    notifySettingsContentReady();
    expect(notifier).toHaveBeenCalledTimes(2);
  });

  it("replaces the previous ready listener and stops when it unsubscribes", () => {
    const first = vi.fn();
    const second = vi.fn();
    const unsubscribeFirst = onSettingsContentReady(first);
    const unsubscribeSecond = onSettingsContentReady(second);
    notifySettingsContentReady();
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    unsubscribeSecond();
    unsubscribeFirst();
    notifySettingsContentReady();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
