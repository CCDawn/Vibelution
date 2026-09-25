/**
 * 快捷键执行内核 —— 匹配、录制与 window 级分发。
 * 模式借鉴 zai-org/ZCode（Apache-2.0）`packages/ui/src/shortcuts/bindings.ts`：
 * 纯函数内核 + IME/长按噪声过滤 + 精确修饰键匹配 + event.code 兜底。
 *
 * 分发监听挂在 window capture 阶段：命中生效表时 preventDefault + stopPropagation，
 * 既接管浏览器默认行为，也避免路由级 bubble 监听（如 chat 左栏的局部快捷键）
 * 对同一组合双触发。
 */
import { useEffect, useRef } from "react";

import { SHORTCUT_COMMANDS } from "./commands";
import type { EffectiveShortcutBindings, ShortcutCommandId } from "./commands";
import {
  CODE_TO_KEY,
  KEY_TO_CODE,
  parseShortcutBinding,
  serializeShortcutBinding,
  type ParsedShortcutBinding,
} from "./bindingFormat";

/** 匹配/录制所需的键盘事件结构（KeyboardEvent 子集，测试可构造）。 */
export interface ShortcutBindingEvent {
  key: string;
  code?: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  repeat?: boolean;
  isComposing?: boolean;
  /** 中文等 IME 组合中 Chromium 报 keyCode 229。 */
  keyCode?: number;
}

/** IME 组合态事件（isComposing / Process / Dead / keyCode 229）。 */
function isImeEvent(event: ShortcutBindingEvent): boolean {
  return (
    event.isComposing === true ||
    event.key === "Process" ||
    event.key === "Dead" ||
    event.keyCode === 229
  );
}

/** 不应触发/录制的噪声：长按 repeat、IME 组合中。 */
function isNoiseEvent(event: ShortcutBindingEvent): boolean {
  return event.repeat === true || isImeEvent(event);
}

/**
 * 通用匹配：canonical 绑定串与键盘事件是否命中。
 * 修饰键精确匹配（多余修饰键不算命中）：
 * - CmdOrCtrl：apple = meta 且无 ctrl；非 apple = ctrl 且无 meta；
 * - 显式 Ctrl：apple 上是独立物理键（ctrl 且无 meta）；非 apple 与 CmdOrCtrl 物理等价；
 * - AltGr：非 apple 上物理 AltGr 报 ctrl+alt 同按，视作主修饰 + Alt；
 * - 裸键绑定（无主修饰键）要求事件 meta/ctrl 抬起，防 Cmd+Enter 误命中裸 Enter。
 */
export function matchesShortcutBinding(
  event: ShortcutBindingEvent,
  binding: string,
  isApple: boolean,
): boolean {
  if (isNoiseEvent(event)) {
    return false;
  }
  const parsed = parseShortcutBinding(binding);
  if (parsed === null || !modifiersMatch(event, parsed, isApple)) {
    return false;
  }
  return eventMatchesKey(event, parsed.key);
}

function modifiersMatch(
  event: ShortcutBindingEvent,
  parsed: ParsedShortcutBinding,
  isApple: boolean,
): boolean {
  const { metaKey: meta, ctrlKey: ctrl, altKey: alt, shiftKey: shift } = event;
  const wantPrimary = parsed.cmdOrCtrl || parsed.altGr || (!isApple && parsed.ctrl);
  const wantAppleCtrl = !parsed.cmdOrCtrl && !parsed.altGr && parsed.ctrl && isApple;

  if (!wantPrimary && !wantAppleCtrl && (meta || ctrl)) {
    return false;
  }
  if (wantPrimary) {
    const ok = isApple ? meta && !ctrl : ctrl && !meta;
    if (!ok) {
      return false;
    }
  }
  if (wantAppleCtrl && (!ctrl || meta)) {
    return false;
  }
  if ((parsed.alt || parsed.altGr) !== alt) {
    return false;
  }
  return parsed.shift === shift;
}

/** 键匹配：event.key 精确 → 单字符小写 → event.code 反查兜底。 */
function eventMatchesKey(
  event: Pick<ShortcutBindingEvent, "key" | "code">,
  key: string,
): boolean {
  if (event.key === key) {
    return true;
  }
  if (event.key.length === 1 && event.key.toLowerCase() === key) {
    return true;
  }
  if (event.code !== undefined) {
    return KEY_TO_CODE[key] === event.code;
  }
  return false;
}

// ============================================================================
// 录制器（设置页改键 UI 属后续任务；录制语义与生效表一起先落地并测试）
// ============================================================================

export type ShortcutRecordOutcome =
  | { kind: "pending" }
  | { kind: "binding"; binding: string }
  | { kind: "invalid"; reason: "no-modifier" | "unsupported-key" }
  | { kind: "cancel" };

const MODIFIER_ONLY_KEYS = new Set([
  "Shift",
  "Control",
  "Meta",
  "Alt",
  "AltGraph",
  "OS",
]);

function normalizeEventKey(rawKey: string): string | null {
  if (rawKey.length === 1) {
    return /^[a-zA-Z0-9[\]=\-,./;'\\`]$/.test(rawKey) ? rawKey.toLowerCase() : null;
  }
  return rawKey in KEY_TO_CODE ? rawKey : null;
}

/** 键名提取：优先 event.code 反查物理基键（布局无关），event.key 仅作兜底。 */
function resolveKeyFromEvent(event: ShortcutBindingEvent): string | null {
  if (event.code !== undefined) {
    const fromCode = Object.prototype.hasOwnProperty.call(CODE_TO_KEY, event.code)
      ? CODE_TO_KEY[event.code]
      : undefined;
    if (fromCode !== undefined) {
      return fromCode;
    }
  }
  return normalizeEventKey(event.key);
}

/**
 * 录制键盘事件为 canonical 绑定串：
 * - pending：纯修饰键按下 / IME 噪声 —— 等待完整组合；
 * - binding：合法组合（主修饰键平台归一：mac Cmd、win/linux Ctrl → CmdOrCtrl）；
 * - invalid：无修饰键的普通字符键（命名键允许裸键），或主修饰键在归一中丢失。
 * Escape 的取消语义由 UI 层在捕获到 Escape 时返回 { kind: "cancel" }。
 */
export function recordShortcutBinding(
  event: ShortcutBindingEvent,
  isApple: boolean,
): ShortcutRecordOutcome {
  if (event.repeat === true || isModifierOnlyKey(event.key)) {
    return { kind: "pending" };
  }
  const key = resolveKeyFromEvent(event);
  if (key === null) {
    return { kind: "invalid", reason: "unsupported-key" };
  }
  const hasModifier = event.metaKey || event.ctrlKey || event.altKey || event.shiftKey;
  if (!hasModifier && key.length === 1) {
    return { kind: "invalid", reason: "no-modifier" };
  }
  const parsed: ParsedShortcutBinding = {
    cmdOrCtrl: isApple ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey,
    ctrl: isApple ? event.ctrlKey && !event.metaKey : false,
    alt: event.altKey,
    shift: event.shiftKey,
    altGr: false,
    key,
  };
  // 归一后主修饰键丢失（如 mac 的 Cmd+Ctrl 同按、win 的纯 Win 键）→ 拒绝，防裸键落盘。
  if ((event.metaKey || event.ctrlKey) && !parsed.cmdOrCtrl && !parsed.ctrl) {
    return { kind: "invalid", reason: "unsupported-key" };
  }
  const binding = serializeShortcutBinding(parsed);
  if (binding === null) {
    return { kind: "invalid", reason: "unsupported-key" };
  }
  return { kind: "binding", binding };
}

function isModifierOnlyKey(key: string): boolean {
  return MODIFIER_ONLY_KEYS.has(key);
}

// ============================================================================
// window 级全局分发 hook
// ============================================================================

export type GlobalShortcutHandler = (commandId: ShortcutCommandId, binding: string) => void;

export type GlobalShortcutRecordHandler = (outcome: ShortcutRecordOutcome) => void;

export type UseGlobalShortcutsOptions = {
  effective: EffectiveShortcutBindings;
  /** 匹配的平台口径（真实宿主平台；标签展示可独立归一）。 */
  isApple: boolean;
  /** 录制态：置真时分发短路，按键进入录制器（对应 ZCode 的录制抑制语义）。 */
  recording: boolean;
  /** false 时完全不挂 window 监听（设置页录制器非录制态复用全局分发）；默认 true。 */
  enabled?: boolean;
  onCommand: GlobalShortcutHandler;
  onRecord: GlobalShortcutRecordHandler;
};

// 录制会话登记（跨 hook 实例共享）：设置页录制器录制时，其他实例的分发必须
// 让路，否则录制组合若命中生效表会先被全局分发抢跑（preventDefault + 触发命令）。
let activeRecorderCount = 0;

/** 是否有录制会话进行中（任意 useGlobalShortcuts 实例）。 */
export function isShortcutRecordingActive(): boolean {
  return activeRecorderCount > 0;
}

/**
 * window capture 级 keydown 监听：命中生效表即 preventDefault + stopPropagation
 * 并分发命令；录制态下按键交给录制器。监听器通过 ref 读最新依赖，避免每次渲染重挂。
 * 其他实例处于录制态时分发静默让路（录制优先）。
 */
export function useGlobalShortcuts(options: UseGlobalShortcutsOptions): void {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const { enabled = true, recording } = options;

  useEffect(() => {
    if (!enabled || !recording) {
      return;
    }
    activeRecorderCount += 1;
    return () => {
      activeRecorderCount -= 1;
    };
  }, [enabled, recording]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const handler = (event: KeyboardEvent) => {
      const current = optionsRef.current;
      if (isNoiseEvent(event)) {
        return;
      }
      if (current.recording) {
        if (event.key === "Escape") {
          event.preventDefault();
          current.onRecord({ kind: "cancel" });
          return;
        }
        const outcome = recordShortcutBinding(event, current.isApple);
        if (outcome.kind !== "pending") {
          event.preventDefault();
        }
        current.onRecord(outcome);
        return;
      }
      if (activeRecorderCount > 0) {
        return;
      }
      for (const entry of SHORTCUT_COMMANDS) {
        for (const binding of current.effective[entry.id] ?? []) {
          if (matchesShortcutBinding(event, binding, current.isApple)) {
            event.preventDefault();
            event.stopPropagation();
            current.onCommand(entry.id, binding);
            return;
          }
        }
      }
    };
    window.addEventListener("keydown", handler, { capture: true });
    return () => window.removeEventListener("keydown", handler, { capture: true });
  }, [enabled]);
}
