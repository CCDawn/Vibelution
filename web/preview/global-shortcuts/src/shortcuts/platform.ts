/**
 * 平台语义与展示标签 —— CmdOrCtrl 的平台分解、mac/Win 标签渲染、冲突检测用的
 * 物理等价归一（canonical key）。模式借鉴 zai-org/ZCode shortcuts 体系，TS 自研。
 */
import { parseShortcutBinding } from "./bindingFormat";

export type KeyboardPlatformInfo = {
  platform?: string;
  userAgent?: string;
};

export function readNavigatorPlatformInfo(): KeyboardPlatformInfo {
  if (typeof navigator === "undefined") {
    return {};
  }
  return {
    platform: navigator.platform,
    userAgent: navigator.userAgent,
  };
}

export function isAppleKeyboardPlatform(
  platformInfo: KeyboardPlatformInfo = readNavigatorPlatformInfo(),
): boolean {
  const platform = platformInfo.platform?.toLowerCase() ?? "";
  if (
    platform.includes("mac") ||
    platform.includes("iphone") ||
    platform.includes("ipad") ||
    platform.includes("ipod")
  ) {
    return true;
  }
  return /Mac|iPhone|iPad|iPod/.test(platformInfo.userAgent ?? "");
}

/** 标签渲染口径：windows = Ctrl/Alt/Shift+KEY；apple = ⌘⌃⌥⇧ 符号前缀。 */
export type BindingLabelStyle = "windows" | "apple";

function formatKeyLabel(key: string): string {
  return key.length === 1 ? key.toUpperCase() : key;
}

/** 渲染一条绑定串的人类标签；解析失败时原样返回。 */
export function formatBindingLabel(binding: string, style: BindingLabelStyle): string {
  const parsed = parseShortcutBinding(binding);
  if (parsed === null) {
    return binding;
  }
  if (style === "apple") {
    let prefix = "";
    if (parsed.cmdOrCtrl) prefix += "⌘";
    if (parsed.ctrl) prefix += "⌃";
    if (parsed.altGr || parsed.alt) prefix += "⌥";
    if (parsed.shift) prefix += "⇧";
    return `${prefix}${formatKeyLabel(parsed.key)}`;
  }
  const parts: string[] = [];
  if (parsed.cmdOrCtrl || parsed.ctrl) parts.push("Ctrl");
  if (parsed.alt || parsed.altGr) parts.push("Alt");
  if (parsed.shift) parts.push("Shift");
  parts.push(formatKeyLabel(parsed.key));
  return parts.join("+");
}

/**
 * 冲突检测专用的物理等价归一：匹配侧把平台等价组合视为同一物理键，
 * 冲突比较也必须用同一口径，否则 win 上录出的 CmdOrCtrl+m 会绕过对
 * 显式 Ctrl+m 的占用检测（无提示静默遮蔽）。
 * - 非 apple：primary = CmdOrCtrl|Ctrl|AltGr（同一物理主修饰），alt = Alt|AltGr；
 * - apple：primary = CmdOrCtrl|AltGr，secondaryCtrl = Ctrl（独立物理键），alt = Alt|AltGr。
 */
export function canonicalBindingKey(binding: string, isApple: boolean): string | null {
  const parsed = parseShortcutBinding(binding);
  if (parsed === null) {
    return null;
  }
  if (isApple) {
    return `${parsed.cmdOrCtrl || parsed.altGr ? 1 : 0}${parsed.ctrl ? 1 : 0}${
      parsed.alt || parsed.altGr ? 1 : 0
    }${parsed.shift ? 1 : 0}:${parsed.key}`;
  }
  return `${parsed.cmdOrCtrl || parsed.ctrl || parsed.altGr ? 1 : 0}${
    parsed.alt || parsed.altGr ? 1 : 0
  }${parsed.shift ? 1 : 0}:${parsed.key}`;
}
