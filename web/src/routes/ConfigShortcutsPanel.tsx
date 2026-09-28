/**
 * 设置页「快捷键」分区 —— 全局快捷键改键面板（health-diagnostics 同款接入：
 * 后端注册虚拟 section + 导航 page + 分区渲染层专用面板分支）。
 *
 * 逻辑全部复用 web/src/shortcuts 真实基建（零拷贝）：
 * - 命令清单/生效表 resolveEffectiveBindings（commands.ts，唯一数据源）；
 * - 冲突检测 checkBindingConflict（保留键黑名单 + canonical 物理归一占用）；
 * - 录制 useGlobalShortcuts（本面板仅录制/捕获态挂监听；非录制态分发交给
 *   GlobalCommandSurfaces 同一执行路径，录制期间其分发经录制门让路）；
 * - 录制态语义：Esc 取消 · Backspace 恢复该命令默认绑定（ZCode
 *   useShortcutRecording 对齐；Backspace 非可绑定键，仅录制态拦截）；
 * - 过滤：文本过滤（当前语言标题/描述）+「按键盘找」按键过滤（canonical
 *   物理归一，与 conflicts.ts 同源口径）；空态区分文本无命中 vs 键未占用；
 * - 持久化 read/writeStoredShortcutOverrides（localStorage 键
 *   vibelution.shortcuts.overrides），写入经订阅让全局分发即时生效。
 *
 * 命令文案来自 COMMAND_DISPLAY_COPY（按注册表 ShortcutCommandId 强类型映射，
 * 新增命令缺文案会在编译期报错）；命令执行不在本面板，改键即时作用于全局。
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { VButton, VChip, VNativeInput } from "../components/vui";
import {
  SHORTCUT_COMMANDS,
  resolveEffectiveBindings,
  type ShortcutCommandEntry,
  type ShortcutCommandId,
  type ShortcutOverrides,
} from "../shortcuts/commands";
import { checkBindingConflict } from "../shortcuts/conflicts";
import { canonicalBindingKey } from "../shortcuts/platform";
import {
  formatBindingLabel,
  isAppleKeyboardPlatform,
  type BindingLabelStyle,
} from "../shortcuts/platform";
import {
  readStoredShortcutOverrides,
  writeStoredShortcutOverrides,
} from "../shortcuts/shortcutOverrides";
import {
  useGlobalShortcuts,
  type ShortcutRecordOutcome,
} from "../shortcuts/useGlobalShortcuts";

import type { ConfigLanguage } from "./ConfigHealthDiagnosticsPanel";
import styles from "./ConfigShortcutsPanel.styles";

export type ConfigShortcutsPanelCopy = {
  shortcutsIntro: string;
  shortcutsPersistence: string;
  shortcutsEffectiveNow: string;
  shortcutsResetAll: string;
  shortcutsClose: string;
  shortcutsStatusDefault: string;
  shortcutsStatusOverridden: string;
  shortcutsStatusCleared: string;
  shortcutsUnset: string;
  shortcutsModify: string;
  shortcutsClear: string;
  shortcutsRestore: string;
  shortcutsRecording: string;
  shortcutsRecordingHint: string;
  shortcutsRecordingPending: string;
  shortcutsRecordCancelled: string;
  shortcutsRestoredByBackspace: string;
  shortcutsFilterPlaceholder: string;
  shortcutsFilterByKeystroke: string;
  shortcutsFilterCapturing: string;
  shortcutsFilterClear: string;
  shortcutsFilterUnknownKey: string;
  shortcutsFilterNoTextMatch: string;
  shortcutsFilterKeyUnbound: string;
  shortcutsInvalidNoModifier: string;
  shortcutsInvalidUnsupported: string;
  shortcutsBoundNotice: string;
  shortcutsReservedNotice: string;
  shortcutsOccupiedNotice: string;
  shortcutsSteal: string;
  shortcutsStealHint: string;
  shortcutsStealDone: string;
  shortcutsClearedNotice: string;
  shortcutsRestoredNotice: string;
  shortcutsResetAllNotice: string;
};

/** 命令展示文案：与注册表同键强类型；title 与 commands.ts 注册表 zh 名保持一致。 */
const COMMAND_DISPLAY_COPY: Record<
  ShortcutCommandId,
  { group: { zh: string; en: string }; title: { zh: string; en: string }; description: { zh: string; en: string } }
> = {
  openCommandPalette: {
    group: { zh: "导航", en: "Navigation" },
    title: { zh: "打开命令面板", en: "Open command palette" },
    description: {
      zh: "在应用任意位置唤起命令面板，快速跳转页面与执行动作",
      en: "Summon the command palette anywhere to jump between pages and run actions",
    },
  },
  openSessionSearch: {
    group: { zh: "导航", en: "Navigation" },
    title: { zh: "会话搜索", en: "Session search" },
    description: {
      zh: "在应用任意位置唤起会话搜索，跨会话检索历史对话",
      en: "Summon session search anywhere to look up past conversations across sessions",
    },
  },
};

type ShortcutsBanner = {
  tone: "info" | "success" | "warning" | "danger";
  text: string;
  detail?: string;
  /** 占用冲突时提供抢占动作：对方变为未绑定，新键落到当前命令。 */
  steal?: { targetId: ShortcutCommandId; binding: string; ownerId: ShortcutCommandId };
} | null;

/** {name} 占位符文案填充。 */
function formatCopy(template: string, vars: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => vars[key] ?? match);
}

type ConfigShortcutsPanelProps = {
  lang: ConfigLanguage;
  copy: ConfigShortcutsPanelCopy;
};

export function ConfigShortcutsPanel({ lang, copy }: ConfigShortcutsPanelProps) {
  const [overrides, setOverrides] = useState<ShortcutOverrides>(() => readStoredShortcutOverrides());
  const [recordingTarget, setRecordingTarget] = useState<ShortcutCommandId | null>(null);
  const [recordingPending, setRecordingPending] = useState(false);
  const [banner, setBanner] = useState<ShortcutsBanner>(null);
  // 命令文本过滤（按当前语言标题/描述/命令 id 匹配）。
  const [textFilter, setTextFilter] = useState("");
  // 按键式过滤：keyCapture = 等待下一次物理按键；keyFilter = 已捕获组合
  //（canonical 为物理等价口径，null 表示捕获到不可绑定键 → 必然无占用）。
  const [keyCapture, setKeyCapture] = useState(false);
  const [keyFilter, setKeyFilter] = useState<{ canonical: string | null; label: string } | null>(null);

  const isApple = useMemo(() => isAppleKeyboardPlatform(), []);
  const labelStyle: BindingLabelStyle = isApple ? "apple" : "windows";
  const effective = useMemo(() => resolveEffectiveBindings(overrides), [overrides]);

  // 覆盖持久化（真实存储键）；写入经订阅让 GlobalCommandSurfaces 即时重读生效表。
  useEffect(() => {
    writeStoredShortcutOverrides(overrides);
  }, [overrides]);

  const titleFor = useCallback(
    (commandId: ShortcutCommandId) => COMMAND_DISPLAY_COPY[commandId].title[lang],
    [lang],
  );

  /** 尝试落一个绑定：保留键/占用拒绝，可绑定则整组替换写入。 */
  const attemptBinding = useCallback(
    (commandId: ShortcutCommandId, binding: string) => {
      const conflict = checkBindingConflict(commandId, binding, effective, isApple);
      if (conflict !== null) {
        if (conflict.kind === "reserved") {
          setBanner({
            tone: "danger",
            text: formatCopy(copy.shortcutsReservedNotice, { binding, title: titleFor(commandId) }),
          });
        } else {
          setBanner({
            tone: "danger",
            text: formatCopy(copy.shortcutsOccupiedNotice, {
              binding,
              owner: conflict.ownerTitle,
            }),
            detail: formatCopy(copy.shortcutsStealHint, {
              binding,
              owner: titleFor(conflict.ownerCommandId),
              title: titleFor(commandId),
            }),
            steal: { targetId: commandId, binding, ownerId: conflict.ownerCommandId },
          });
        }
        return;
      }
      setOverrides((prev) => ({ ...prev, [commandId]: [binding] }));
      setBanner({
        tone: "success",
        text: formatCopy(copy.shortcutsBoundNotice, { binding, title: titleFor(commandId) }),
      });
    },
    [copy, effective, isApple, titleFor],
  );

  const stealBinding = useCallback(
    (targetId: ShortcutCommandId, binding: string, ownerId: ShortcutCommandId) => {
      setOverrides((prev) => ({ ...prev, [ownerId]: [], [targetId]: [binding] }));
      setBanner({
        tone: "success",
        text: formatCopy(copy.shortcutsStealDone, {
          binding,
          title: titleFor(targetId),
          owner: titleFor(ownerId),
        }),
      });
    },
    [copy, titleFor],
  );

  // 录制/捕获态回调：命令录制走冲突检测落键；按键过滤捕获态把一次物理按键
  // 归一为过滤条件；pending 更新提示；cancel/restore-default 收尾。
  const handleRecord = useCallback(
    (outcome: ShortcutRecordOutcome) => {
      if (keyCapture) {
        if (outcome.kind === "pending") {
          return;
        }
        setKeyCapture(false);
        if (outcome.kind === "cancel") {
          // Esc 退出按键捕获，不影响已有过滤。
          return;
        }
        if (outcome.kind === "binding") {
          const canonical = canonicalBindingKey(outcome.binding, isApple);
          setKeyFilter({
            canonical,
            label: canonical ? formatBindingLabel(outcome.binding, labelStyle) : copy.shortcutsFilterUnknownKey,
          });
          return;
        }
        if (outcome.kind === "invalid") {
          if (outcome.reason === "no-modifier" && outcome.key) {
            // 裸字符键：物理等价口径下等价于「无修饰键 + 该键」组合。
            const bare = outcome.key.toLowerCase();
            setKeyFilter({
              canonical: isApple ? `0000:${bare}` : `000:${bare}`,
              label: outcome.key.toUpperCase(),
            });
          } else {
            setKeyFilter({ canonical: null, label: copy.shortcutsFilterUnknownKey });
          }
          return;
        }
        // restore-default 在捕获态无恢复语义：等同退出捕获。
        return;
      }
      const target = recordingTarget;
      if (target === null) {
        return;
      }
      if (outcome.kind === "pending") {
        setRecordingPending(true);
        return;
      }
      setRecordingTarget(null);
      setRecordingPending(false);
      if (outcome.kind === "cancel") {
        setBanner({ tone: "info", text: copy.shortcutsRecordCancelled });
        return;
      }
      if (outcome.kind === "restore-default") {
        // 录制态 Backspace：恢复该命令默认绑定（移除用户覆盖）。
        setOverrides((prev) => {
          const next = { ...prev };
          delete next[target];
          return next;
        });
        setBanner({
          tone: "info",
          text: formatCopy(copy.shortcutsRestoredByBackspace, { title: titleFor(target) }),
        });
        return;
      }
      if (outcome.kind === "invalid") {
        setBanner({
          tone: "warning",
          text:
            outcome.reason === "no-modifier"
              ? copy.shortcutsInvalidNoModifier
              : copy.shortcutsInvalidUnsupported,
        });
        return;
      }
      attemptBinding(target, outcome.binding);
    },
    [attemptBinding, copy, isApple, keyCapture, labelStyle, recordingTarget, titleFor],
  );

  // 本面板负责录制与按键捕获；空闲态不挂监听，命令分发仍由 GlobalCommandSurfaces
  // 执行（录制/捕获期间其分发经录制门让路）。
  useGlobalShortcuts({
    effective,
    isApple,
    recording: recordingTarget !== null || keyCapture,
    enabled: recordingTarget !== null || keyCapture,
    onCommand: () => undefined,
    onRecord: handleRecord,
  });

  const startRecording = useCallback((commandId: ShortcutCommandId) => {
    setBanner(null);
    setRecordingPending(false);
    setKeyCapture(false);
    setRecordingTarget(commandId);
  }, []);

  const clearBinding = useCallback(
    (commandId: ShortcutCommandId) => {
      setOverrides((prev) => ({ ...prev, [commandId]: [] }));
      setBanner({
        tone: "warning",
        text: formatCopy(copy.shortcutsClearedNotice, { title: titleFor(commandId) }),
      });
    },
    [copy, titleFor],
  );

  const restoreDefault = useCallback(
    (commandId: ShortcutCommandId) => {
      setOverrides((prev) => {
        const next = { ...prev };
        delete next[commandId];
        return next;
      });
      setBanner({
        tone: "info",
        text: formatCopy(copy.shortcutsRestoredNotice, { title: titleFor(commandId) }),
      });
    },
    [copy, titleFor],
  );

  const resetAll = useCallback(() => {
    setOverrides({});
    setRecordingTarget(null);
    setRecordingPending(false);
    setBanner({ tone: "info", text: copy.shortcutsResetAllNotice });
  }, [copy]);

  // 过滤后的命令清单：文本过滤（当前语言标题/描述/命令 id）+ 按键过滤
  //（canonical 物理等价口径，与 conflicts.ts 冲突检测同源）取 AND。
  const visibleCommands = useMemo(() => {
    const normalizedText = textFilter.trim().toLowerCase();
    return SHORTCUT_COMMANDS.filter((command) => {
      if (normalizedText) {
        const display = COMMAND_DISPLAY_COPY[command.id];
        const haystack = `${display.title[lang]} ${display.description[lang]} ${command.id}`.toLowerCase();
        if (!haystack.includes(normalizedText)) {
          return false;
        }
      }
      if (keyFilter) {
        if (keyFilter.canonical === null) {
          return false;
        }
        const hit = (effective[command.id] ?? []).some(
          (binding) => canonicalBindingKey(binding, isApple) === keyFilter.canonical,
        );
        if (!hit) {
          return false;
        }
      }
      return true;
    });
  }, [effective, isApple, keyFilter, lang, textFilter]);

  // 分组保持命令表顺序；组名与命令描述按语言取自统一文案映射。
  const groups = useMemo(() => {
    const map = new Map<string, ShortcutCommandEntry[]>();
    for (const command of visibleCommands) {
      const groupLabel = COMMAND_DISPLAY_COPY[command.id].group[lang];
      const bucket = map.get(groupLabel);
      if (bucket === undefined) {
        map.set(groupLabel, [command]);
      } else {
        bucket.push(command);
      }
    }
    return Array.from(map.entries());
  }, [lang, visibleCommands]);

  const bannerToneStyle =
    banner?.tone === "danger"
      ? styles.bannerToneDanger
      : banner?.tone === "warning"
        ? styles.bannerToneWarning
        : banner?.tone === "success"
          ? styles.bannerToneSuccess
          : styles.bannerToneInfo;

  return (
    <div className={styles.groupList} data-testid="shortcuts-panel">
      <p className={styles.intro}>{copy.shortcutsIntro}</p>
      <p className={styles.intro}>
        {copy.shortcutsPersistence} {copy.shortcutsEffectiveNow}
      </p>

      {banner !== null ? (
        <div
          className={`${styles.banner} ${bannerToneStyle}`}
          role={banner.tone === "danger" ? "alert" : "status"}
          data-testid="shortcuts-banner"
          data-banner-tone={banner.tone}
        >
          <div className={styles.bannerBody}>
            <span className={styles.bannerText}>{banner.text}</span>
            {banner.detail ? <span className={styles.bannerDetail}>{banner.detail}</span> : null}
          </div>
          <div className={styles.rowActions}>
            {banner.steal ? (
              <VButton
                variant="secondary"
                density="compact"
                data-testid="shortcuts-banner-steal"
                onClick={() => {
                  const steal = banner.steal;
                  if (steal) {
                    stealBinding(steal.targetId, steal.binding, steal.ownerId);
                  }
                }}
              >
                {copy.shortcutsSteal}
              </VButton>
            ) : null}
            <VButton
              variant="ghost"
              density="compact"
              data-testid="shortcuts-banner-close"
              onClick={() => setBanner(null)}
            >
              {copy.shortcutsClose}
            </VButton>
          </div>
        </div>
      ) : null}

      <div className={styles.filterRow} data-testid="shortcuts-filter-row">
        <VNativeInput
          type="search"
          value={textFilter}
          className={styles.filterInput}
          placeholder={copy.shortcutsFilterPlaceholder}
          aria-label={copy.shortcutsFilterPlaceholder}
          data-testid="shortcuts-filter-input"
          onChange={(event) => setTextFilter(event.target.value)}
        />
        {keyCapture ? (
          <span className={styles.filterCapturing} role="status" data-testid="shortcuts-key-capturing">
            {copy.shortcutsFilterCapturing}
          </span>
        ) : null}
        <VButton
          variant={keyCapture ? "primary" : "secondary"}
          density="compact"
          aria-pressed={keyCapture}
          data-testid="shortcuts-filter-key-button"
          onClick={() => {
            setBanner(null);
            setKeyCapture((active) => !active);
          }}
        >
          {copy.shortcutsFilterByKeystroke}
        </VButton>
        {keyFilter ? (
          <>
            <VChip tone="info" data-testid="shortcuts-key-filter-chip">
              {keyFilter.label}
            </VChip>
            <VButton
              variant="ghost"
              density="compact"
              data-testid="shortcuts-filter-key-clear"
              onClick={() => setKeyFilter(null)}
            >
              {copy.shortcutsFilterClear}
            </VButton>
          </>
        ) : null}
      </div>

      {visibleCommands.length === 0 && (textFilter.trim() || keyFilter) ? (
        <div className={styles.filterEmpty} role="status" data-testid="shortcuts-filter-empty">
          {textFilter.trim() ? copy.shortcutsFilterNoTextMatch : copy.shortcutsFilterKeyUnbound}
        </div>
      ) : null}

      {groups.map(([groupLabel, commands]) => (
        <section className={styles.group} key={groupLabel} aria-label={groupLabel}>
          <h3 className={styles.groupTitle}>{groupLabel}</h3>
          <div className={styles.rows}>
            {commands.map((command) => {
              const override = overrides[command.id];
              const bindings = effective[command.id] ?? [];
              const recording = recordingTarget === command.id;
              const status =
                override === undefined
                  ? { label: copy.shortcutsStatusDefault, tone: "neutral" as const }
                  : override.length === 0
                    ? { label: copy.shortcutsStatusCleared, tone: "warning" as const }
                    : { label: copy.shortcutsStatusOverridden, tone: "info" as const };
              return (
                <div
                  className={styles.row}
                  key={command.id}
                  data-testid={`shortcuts-row-${command.id}`}
                >
                  <div className={styles.rowMain}>
                    <span className={styles.rowTitle}>
                      {COMMAND_DISPLAY_COPY[command.id].title[lang]}
                    </span>
                    <span className={styles.rowDesc}>
                      {COMMAND_DISPLAY_COPY[command.id].description[lang]}
                    </span>
                  </div>

                  {recording ? (
                    <div
                      className={styles.recordingStrip}
                      role="status"
                      data-testid="shortcuts-recording-strip"
                    >
                      <span className={styles.recordingText}>{copy.shortcutsRecording}</span>
                      <span className={styles.recordingHint}>
                        {recordingPending ? copy.shortcutsRecordingPending : copy.shortcutsRecordingHint}
                      </span>
                    </div>
                  ) : (
                    <>
                      <div className={styles.keys} data-testid={`shortcuts-keys-${command.id}`}>
                        {bindings.length === 0 ? (
                          <VChip tone="warning" data-testid="shortcuts-unset-chip">
                            {copy.shortcutsUnset}
                          </VChip>
                        ) : (
                          bindings.map((binding) => (
                            <kbd
                              className={styles.bindingKey}
                              key={binding}
                              data-testid="shortcuts-binding-kbd"
                            >
                              {formatBindingLabel(binding, labelStyle)}
                            </kbd>
                          ))
                        )}
                        <VChip tone={status.tone}>{status.label}</VChip>
                      </div>
                      <div className={styles.rowActions}>
                        <VButton
                          variant="secondary"
                          density="compact"
                          isDisabled={recordingTarget !== null}
                          data-testid={`shortcuts-modify-${command.id}`}
                          onClick={() => startRecording(command.id)}
                        >
                          {copy.shortcutsModify}
                        </VButton>
                        {bindings.length > 0 ? (
                          <VButton
                            variant="ghost"
                            density="compact"
                            data-testid={`shortcuts-clear-${command.id}`}
                            onClick={() => clearBinding(command.id)}
                          >
                            {copy.shortcutsClear}
                          </VButton>
                        ) : null}
                        {override !== undefined ? (
                          <VButton
                            variant="ghost"
                            density="compact"
                            data-testid={`shortcuts-restore-${command.id}`}
                            onClick={() => restoreDefault(command.id)}
                          >
                            {copy.shortcutsRestore}
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

      <div className={styles.rowActions}>
        <VButton variant="secondary" density="compact" data-testid="shortcuts-reset-all" onClick={resetAll}>
          {copy.shortcutsResetAll}
        </VButton>
      </div>
    </div>
  );
}
