/**
 * 快捷键命令表与生效表 —— 全局快捷键命令的唯一数据源（纯数据 + 纯函数）。
 * 模式借鉴 zai-org/ZCode（Apache-2.0）`packages/shared/src/shortcutCommands.ts`：
 * 命令表收敛键位知识，绑定串同一形式用于持久化/匹配/展示。
 *
 * 与 ZCode 的有意差异（已批准契约）：CmdOrCtrl+p 用作「会话搜索」默认键
 * （VS Code「转到文件」惯例）。应用是同源受控环境，分发层对命中的按键
 * preventDefault 接管浏览器默认行为。
 *
 * 只收录有真实全局动作的命令；路由级局部快捷键（如 chat 输入面板）不入表。
 */
import { parseShortcutBinding } from "./bindingFormat";

export type ShortcutCommandId =
  | "openCommandPalette"
  | "openSessionSearch";

export type ShortcutCommandEntry = {
  readonly id: ShortcutCommandId;
  readonly title: string;
  readonly group: string;
  /** 默认绑定（canonical 串）；多条表示双默认，覆盖时整组替换。 */
  readonly defaultBindings: readonly string[];
};

/** 命令表：全局快捷键命令的唯一事实来源。 */
export const SHORTCUT_COMMANDS: readonly ShortcutCommandEntry[] = [
  {
    id: "openCommandPalette",
    title: "打开命令面板",
    group: "导航",
    defaultBindings: ["CmdOrCtrl+k"],
  },
  {
    id: "openSessionSearch",
    title: "会话搜索",
    group: "导航",
    defaultBindings: ["CmdOrCtrl+p"],
  },
];

export function getShortcutCommand(id: ShortcutCommandId): ShortcutCommandEntry {
  const entry = SHORTCUT_COMMANDS.find((command) => command.id === id);
  if (entry === undefined) {
    throw new Error(`Unknown shortcut command: ${id}`);
  }
  return entry;
}

/** 用户覆盖：命令 ID → 绑定串数组（可序列化，localStorage 持久化）。 */
export type ShortcutOverrides = Readonly<Record<string, readonly string[]>>;

/** 生效表：命令 ID → 实际生效的绑定串数组。 */
export type EffectiveShortcutBindings = Readonly<Record<ShortcutCommandId, readonly string[]>>;

/**
 * 计算生效表：默认绑定 + 用户覆盖（整组替换）。
 * - 覆盖缺失（undefined）→ 用默认；
 * - 显式空数组 = 用户清除为「未设置」，生效表为空，不回退默认；
 * - 覆盖条目非法时逐条忽略；全部非法且非空 → 回退默认（手改持久化不得让整体失效）。
 */
export function resolveEffectiveBindings(
  overrides?: ShortcutOverrides,
): EffectiveShortcutBindings {
  const effective = {} as Record<ShortcutCommandId, readonly string[]>;
  for (const entry of SHORTCUT_COMMANDS) {
    const override = overrides?.[entry.id];
    if (override === undefined) {
      effective[entry.id] = entry.defaultBindings;
      continue;
    }
    const valid = override.filter((binding) => parseShortcutBinding(binding) !== null);
    if (override.length > 0 && valid.length === 0) {
      effective[entry.id] = entry.defaultBindings;
      continue;
    }
    effective[entry.id] = valid;
  }
  return effective;
}
