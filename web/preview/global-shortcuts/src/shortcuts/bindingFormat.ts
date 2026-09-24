/**
 * 预览专用快捷键绑定串格式 —— 解析与序列化的唯一实现（纯函数，无 DOM 依赖）。
 *
 * 模式借鉴 zai-org/ZCode（Apache-2.0）`packages/ui/src/shortcuts` 体系
 * （canonical 绑定串 + event.code 反查 + 平台修饰键语义），本仓库 TS 自研实现。
 *
 * Canonical 绑定串格式：`修饰键+修饰键+键`。
 * - 修饰键 canonical 顺序：CmdOrCtrl、Ctrl、Alt、AltGr、Shift；键名必须是最后一个 token；
 * - 单字符键小写化；命名键保留原文（F1..F12、ArrowUp、Enter 等，见 KEY_TO_CODE）；
 * - 同一形式同时用于：演示用「设置持久化」JSON、运行时匹配、展示标签归一。
 */

/** 解析后的绑定：修饰键开关 + 规范化键名。 */
export type ParsedShortcutBinding = {
  cmdOrCtrl: boolean;
  ctrl: boolean;
  alt: boolean;
  shift: boolean;
  altGr: boolean;
  /** 规范化键名：小写字母/数字/白名单符号，或命名键。 */
  key: string;
};

/** event.code → 规范键名（键盘布局差异下的可靠物理来源）。 */
export const CODE_TO_KEY: Readonly<Record<string, string>> = {
  ...Object.fromEntries(
    Array.from({ length: 26 }, (_, index) => [
      `Key${String.fromCharCode(65 + index)}`,
      String.fromCharCode(97 + index),
    ]),
  ),
  ...Object.fromEntries(
    Array.from({ length: 10 }, (_, index) => [`Digit${index}`, String(index)]),
  ),
  ...Object.fromEntries(
    Array.from({ length: 12 }, (_, index) => [`F${index + 1}`, `F${index + 1}`]),
  ),
  BracketLeft: "[",
  BracketRight: "]",
  Equal: "=",
  Minus: "-",
  Comma: ",",
  Period: ".",
  Slash: "/",
  Semicolon: ";",
  Quote: "'",
  Backquote: "`",
  Backslash: "\\",
  ArrowUp: "ArrowUp",
  ArrowDown: "ArrowDown",
  ArrowLeft: "ArrowLeft",
  ArrowRight: "ArrowRight",
  Enter: "Enter",
  Home: "Home",
  End: "End",
  PageUp: "PageUp",
  PageDown: "PageDown",
  Delete: "Delete",
  Insert: "Insert",
};

/** 规范键名 → 期望的 event.code（匹配兜底：macOS Option 改写、非 US 布局）。 */
export const KEY_TO_CODE: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(CODE_TO_KEY).map(([code, key]) => [key, code]),
);

type ModifierFlag = Exclude<keyof ParsedShortcutBinding, "key">;

const MODIFIER_TOKENS: Readonly<Record<string, ModifierFlag>> = {
  cmdorctrl: "cmdOrCtrl",
  ctrl: "ctrl",
  alt: "alt",
  altgr: "altGr",
  shift: "shift",
};

const SINGLE_CHAR_KEY_PATTERN = /^[a-z0-9[\]=\-,.\/;'`\\]$/;

/** 解析 canonical 绑定串；非法格式返回 null（消费方不得自行解析键位）。 */
export function parseShortcutBinding(binding: string): ParsedShortcutBinding | null {
  const tokens = binding
    .split("+")
    .map((token) => token.trim())
    .filter((token) => token.length > 0);
  if (tokens.length < 1) {
    return null;
  }
  const keyToken = tokens[tokens.length - 1];
  if (keyToken === undefined) {
    return null;
  }
  const key =
    keyToken.length === 1 ? keyToken.toLowerCase() : keyToken;
  const keyCanonical =
    key.length === 1
      ? SINGLE_CHAR_KEY_PATTERN.test(key)
        ? key
        : null
      : key in KEY_TO_CODE
        ? key
        : null;
  if (keyCanonical === null) {
    return null;
  }
  const parsed: ParsedShortcutBinding = {
    cmdOrCtrl: false,
    ctrl: false,
    alt: false,
    shift: false,
    altGr: false,
    key: keyCanonical,
  };
  for (const token of tokens.slice(0, -1)) {
    const flag = MODIFIER_TOKENS[token.toLowerCase()];
    if (flag === undefined || parsed[flag]) {
      return null;
    }
    parsed[flag] = true;
  }
  return parsed;
}

/** 序列化为 canonical 绑定串；缺键名返回 null。 */
export function serializeShortcutBinding(parsed: ParsedShortcutBinding): string | null {
  if (!parsed.key) {
    return null;
  }
  const parts: string[] = [];
  if (parsed.cmdOrCtrl) parts.push("CmdOrCtrl");
  if (parsed.ctrl) parts.push("Ctrl");
  if (parsed.alt) parts.push("Alt");
  if (parsed.altGr) parts.push("AltGr");
  if (parsed.shift) parts.push("Shift");
  parts.push(parsed.key);
  return parts.join("+");
}
