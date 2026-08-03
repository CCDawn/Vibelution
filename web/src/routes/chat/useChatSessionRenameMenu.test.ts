import { describe, expect, it } from "vitest";

import {
  defaultNewSessionTitle,
  isDefaultNewSessionTitle,
} from "./useChatSessionRenameMenu";

describe("isDefaultNewSessionTitle", () => {
  it("recognizes Chinese and English create placeholders", () => {
    expect(isDefaultNewSessionTitle("新会话")).toBe(true);
    expect(isDefaultNewSessionTitle("新建会话")).toBe(true);
    expect(isDefaultNewSessionTitle("New session")).toBe(true);
    expect(isDefaultNewSessionTitle("New Session")).toBe(true);
    expect(isDefaultNewSessionTitle("  新会话  ")).toBe(true);
  });

  it("rejects customized titles", () => {
    expect(isDefaultNewSessionTitle("资料搜集")).toBe(false);
    expect(isDefaultNewSessionTitle("DeepSeek")).toBe(false);
    expect(isDefaultNewSessionTitle("")).toBe(false);
  });
});

describe("defaultNewSessionTitle", () => {
  it("matches backend create defaults", () => {
    expect(defaultNewSessionTitle("zh")).toBe("新会话");
    expect(defaultNewSessionTitle("en")).toBe("New session");
  });
});
