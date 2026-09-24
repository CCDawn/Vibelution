/**
 * 全局快捷键 × 命令面板 —— 隔离预览应用（不进生产路由）。
 *
 * 桌面主视口模拟工作台壳层：左侧 mock 侧栏 + 右侧演示卡片区；
 * 真实挂载 VCommandPalette 与 VSessionSearchDialog（mock 数据，无生产接口），
 * 由自研全局快捷键基建（window capture 分发）唤起。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { VButton } from "../../../src/components/vui/primitives/VButton";
import { VChip } from "../../../src/components/vui/primitives/VChip";
import { VCommandPalette } from "../../../src/components/vui/product/workbench-shell/VCommandPalette";
import { VSessionSearchDialog } from "../../../src/components/vui/product/workbench-shell/VSessionSearchDialog";

import {
  buildMockPaletteItems,
  CONFLICT_DEMO,
  filterMockSessions,
  PALETTE_LABELS,
  readPreviewBootState,
  SEARCH_EMPTY_QUERY,
  SEARCH_FILTERED_QUERY,
  SESSION_SEARCH_LABELS,
} from "./mockData";
import {
  resolveEffectiveBindings,
  SHORTCUT_COMMANDS,
  type ShortcutCommandId,
  type ShortcutOverrides,
} from "./shortcuts/commands";
import { checkBindingConflict } from "./shortcuts/conflicts";
import {
  canonicalBindingKey,
  formatBindingLabel,
  isAppleKeyboardPlatform,
  type BindingLabelStyle,
} from "./shortcuts/platform";
import {
  useGlobalShortcuts,
  type ShortcutRecordOutcome,
} from "./shortcuts/useGlobalShortcuts";

type LogEntry = { id: number; text: string };

type ConflictBanner = { tone: "error" | "ok"; text: string } | null;

let logSeq = 0;

/** 命令面板空态截图用的确定性输入预置（原生 setter + input 事件）。 */
function presetPaletteQuery(text: string): boolean {
  const input = document.querySelector<HTMLInputElement>(
    '[data-testid="vui-command-palette"] input',
  );
  if (input === null) {
    return false;
  }
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, text);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
}

export function PreviewApp() {
  const bootRef = useRef(readPreviewBootState());
  const boot = bootRef.current;

  const [overrides, setOverrides] = useState<ShortcutOverrides>(() => {
    const initial: ShortcutOverrides = boot === "cleared" ? { cycleDensity: [] } : {};
    return initial;
  });
  const [paletteOpen, setPaletteOpen] = useState(boot === "palette" || boot === "palette-empty");
  const [searchOpen, setSearchOpen] = useState(
    boot === "search" || boot === "search-filtered" || boot === "search-empty",
  );
  const [searchQuery, setSearchQuery] = useState(() => {
    if (boot === "search-filtered") return SEARCH_FILTERED_QUERY;
    if (boot === "search-empty") return SEARCH_EMPTY_QUERY;
    return "";
  });
  const [searchExpanded, setSearchExpanded] = useState(false);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [compactDensity, setCompactDensity] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  });
  const [recordingTarget, setRecordingTarget] = useState<ShortcutCommandId | null>(
    boot === "recording" ? "openCommandPalette" : null,
  );
  const [recordHint, setRecordHint] = useState("");
  const [conflictBanner, setConflictBanner] = useState<ConflictBanner>(null);
  const [simulateAppleLabels, setSimulateAppleLabels] = useState(false);

  const realIsApple = useMemo(() => isAppleKeyboardPlatform(), []);
  const labelStyle: BindingLabelStyle = simulateAppleLabels || realIsApple ? "apple" : "windows";
  const effective = useMemo(() => resolveEffectiveBindings(overrides), [overrides]);

  const pushLog = useCallback((text: string) => {
    logSeq += 1;
    const entry = { id: logSeq, text };
    setLog((prev) => [entry, ...prev].slice(0, 8));
  }, []);

  const runCommand = useCallback(
    (commandId: ShortcutCommandId, via: string) => {
      const title = SHORTCUT_COMMANDS.find((c) => c.id === commandId)?.title ?? commandId;
      switch (commandId) {
        case "openCommandPalette":
          setPaletteOpen((open) => {
            pushLog(`${open ? "关闭" : "打开"}命令面板（via ${via}）`);
            return !open;
          });
          break;
        case "openSessionSearch":
          setSearchOpen((open) => {
            pushLog(`${open ? "关闭" : "打开"}会话搜索（via ${via}）`);
            return !open;
          });
          break;
        case "toggleSidebar":
          setSidebarCollapsed((collapsed) => {
            pushLog(`${collapsed ? "展开" : "折叠"}侧栏（via ${via}）`);
            return !collapsed;
          });
          break;
        case "cycleDensity":
          setCompactDensity((compact) => {
            pushLog(`切换信息密度 → ${compact ? "舒适" : "紧凑"}（via ${via}）`);
            return !compact;
          });
          break;
        case "switchTheme":
          setTheme((current) => {
            const next = current === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", next);
            pushLog(`切换主题 → ${next === "dark" ? "深色" : "浅色"}（via ${via}）`);
            return next;
          });
          break;
        case "openMockSettings":
          pushLog(`打开设置（演示 toast，设置页不在预览范围；via ${via}）`);
          break;
      }
      void title;
    },
    [pushLog],
  );

  /** 尝试落一个绑定：冲突拒绝或应用覆盖（演示入口与录制共用）。 */
  const attemptBinding = useCallback(
    (commandId: ShortcutCommandId, binding: string) => {
      const title = SHORTCUT_COMMANDS.find((c) => c.id === commandId)?.title ?? commandId;
      const conflict = checkBindingConflict(commandId, binding, effective, realIsApple);
      if (conflict !== null) {
        if (conflict.kind === "reserved") {
          setConflictBanner({
            tone: "error",
            text: `拒绝：${binding} 是保留键（浏览器/编辑原生行为或组件固定交互），不能绑定「${title}」。`,
          });
          pushLog(`冲突演示：${binding} 命中保留键黑名单 → 拒绝`);
        } else {
          setConflictBanner({
            tone: "error",
            text: `拒绝：${binding} 已被「${conflict.ownerTitle}」占用（物理等价归一后判定）。先为占用方改键或换一个组合。`,
          });
          pushLog(`冲突演示：${binding} 已被「${conflict.ownerTitle}」占用 → 拒绝`);
        }
        return;
      }
      setOverrides((prev) => ({ ...prev, [commandId]: [binding] }));
      setConflictBanner({
        tone: "ok",
        text: `已把 ${binding} 绑定到「${title}」（整组替换该命令的绑定）。`,
      });
      pushLog(`覆盖生效：「${title}」 → ${binding}`);
    },
    [effective, pushLog, realIsApple],
  );

  // 冲突演示初始态（URL ?state=conflict）：只演示一次。
  const conflictBootedRef = useRef(false);
  useEffect(() => {
    if (boot === "conflict" && !conflictBootedRef.current) {
      conflictBootedRef.current = true;
      attemptBinding(CONFLICT_DEMO.commandId, CONFLICT_DEMO.binding);
    }
  }, [boot, attemptBinding]);

  // 热键分发自检（URL ?selftest=1）：合成 Ctrl+K 走真实 window capture 分发链路，
  // 结果写到 <html data-selftest-hotkey>，供 headless dump-dom 断言。
  useEffect(() => {
    const selftest = new URLSearchParams(window.location.search).get("selftest");
    if (selftest !== "1") {
      return;
    }
    const timer = window.setTimeout(() => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "k",
          code: "KeyK",
          ctrlKey: true,
          metaKey: false,
          altKey: false,
          shiftKey: false,
          bubbles: true,
        }),
      );
      window.setTimeout(() => {
        const opened = document.querySelector('[data-testid="vui-command-palette"]') !== null;
        document.documentElement.setAttribute(
          "data-selftest-hotkey",
          opened ? "palette-open" : "fail",
        );
      }, 300);
    }, 300);
    return () => window.clearTimeout(timer);
  }, []);

  // 命令面板空态初始态：打开后预置一个必然零命中的查询。
  useEffect(() => {
    if (boot !== "palette-empty" || !paletteOpen) {
      return;
    }
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      if (presetPaletteQuery("zzzz") || tries > 20) {
        window.clearInterval(timer);
      }
    }, 50);
    return () => window.clearInterval(timer);
  }, [boot, paletteOpen]);

  // 录制态回调：pending 更新提示，binding 走冲突检测，invalid/cancel 收尾。
  const handleRecord = useCallback(
    (outcome: ShortcutRecordOutcome) => {
      const target = recordingTarget;
      if (target === null) {
        return;
      }
      const title = SHORTCUT_COMMANDS.find((c) => c.id === target)?.title ?? target;
      if (outcome.kind === "pending") {
        setRecordHint("等待完整组合键…（Esc 取消）");
        return;
      }
      setRecordingTarget(null);
      setRecordHint("");
      if (outcome.kind === "cancel") {
        pushLog("录制已取消");
        return;
      }
      if (outcome.kind === "invalid") {
        pushLog(
          outcome.reason === "no-modifier"
            ? "录制失败：普通字符键必须至少带一个修饰键（F 键/方向键等命名键除外）"
            : "录制失败：不支持的按键组合",
        );
        return;
      }
      const conflict = checkBindingConflict(target, outcome.binding, effective, realIsApple);
      if (conflict !== null) {
        const reason =
          conflict.kind === "reserved"
            ? "保留键黑名单"
            : `已被「${conflict.ownerTitle}」占用`;
        setConflictBanner({ tone: "error", text: `录制结果 ${outcome.binding} 被拒绝：${reason}。` });
        pushLog(`录制 ${outcome.binding} → 冲突拒绝（${reason}）`);
        return;
      }
      setOverrides((prev) => ({ ...prev, [target]: [outcome.binding] }));
      setConflictBanner({ tone: "ok", text: `「${title}」的新绑定 ${outcome.binding} 已生效。` });
      pushLog(`录制成功：「${title}」 → ${outcome.binding}`);
    },
    [effective, pushLog, realIsApple, recordingTarget],
  );

  useGlobalShortcuts({
    effective,
    isApple: realIsApple,
    recording: recordingTarget !== null,
    onCommand: runCommand,
    onRecord: handleRecord,
  });

  const paletteItems = useMemo(
    () =>
      buildMockPaletteItems({
        onNavigate: (target) => pushLog(`面板导航 → ${target}（演示动作，只记日志）`),
        onCycleDensity: () => runCommand("cycleDensity", "命令面板条目"),
        onSwitchTheme: () => runCommand("switchTheme", "命令面板条目"),
        onOpenSessionSearch: () => {
          setSearchOpen(true);
          pushLog("跨面板联动：命令面板 → 打开会话搜索");
        },
        onClearLog: () => setLog([]),
      }),
    [pushLog, runCommand],
  );

  const searchHits = useMemo(() => filterMockSessions(searchQuery), [searchQuery]);
  const visibleSessions = useMemo(
    () => (searchExpanded ? searchHits : searchHits.slice(0, 6)),
    [searchExpanded, searchHits],
  );
  const searchHasMore = !searchExpanded && searchHits.length > visibleSessions.length;

  const closeSearch = useCallback((open: boolean) => {
    setSearchOpen(open);
    if (!open) {
      setSearchExpanded(false);
    }
  }, []);

  const resetOverrides = useCallback(() => {
    setOverrides({});
    setConflictBanner(null);
    pushLog("已重置全部用户覆盖（回退默认绑定）");
  }, [pushLog]);

  const kbdLabel = (binding: string) => formatBindingLabel(binding, labelStyle);
  const hintPalette = kbdLabel("CmdOrCtrl+k");
  const hintSearch = kbdLabel("CmdOrCtrl+p");

  const canonicalWinKey = canonicalBindingKey("Ctrl+k", simulateAppleLabels);
  const canonicalCmdKey = canonicalBindingKey("CmdOrCtrl+k", simulateAppleLabels);

  return (
    <div className="gsp-app" data-preview-state={boot} data-density={compactDensity ? "compact" : "cozy"}>
      <header className="gsp-topbar">
        <div className="gsp-topbar-title">
          <strong>全局快捷键 × 命令面板 · 隔离预览</strong>
          <VChip tone="info">预览专用 · 不进生产路由</VChip>
          <VChip tone="neutral">分支 codex/zcode-global-shortcuts-palette</VChip>
        </div>
        <div className="gsp-topbar-actions">
          <VChip tone="neutral">宿主平台：{realIsApple ? "Apple（⌘）" : "Windows / Linux（Ctrl）"}</VChip>
          <VButton
            variant="secondary"
            density="compact"
            onClick={() => {
              const next = theme === "dark" ? "light" : "dark";
              document.documentElement.setAttribute("data-theme", next);
              setTheme(next);
              pushLog(`切换主题 → ${next === "dark" ? "深色" : "浅色"}（顶栏按钮）`);
            }}
          >
            {theme === "dark" ? "浅色主题" : "深色主题"}
          </VButton>
        </div>
      </header>

      <div className="gsp-body">
        <aside className="gsp-sidebar" data-collapsed={sidebarCollapsed ? "true" : "false"}>
          <p className="gsp-sidebar-title">mock 侧栏</p>
          {["团队", "会话", "知识库", "任务", "设置"].map((item) => (
            <div className="gsp-sidebar-item" key={item}>
              {item}
            </div>
          ))}
          {sidebarCollapsed ? (
            <p className="gsp-sidebar-note">已折叠（{kbdLabel("CmdOrCtrl+b")} 恢复）</p>
          ) : null}
        </aside>

        <main className="gsp-main">
          <section className="gsp-hero">
            <h1 className="gsp-hero-title">演示桌面主视口</h1>
            <p className="gsp-hero-text">
              按 <kbd>{hintPalette}</kbd> 唤起命令面板（VCommandPalette），
              按 <kbd>{hintSearch}</kbd> 唤起会话搜索（VSessionSearchDialog）。
              两个对话框是 web/src 的真实组件，本页只提供 mock 数据与全局快捷键基建。
            </p>
            <div className="gsp-hero-state">
              <VChip tone={paletteOpen ? "success" : "neutral"}>
                命令面板：{paletteOpen ? "打开" : "关闭"}
              </VChip>
              <VChip tone={searchOpen ? "success" : "neutral"}>
                会话搜索：{searchOpen ? "打开" : "关闭"}
              </VChip>
              <VChip tone="neutral">密度：{compactDensity ? "紧凑" : "舒适"}</VChip>
              <VChip tone="neutral">侧栏：{sidebarCollapsed ? "折叠" : "展开"}</VChip>
            </div>
          </section>

          {recordingTarget !== null ? (
            <div className="gsp-recording" role="status">
              正在为「{SHORTCUT_COMMANDS.find((c) => c.id === recordingTarget)?.title}」录制新绑定…
              {recordHint || "请按下组合键（Esc 取消）"}
            </div>
          ) : null}

          {conflictBanner !== null ? (
            <div className="gsp-banner" data-tone={conflictBanner.tone} role="alert">
              <span>{conflictBanner.text}</span>
              <VButton variant="ghost" density="compact" onClick={() => setConflictBanner(null)}>
                关闭提示
              </VButton>
            </div>
          ) : null}

          <div className="gsp-grid">
            <section className="gsp-card gsp-registry" aria-label="快捷键注册表">
              <h2 className="gsp-card-title">快捷键注册表（生效表）</h2>
              <p className="gsp-card-note">
                覆盖为整组替换；显式空数组 = 用户清除（不回退默认）；非法条目逐条忽略。
              </p>
              <div className="gsp-rows">
                {SHORTCUT_COMMANDS.map((command) => {
                  const override = overrides[command.id];
                  const status =
                    override === undefined ? "默认" : override.length === 0 ? "已清除" : "已覆盖";
                  const bindings = effective[command.id] ?? [];
                  return (
                    <div className="gsp-row" key={command.id}>
                      <div className="gsp-row-main">
                        <span className="gsp-row-title">{command.title}</span>
                        <span className="gsp-row-desc">{command.description}</span>
                      </div>
                      <div className="gsp-row-keys">
                        {bindings.length === 0 ? (
                          <VChip tone="warning">未设置</VChip>
                        ) : (
                          bindings.map((binding) => (
                            <kbd className="gsp-kbd" key={binding}>
                              {kbdLabel(binding)}
                            </kbd>
                          ))
                        )}
                        <VChip tone={status === "默认" ? "neutral" : status === "已清除" ? "warning" : "info"}>
                          {status}
                        </VChip>
                      </div>
                      <div className="gsp-row-actions">
                        <VButton
                          variant="secondary"
                          density="compact"
                          onClick={() => {
                            setRecordingTarget(command.id);
                            setRecordHint("");
                            pushLog(`开始为「${command.title}」录制新绑定`);
                          }}
                        >
                          录制
                        </VButton>
                        {override === undefined || override.length > 0 ? (
                          <VButton
                            variant="ghost"
                            density="compact"
                            onClick={() => {
                              setOverrides((prev) => ({ ...prev, [command.id]: [] }));
                              pushLog(`已清除「${command.title}」的绑定（显式空数组，不回退默认）`);
                            }}
                          >
                            清除
                          </VButton>
                        ) : null}
                        {override !== undefined ? (
                          <VButton
                            variant="ghost"
                            density="compact"
                            onClick={() => {
                              setOverrides((prev) => {
                                const next = { ...prev };
                                delete next[command.id];
                                return next;
                              });
                              pushLog(`「${command.title}」已恢复默认绑定`);
                            }}
                          >
                            恢复默认
                          </VButton>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            <div className="gsp-side-col">
              <section className="gsp-card" aria-label="操作日志">
                <h2 className="gsp-card-title">操作日志</h2>
                {log.length === 0 ? (
                  <p className="gsp-empty">暂无操作记录 — 按 {hintPalette} 或 {hintSearch} 试试</p>
                ) : (
                  <ul className="gsp-log">
                    {log.map((entry) => (
                      <li key={entry.id}>{entry.text}</li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="gsp-card" aria-label="冲突检测演示">
                <h2 className="gsp-card-title">冲突检测演示</h2>
                <div className="gsp-btn-row">
                  <VButton
                    variant="secondary"
                    density="compact"
                    onClick={() => attemptBinding(CONFLICT_DEMO.commandId, CONFLICT_DEMO.binding)}
                  >
                    演示占用冲突（{kbdLabel(CONFLICT_DEMO.binding)} → 会话搜索）
                  </VButton>
                  <VButton
                    variant="secondary"
                    density="compact"
                    onClick={() => attemptBinding("cycleDensity", "Enter")}
                  >
                    演示保留键拒绝（Enter → 切密度）
                  </VButton>
                </div>
              </section>

              <section className="gsp-card" aria-label="平台语义演示">
                <h2 className="gsp-card-title">平台语义（CmdOrCtrl）</h2>
                <div className="gsp-btn-row">
                  <VButton
                    variant={simulateAppleLabels ? "ghost" : "secondary"}
                    density="compact"
                    onClick={() => setSimulateAppleLabels(false)}
                  >
                    Windows / Linux 标签
                  </VButton>
                  <VButton
                    variant={simulateAppleLabels ? "secondary" : "ghost"}
                    density="compact"
                    onClick={() => setSimulateAppleLabels(true)}
                  >
                    模拟 macOS 标签（仅展示）
                  </VButton>
                </div>
                <p className="gsp-card-note">
                  匹配始终跟随宿主平台；此开关只切换展示标签与归一口径演示。
                  当前归一比较：Ctrl+k → <code>{canonicalWinKey ?? "invalid"}</code>，
                  CmdOrCtrl+k → <code>{canonicalCmdKey ?? "invalid"}</code>
                  （{simulateAppleLabels ? "mac 上两者不等价：⌘ 与 ⌃ 是不同物理键" : "win/linux 上两者物理等价"}）。
                </p>
              </section>

              <section className="gsp-card" aria-label="用户覆盖序列化">
                <h2 className="gsp-card-title">用户覆盖（可序列化，模拟 settings 持久化）</h2>
                <pre className="gsp-json">{JSON.stringify(overrides, null, 2)}</pre>
                <div className="gsp-btn-row">
                  <VButton variant="ghost" density="compact" onClick={resetOverrides}>
                    重置全部覆盖
                  </VButton>
                </div>
              </section>
            </div>
          </div>
        </main>
      </div>

      <VCommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        items={paletteItems}
        labels={PALETTE_LABELS}
        maxVisible={7}
      />
      <VSessionSearchDialog
        open={searchOpen}
        onOpenChange={closeSearch}
        query={searchQuery}
        onQueryChange={(query) => {
          setSearchQuery(query);
          setSearchExpanded(false);
        }}
        items={visibleSessions}
        hasMore={searchHasMore}
        onLoadMore={() => setSearchExpanded(true)}
        totalEstimate={filterMockSessions("").length}
        labels={SESSION_SEARCH_LABELS}
      />
    </div>
  );
}
