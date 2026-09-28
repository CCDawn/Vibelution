/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import { parseShortcutBinding, serializeShortcutBinding } from "./bindingFormat";

describe("parseShortcutBinding", () => {
  it("解析 canonical 绑定串", () => {
    expect(parseShortcutBinding("CmdOrCtrl+k")).toEqual({
      cmdOrCtrl: true,
      ctrl: false,
      alt: false,
      shift: false,
      altGr: false,
      key: "k",
    });
  });

  it("单字符键小写化、修饰键大小写不敏感", () => {
    expect(parseShortcutBinding("CTRL+SHIFT+D")?.key).toBe("d");
    expect(parseShortcutBinding("Ctrl+Shift+D")?.shift).toBe(true);
  });

  it("命名键保留原文", () => {
    expect(parseShortcutBinding("CmdOrCtrl+Shift+]")?.key).toBe("]");
    expect(parseShortcutBinding("Enter")?.key).toBe("Enter");
  });

  it("拒绝重复修饰键与未知修饰键", () => {
    expect(parseShortcutBinding("Ctrl+Ctrl+k")).toBeNull();
    expect(parseShortcutBinding("Hyper+k")).toBeNull();
  });

  it("拒绝空串、缺键名与非法键", () => {
    expect(parseShortcutBinding("")).toBeNull();
    expect(parseShortcutBinding("CmdOrCtrl+")).toBeNull();
    expect(parseShortcutBinding("CmdOrCtrl+%")).toBeNull();
    expect(parseShortcutBinding("NotAKey")).toBeNull();
  });
});

describe("serializeShortcutBinding", () => {
  it("按 canonical 顺序输出修饰键", () => {
    expect(
      serializeShortcutBinding({
        cmdOrCtrl: true,
        ctrl: false,
        alt: false,
        altGr: false,
        shift: true,
        key: "p",
      }),
    ).toBe("CmdOrCtrl+Shift+p");
  });

  it("键名缺失返回 null", () => {
    expect(
      serializeShortcutBinding({ cmdOrCtrl: true, ctrl: false, alt: false, altGr: false, shift: false, key: "" }),
    ).toBeNull();
  });

  it("解析-序列化往返稳定", () => {
    expect(serializeShortcutBinding(parseShortcutBinding("CmdOrCtrl+Shift+l"))).toBe(
      "CmdOrCtrl+Shift+l",
    );
  });
});
