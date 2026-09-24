/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import { resolveEffectiveBindings, SHORTCUT_COMMANDS } from "./commands";

describe("resolveEffectiveBindings", () => {
  it("无覆盖时回退默认绑定", () => {
    const effective = resolveEffectiveBindings();
    for (const entry of SHORTCUT_COMMANDS) {
      expect(effective[entry.id]).toEqual(entry.defaultBindings);
    }
  });

  it("显式空数组 = 用户清除，生效表为空且不回退默认", () => {
    expect(resolveEffectiveBindings({ openSessionSearch: [] }).openSessionSearch).toEqual([]);
    expect(resolveEffectiveBindings({ openCommandPalette: [] }).openCommandPalette).toEqual([]);
    expect(resolveEffectiveBindings({ openCommandPalette: [] }).openSessionSearch).toEqual([
      "CmdOrCtrl+p",
    ]);
  });

  it("覆盖为整组替换", () => {
    expect(resolveEffectiveBindings({ openCommandPalette: ["Ctrl+Alt+k"] }).openCommandPalette).toEqual([
      "Ctrl+Alt+k",
    ]);
  });

  it("非法条目逐条忽略，合法条目保留", () => {
    expect(
      resolveEffectiveBindings({ openCommandPalette: ["无效绑定", "CmdOrCtrl+k"] }).openCommandPalette,
    ).toEqual(["CmdOrCtrl+k"]);
  });

  it("非空覆盖全部非法时回退默认", () => {
    expect(resolveEffectiveBindings({ openCommandPalette: ["无效绑定"] }).openCommandPalette).toEqual([
      "CmdOrCtrl+k",
    ]);
  });

  it("未知命令的覆盖整体忽略", () => {
    const effective = resolveEffectiveBindings({ unknownCommand: ["Ctrl+g"] } as Record<string, readonly string[]>);
    expect(effective.openCommandPalette).toEqual(["CmdOrCtrl+k"]);
  });
});
