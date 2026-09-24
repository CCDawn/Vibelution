/**
 * 快捷键设置面板 —— 隔离预览应用（不进生产路由）。
 *
 * 复刻设置页（ConfigSettingsIndex）的视觉语言：分组标题 + 圆角描边面板行。
 * 交互核心全部来自 web/src/shortcuts 的真实纯逻辑（只读 import，零拷贝）：
 * - 生效表 resolveEffectiveBindings（默认 / 整组替换覆盖 / 显式空数组=清除）；
 * - 冲突检测 checkBindingConflict（保留键黑名单 + canonical 物理归一占用检测）；
 * - 录制 useGlobalShortcuts（window capture 分发 + 录制态短路，Esc 取消）；
 * - 持久化 read/writeStoredShortcutOverrides（真实 localStorage 键
 *   vibelution.shortcuts.overrides，本预览页 origin 内生效）。
 * UI 壳自绘，样式只用 vui 令牌类与共享状态配方（无内置字号/裸 hex/任意圆角）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { VButton } from "../../../src/components/vui/primitives/VButton";
import { VChip } from "../../../src/components/vui/primitives/VChip";
import {
  SHORTCUT_COMMANDS,
  resolveEffectiveBindings,
  type ShortcutCommandEntry,
  type ShortcutCommandId,
  type ShortcutOverrides,
} from "../../../src/shortcuts/commands";
import { checkBindingConflict } from "../../../src/shortcuts/conflicts";
import {
  canonicalBindingKey,
  formatBindingLabel,
  isAppleKeyboardPlatform,
  type BindingLabelStyle,
} from "../../../src/shortcuts/platform";
import {
  SHORTCUT_OVERRIDES_STORAGE_KEY,
  readStoredShortcutOverrides,
  writeStoredShortcutOverrides,
} from "../../../src/shortcuts/shortcutOverrides";
import {
  useGlobalShortcuts,
  type ShortcutRecordOutcome,
} from "../../../src/shortcuts/useGlobalShortcuts";

import {
  COMMAND_DESCRIPTIONS,
  CONFLICT_DEMO,
  RESERVED_DEMO,
  readPreviewBootState,
} from "./demoData";

type Banner = {
  tone: "info" | "success" | "warning" | "danger";
  text: string;
  detail?: string;
} | null;

function Kbd({ label, testId }: { label: string; testId?: string }) {
  return (
    <kbd
      className="inline-flex items-center rounded-vui-control border border-vui-border-subtle bg-vui-surface-inset px-1.5 py-0.5 font-medium text-vui-2xs text-vui-fg-secondary"
      data-testid={testId}
    >
      {label}
    </kbd>
  );
}

export function PreviewApp() {
  const bootRef = useRef(readPreviewBootState());
  const boot = bootRef.current;

  const [overrides, setOverrides] = useState<ShortcutOverrides>(() => {
    if (boot === "cleared") {
      return { openCommandPalette: [] };
    }
    return readStoredShortcutOverrides();
  });
  const [recordingTarget, setRecordingTarget] = useState<ShortcutCommandId | null>(
    boot === "recording" ? "openCommandPalette" : null,
  );
  const [recordHint, setRecordHint] = useState("");
  const [banner, setBanner] = useState<Banner>(null);
  const [simulateAppleLabels, setSimulateAppleLabels] = useState(false);

  const realIsApple = useMemo(() => isAppleKeyboardPlatform(), []);
  const labelStyle: BindingLabelStyle = simulateAppleLabels || realIsApple ? "apple" : "windows";
  const effective = useMemo(() => resolveEffectiveBindings(overrides), [overrides]);

  // 覆盖持久化：真实 localStorage 键（本预览页 origin 内生效）。
  useEffect(() => {
    writeStoredShortcutOverrides(overrides);
  }, [overrides]);

  const labelFor = useCallback(
    (binding: string) => formatBindingLabel(binding, labelStyle),
    [labelStyle],
  );

  /** 尝试落一个绑定（演示按钮与录制结果共用）：冲突拒绝或整组替换。 */
  const attemptBinding = useCallback(
    (commandId: ShortcutCommandId, binding: string) => {
      const title = SHORTCUT_COMMANDS.find((c) => c.id === commandId)?.title ?? commandId;
      const conflict = checkBindingConflict(commandId, binding, effective, realIsApple);
      if (conflict !== null) {
        if (conflict.kind === "reserved") {
          setBanner({
            tone: "danger",
            text: `拒绝：${binding} 是保留键（浏览器/编辑原生行为或组件固定交互），不能绑定为「${title}」的全局快捷键。`,
          });
        } else {
          const ownerBindings = effective[conflict.ownerCommandId] ?? [];
          const ownerCanonicals = ownerBindings
            .map((ownerBinding) => canonicalBindingKey(ownerBinding, realIsApple))
            .join(" / ");
          setBanner({
            tone: "danger",
            text: `拒绝：${binding} 已被「${conflict.ownerTitle}」占用。请换一个组合，或先为占用方改键。`,
            detail:
              `物理归一判定：新绑定 ${binding} → 归一 ${canonicalBindingKey(binding, realIsApple) ?? "?"}；` +
              `占用方 ${ownerBindings.join("、")} → 归一 ${ownerCanonicals || "?"}。两者相同即判定占用。`,
          });
        }
        return;
      }
      setOverrides((prev) => ({ ...prev, [commandId]: [binding] }));
      setBanner({
        tone: "success",
        text: `已把 ${binding} 绑定到「${title}」（覆盖为整组替换该命令的绑定）。`,
      });
    },
    [effective, realIsApple],
  );

  // 冲突/保留键演示初始态（URL ?state=conflict / ?state=reserved）：只演示一次。
  const bootedDemoRef = useRef(false);
  useEffect(() => {
    if (bootedDemoRef.current) {
      return;
    }
    if (boot === "conflict") {
      bootedDemoRef.current = true;
      attemptBinding(CONFLICT_DEMO.commandId, CONFLICT_DEMO.binding);
    } else if (boot === "reserved") {
      bootedDemoRef.current = true;
      attemptBinding(RESERVED_DEMO.commandId, RESERVED_DEMO.binding);
    }
  }, [boot, attemptBinding]);

  // 录制态回调：pending 更新提示；binding 走冲突检测；invalid/cancel 收尾。
  const handleRecord = useCallback(
    (outcome: ShortcutRecordOutcome) => {
      const target = recordingTarget;
      if (target === null) {
        return;
      }
      const title = SHORTCUT_COMMANDS.find((c) => c.id === target)?.title ?? target;
      if (outcome.kind === "pending") {
        setRecordHint("已收到修饰键，等待完整组合…（Esc 取消）");
        return;
      }
      setRecordingTarget(null);
      setRecordHint("");
      if (outcome.kind === "cancel") {
        setBanner({ tone: "info", text: "录制已取消，绑定未变更。" });
        return;
      }
      if (outcome.kind === "invalid") {
        setBanner({
          tone: "warning",
          text:
            outcome.reason === "no-modifier"
              ? "录制失败：普通字符键必须至少带一个修饰键（F 键、方向键等命名键允许裸键）。"
              : "录制失败：不支持的按键组合（主修饰键在归一中丢失），绑定未变更。",
        });
        return;
      }
      attemptBinding(target, outcome.binding);
      void title;
    },
    [attemptBinding, recordingTarget],
  );

  // 生效表命中即演示（清空绑定的命令不再触发，验证「未设置」语义）。
  const handleCommand = useCallback((commandId: ShortcutCommandId) => {
    const title = SHORTCUT_COMMANDS.find((c) => c.id === commandId)?.title ?? commandId;
    setBanner({
      tone: "info",
      text: `全局快捷键触发：「${title}」（预览页只演示分发，无真实动作）。`,
    });
  }, []);

  useGlobalShortcuts({
    effective,
    isApple: realIsApple,
    recording: recordingTarget !== null,
    onCommand: handleCommand,
    onRecord: handleRecord,
  });

  const startRecording = useCallback((commandId: ShortcutCommandId) => {
    setBanner(null);
    setRecordHint("");
    setRecordingTarget(commandId);
  }, []);

  const clearBinding = useCallback((commandId: ShortcutCommandId) => {
    const title = SHORTCUT_COMMANDS.find((c) => c.id === commandId)?.title ?? commandId;
    setOverrides((prev) => ({ ...prev, [commandId]: [] }));
    setBanner({
      tone: "warning",
      text: `已清除「${title}」的全部绑定（显式空数组 = 未设置，不回退默认）。`,
      detail: `持久化写入 ${SHORTCUT_OVERRIDES_STORAGE_KEY}：{"${commandId}":[]}。`,
    });
  }, []);

  const restoreDefault = useCallback((commandId: ShortcutCommandId) => {
    const title = SHORTCUT_COMMANDS.find((c) => c.id === commandId)?.title ?? commandId;
    setOverrides((prev) => {
      const next = { ...prev };
      delete next[commandId];
      return next;
    });
    setBanner({ tone: "info", text: `「${title}」已移除用户覆盖，恢复默认绑定。` });
  }, []);

  const resetAll = useCallback(() => {
    setOverrides({});
    setRecordingTarget(null);
    setRecordHint("");
    setBanner({ tone: "info", text: "已恢复全部默认绑定，并清除持久化覆盖。" });
  }, []);

  // 分组保持命令表顺序（当前仅「导航」组）。
  const groups = useMemo(() => {
    const map = new Map<string, ShortcutCommandEntry[]>();
    for (const command of SHORTCUT_COMMANDS) {
      const bucket = map.get(command.group);
      if (bucket === undefined) {
        map.set(command.group, [command]);
      } else {
        bucket.push(command);
      }
    }
    return Array.from(map.entries());
  }, []);

  return (
    <div className="grid min-h-screen content-start gap-0 bg-vui-bg-canvas text-vui-fg-primary">
      <header className="flex items-center justify-between gap-3 border-b border-vui-border-subtle bg-vui-surface-panel px-6 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <strong className="text-vui-md font-semibold">快捷键设置</strong>
          <VChip tone="info">隔离预览 · 不进生产路由</VChip>
          <VChip tone="neutral">codex/zcode-shortcuts-settings-preview</VChip>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <VChip tone="neutral">宿主平台：{realIsApple ? "macOS（⌘）" : "Windows / Linux（Ctrl）"}</VChip>
          <VButton
            variant={simulateAppleLabels ? "ghost" : "secondary"}
            density="compact"
            onClick={() => setSimulateAppleLabels(false)}
          >
            Ctrl 标签
          </VButton>
          <VButton
            variant={simulateAppleLabels ? "secondary" : "ghost"}
            density="compact"
            onClick={() => setSimulateAppleLabels(true)}
          >
            模拟 ⌘ 标签
          </VButton>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-3xl content-start gap-6 px-6 py-8">
        <section className="grid gap-1">
          <h1 className="m-0 text-vui-lg font-semibold">全局快捷键</h1>
          <p className="m-0 text-vui-xs leading-relaxed text-vui-fg-tertiary">
            点击「修改」后按下新组合键完成录制，Esc 取消；「清除」写入显式空数组（未设置，不回退默认）。
            覆盖持久化到 localStorage 键 <code className="text-vui-xs">{SHORTCUT_OVERRIDES_STORAGE_KEY}</code>（本预览页 origin 的真实存储）。
          </p>
        </section>

        {banner !== null ? (
          <div
            className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-3 vui-tone-${banner.tone}`}
            role={banner.tone === "danger" ? "alert" : "status"}
            data-testid="banner"
            data-banner-tone={banner.tone}
          >
            <div className="grid min-w-0 gap-1">
              <span className="text-vui-xs font-semibold">{banner.text}</span>
              {banner.detail ? (
                <span className="text-vui-xs leading-relaxed opacity-80">{banner.detail}</span>
              ) : null}
            </div>
            <VButton variant="ghost" density="compact" onClick={() => setBanner(null)}>
              关闭
            </VButton>
          </div>
        ) : null}

        {groups.map(([groupTitle, commands]) => (
          <section className="grid min-w-0 gap-2" key={groupTitle} aria-label={groupTitle}>
            <h2 className="m-0 px-1 text-vui-xs font-semibold text-vui-fg-secondary">{groupTitle}</h2>
            <div className="grid min-w-0 divide-y divide-vui-border-subtle overflow-hidden rounded-lg border border-vui-border-subtle bg-vui-surface-panel">
              {commands.map((command) => {
                const override = overrides[command.id];
                const bindings = effective[command.id] ?? [];
                const recording = recordingTarget === command.id;
                const status =
                  override === undefined
                    ? { label: "默认", tone: "neutral" as const }
                    : override.length === 0
                      ? { label: "已清除", tone: "warning" as const }
                      : { label: "已覆盖", tone: "info" as const };
                return (
                  <div
                    className="flex min-h-16 items-center gap-3 px-4 py-3 hover:bg-vui-surface-row"
                    key={command.id}
                    data-testid={`shortcut-row-${command.id}`}
                  >
                    <div className="grid min-w-0 flex-1 gap-1">
                      <span className="text-vui-xs font-semibold text-vui-fg-primary">{command.title}</span>
                      <span className="text-vui-xs leading-relaxed text-vui-fg-tertiary">
                        {COMMAND_DESCRIPTIONS[command.id]}
                      </span>
                    </div>

                    {recording ? (
                      <div
                        className="flex shrink-0 items-center gap-2 rounded-vui-control border border-vui-border-subtle bg-vui-surface-inset px-3 py-2"
                        role="status"
                        data-testid="recording-strip"
                      >
                        <span className="text-vui-xs font-medium text-vui-fg-primary">
                          录制中：请按下新组合键
                        </span>
                        <span className="text-vui-xs text-vui-fg-tertiary">
                          {recordHint || "Esc 取消"}
                        </span>
                      </div>
                    ) : (
                      <>
                        <div className="flex shrink-0 items-center gap-2" data-testid={`keys-${command.id}`}>
                          {bindings.length === 0 ? (
                            <VChip tone="warning" data-testid="unset-chip">
                              未设置
                            </VChip>
                          ) : (
                            bindings.map((binding) => (
                              <Kbd key={binding} label={labelFor(binding)} testId="binding-kbd" />
                            ))
                          )}
                          <VChip tone={status.tone}>{status.label}</VChip>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <VButton
                            variant="secondary"
                            density="compact"
                            isDisabled={recordingTarget !== null}
                            data-testid={`modify-${command.id}`}
                            onClick={() => startRecording(command.id)}
                          >
                            修改
                          </VButton>
                          {bindings.length > 0 ? (
                            <VButton
                              variant="ghost"
                              density="compact"
                              data-testid={`clear-${command.id}`}
                              onClick={() => clearBinding(command.id)}
                            >
                              清除
                            </VButton>
                          ) : null}
                          {override !== undefined ? (
                            <VButton
                              variant="ghost"
                              density="compact"
                              data-testid={`restore-${command.id}`}
                              onClick={() => restoreDefault(command.id)}
                            >
                              恢复默认
                            </VButton>
                          ) : null}
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}

        <section className="grid gap-3 rounded-lg border border-vui-border-subtle bg-vui-surface-panel p-4" aria-label="覆盖持久化">
          <div className="flex items-center justify-between gap-3">
            <strong className="text-vui-xs font-semibold text-vui-fg-primary">覆盖持久化（演示）</strong>
            <VButton variant="secondary" density="compact" data-testid="reset-all" onClick={resetAll}>
              恢复全部默认
            </VButton>
          </div>
          <p className="m-0 text-vui-xs leading-relaxed text-vui-fg-tertiary">
            与生产壳层同一套覆盖语义：整组替换、显式空数组保留为「未设置」、未知命令与非法条目在读取时清洗。
          </p>
          <pre
            className="m-0 overflow-x-auto rounded-vui-control border border-vui-border-subtle bg-vui-surface-inset p-3 text-vui-2xs leading-relaxed text-vui-fg-secondary"
            data-testid="overrides-json"
          >
            {JSON.stringify(overrides, null, 2)}
          </pre>
        </section>
      </main>
    </div>
  );
}
