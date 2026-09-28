/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import { resolveEffectiveBindings } from "./commands";
import { checkBindingConflict } from "./conflicts";

const effective = resolveEffectiveBindings();

describe("checkBindingConflict（win/linux 口径）", () => {
  it("占用检测：目标命令之外的命令已持有该绑定", () => {
    expect(
      checkBindingConflict("openSessionSearch", "CmdOrCtrl+k", effective, false),
    ).toEqual({
      kind: "occupied",
      binding: "CmdOrCtrl+k",
      ownerCommandId: "openCommandPalette",
      ownerTitle: "打开命令面板",
    });
  });

  it("物理等价归一：显式 Ctrl+k 与 CmdOrCtrl+k 判为同一占用", () => {
    expect(checkBindingConflict("openSessionSearch", "Ctrl+k", effective, false)?.kind).toBe(
      "occupied",
    );
  });

  it("保留键：编辑类与 Enter 被拒", () => {
    expect(checkBindingConflict("openSessionSearch", "CmdOrCtrl+c", effective, false)?.kind).toBe("reserved");
    expect(checkBindingConflict("openSessionSearch", "Enter", effective, false)).toEqual({
      kind: "reserved",
      binding: "Enter",
    });
  });

  it("保留键等价变体同样被拦", () => {
    expect(checkBindingConflict("openSessionSearch", "Ctrl+c", effective, false)?.kind).toBe("reserved");
  });

  it("命令自身现有绑定不构成冲突（覆盖=整组替换）", () => {
    expect(checkBindingConflict("openCommandPalette", "CmdOrCtrl+k", effective, false)).toBeNull();
  });

  it("空闲组合可绑定", () => {
    expect(checkBindingConflict("openSessionSearch", "Ctrl+Alt+g", effective, false)).toBeNull();
  });

  it("解析失败的绑定串返回 null", () => {
    expect(checkBindingConflict("openSessionSearch", "不是绑定串", effective, false)).toBeNull();
  });
});

describe("checkBindingConflict（mac 口径）", () => {
  it("Ctrl+k 与 CmdOrCtrl+k 在 mac 上是不同物理键，不判占用", () => {
    expect(checkBindingConflict("openSessionSearch", "Ctrl+k", effective, true)).toBeNull();
  });

  it("mac 上 Meta 等价组合判占用", () => {
    expect(checkBindingConflict("openSessionSearch", "CmdOrCtrl+k", effective, true)?.kind).toBe(
      "occupied",
    );
  });
});
