/**
 * 冲突策略 —— 保留键黑名单、物理等价归一后的占用检测。
 * 模式借鉴 zai-org/ZCode `packages/ui/src/shortcuts/conflicts.ts`（拒绝 + 标红策略）。
 * 本模块只回答「这个绑定能不能落」；匹配/录制在 useGlobalShortcuts.ts。
 */
import type { EffectiveShortcutBindings, ShortcutCommandId } from "./commands";
import { getShortcutCommand } from "./commands";
import { canonicalBindingKey } from "./platform";

/**
 * 保留键黑名单：编辑原生行为、浏览器刷新/开发者工具、功能键整段、
 * 组件固定交互单键。比较发生在 canonical 键上（等价变体同样被拦）。
 * 注：CmdOrCtrl+p 在 ZCode 中属于保留键（打印）；本预览按需求把它用作
 * 会话搜索默认键（见 commands.ts 差异说明），故不在本黑名单内。
 */
const RESERVED_BINDINGS: readonly string[] = [
  // 编辑类原生行为（主修饰键组合）
  ...["c", "v", "x", "z", "a", "s"].map((key) => `CmdOrCtrl+${key}`),
  "CmdOrCtrl+Shift+z",
  // 刷新与开发工具
  "CmdOrCtrl+r",
  "CmdOrCtrl+Shift+r",
  "CmdOrCtrl+Shift+i",
  "CmdOrCtrl+Shift+j",
  "CmdOrCtrl+Shift+c",
  // 功能键整段（F1-F12 的裸键与主修饰组合）
  ...Array.from({ length: 12 }, (_, index) => `F${index + 1}`),
  ...Array.from({ length: 12 }, (_, index) => `CmdOrCtrl+F${index + 1}`),
  // 方向键单键（组件固定交互）
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  // Enter：对话框确认键全局化会毁掉所有确认交互
  "Enter",
];

/** 保留键 canonical 集合，按平台惰性构建。 */
let reservedCache: { apple: ReadonlySet<string>; nonApple: ReadonlySet<string> } | null = null;
function getReservedCanonicalKeys(isApple: boolean): ReadonlySet<string> {
  if (reservedCache === null) {
    const apple = new Set<string>();
    const nonApple = new Set<string>();
    for (const binding of RESERVED_BINDINGS) {
      const appleKey = canonicalBindingKey(binding, true);
      if (appleKey !== null) apple.add(appleKey);
      const nonAppleKey = canonicalBindingKey(binding, false);
      if (nonAppleKey !== null) nonApple.add(nonAppleKey);
    }
    reservedCache = { apple, nonApple };
  }
  return isApple ? reservedCache.apple : reservedCache.nonApple;
}

export type ShortcutBindingConflict =
  | { kind: "reserved"; binding: string }
  | {
      kind: "occupied";
      binding: string;
      ownerCommandId: ShortcutCommandId;
      ownerTitle: string;
    };

/**
 * 冲突检测：把 newBinding 绑定到 commandId 是否会被拒绝；null 表示可绑定。
 * - 占用只与其他命令的生效绑定比对，命令自身的现有绑定不构成冲突（覆盖=整组替换）；
 * - 保留黑名单与占用比对都在 canonical 键上进行（平台等价组合不漏检）；
 * - 解析失败的绑定串在此返回 null，由调用方先用 parseShortcutBinding 校验合法性。
 */
export function checkBindingConflict(
  commandId: ShortcutCommandId,
  newBinding: string,
  effective: EffectiveShortcutBindings,
  isApple: boolean,
): ShortcutBindingConflict | null {
  const canonical = canonicalBindingKey(newBinding, isApple);
  if (canonical === null) {
    return null;
  }
  if (getReservedCanonicalKeys(isApple).has(canonical)) {
    return { kind: "reserved", binding: newBinding };
  }
  for (const other of Object.keys(effective) as ShortcutCommandId[]) {
    if (other === commandId) {
      continue;
    }
    const hit = (effective[other] ?? []).some(
      (binding) => canonicalBindingKey(binding, isApple) === canonical,
    );
    if (hit) {
      return {
        kind: "occupied",
        binding: newBinding,
        ownerCommandId: other,
        ownerTitle: getShortcutCommand(other).title,
      };
    }
  }
  return null;
}
