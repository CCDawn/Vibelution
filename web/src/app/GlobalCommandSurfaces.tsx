/**
 * 全局命令面（workbench 根路由挂载，与 AppShell 并列）：全局快捷键分发 +
 * 命令面板 + 会话搜索。
 *
 * - Ctrl+K / ⌘K 唤起 VCommandPalette（命令源：壳层主导航 + 壳层动作，非 mock）；
 * - Ctrl+P / ⌘P 唤起 VSessionSearchDialog（数据源：useSessionSearchQuery，server 分页）；
 * - 快捷键基建见 web/src/shortcuts/；用户覆盖持久化到
 *   localStorage（vibelution.shortcuts.overrides），改键入口在设置页
 *   「快捷键」分区（ConfigShortcutsPanel），覆盖变更经订阅即时生效，无需重载。
 *
 * 本组件只渲染 portal 对话框，不进 AppShell 布局树；特性开关经
 * config 公共接口自行解析（与 AppShell 共享同一 react-query 缓存键）。
 */
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchPublicConfig } from "../api/config";
import { queryKeys } from "../api/queryKeys";
import { VCommandPalette } from "../components/vui/product/workbench-shell/VCommandPalette";
import { VSessionSearchDialog } from "../components/vui/product/workbench-shell/VSessionSearchDialog";
import { useShellI18n } from "../i18n/useShellI18n";
import {
  resolveEffectiveBindings,
  type ShortcutCommandId,
  type ShortcutOverrides,
} from "../shortcuts/commands";
import {
  readStoredShortcutOverrides,
  subscribeStoredShortcutOverrides,
  writeStoredShortcutOverrides,
} from "../shortcuts/shortcutOverrides";
import { isAppleKeyboardPlatform } from "../shortcuts/platform";
import { useGlobalShortcuts } from "../shortcuts/useGlobalShortcuts";
import { serializeChatRouteSelection } from "../routes/chat/chatSelectionProjection";
import { useSessionSearchQuery } from "../routes/useSessionSearchQuery";
import { isWorkbenchDomainEnabled, isWorkbenchModeEnabled } from "./workbenchContract";
import {
  isCommandItem,
  readRecentCommandIds,
  recordRecentCommandId,
  resolvePaletteScope,
  withRecentGroupTop,
} from "./paletteScope";

export function GlobalCommandSurfaces() {
  const { lang, t } = useShellI18n();
  const navigate = useNavigate();

  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: fetchPublicConfig,
  });
  const chatEnabled = isWorkbenchDomainEnabled(configQuery.data, "chat");
  const supervisedEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "supervised_evolution");
  const selfEvolutionEnabled = isWorkbenchModeEnabled(configQuery.data, "self_evolution");

  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // 命令面板最近使用（MRU）：只记面板内执行的命令条目（会话搜索不记）。
  const [recentCommandIds, setRecentCommandIds] = useState<readonly string[]>(() =>
    readRecentCommandIds(),
  );
  // 用户覆盖：与设置页改键（ConfigShortcutsPanel）共用同一 localStorage 存储；
  // 订阅变更即时重读，改键无需重载即对新分发生效。
  const [overrides, setOverrides] = useState<ShortcutOverrides>(() => readStoredShortcutOverrides());
  useEffect(() => {
    writeStoredShortcutOverrides(overrides);
  }, [overrides]);
  useEffect(
    () =>
      subscribeStoredShortcutOverrides(() => {
        setOverrides(readStoredShortcutOverrides());
      }),
    [],
  );

  const effective = useMemo(() => resolveEffectiveBindings(overrides), [overrides]);
  const isApple = useMemo(() => isAppleKeyboardPlatform(), []);

  const catalogSearch = useSessionSearchQuery({
    queryText: searchQuery,
    filters: { agentId: "", teamId: "" },
    enabled: searchOpen,
  });

  // 面板 scope 前缀分流（`#` 会话 / `>` 命令，见 paletteScope.ts）。
  const paletteScope = useMemo(() => resolvePaletteScope(paletteQuery), [paletteQuery]);
  // `#` 会话模式复用会话搜索的 server 分页结果（与 Ctrl+P 对话框共享
  // react-query 缓存键），仅在该模式下启用。
  const paletteSessionSearch = useSessionSearchQuery({
    queryText: paletteScope.kind === "sessions" ? paletteScope.text : "",
    filters: { agentId: "", teamId: "" },
    enabled: paletteOpen && paletteScope.kind === "sessions",
  });

  const recordRecentPaletteCommand = useCallback((commandId: string) => {
    setRecentCommandIds((previous) => recordRecentCommandId(commandId, previous));
  }, []);

  const runCommand = useCallback(
    (commandId: ShortcutCommandId) => {
      if (commandId === "openCommandPalette") {
        setPaletteOpen((open) => !open);
      } else if (commandId === "openSessionSearch") {
        setSearchOpen((open) => !open);
      }
    },
    [],
  );

  useGlobalShortcuts({
    effective,
    isApple,
    recording: false,
    onCommand: runCommand,
    onRecord: () => undefined,
  });

  const openSession = useCallback(
    (sessionId: string) => {
      setSearchOpen(false);
      navigate({
        pathname: "/chat",
        search: serializeChatRouteSelection("", { kind: "session", sessionId }),
      });
    },
    [navigate],
  );

  const paletteItems = useMemo(() => {
    if (paletteScope.kind === "sessions") {
      // `#` 会话模式：server 已按去前缀文本过滤，面板按原样列出（不再本地过滤）。
      return paletteSessionSearch.sessions.map((session) => ({
        id: `session:${session.id}`,
        label: session.title || session.id,
        detail:
          session.taskSummary ||
          session.resultCard?.summary ||
          [session.agentDisplayName || session.agentId || "", session.updatedAt || session.lastActive || ""]
            .filter(Boolean)
            .join(" · "),
        group: lang === "en" ? "Sessions" : "会话",
        onRun: () => openSession(session.id),
      }));
    }
    const navItems: { to: string; label: string; keywords: string }[] = [
      ...(chatEnabled ? [{ to: "/chat", label: t("navChat"), keywords: "chat 对话 会话" }] : []),
      ...(chatEnabled
        ? [{ to: "/companions", label: t("navCompanions"), keywords: "companions 伴侣 虚拟人" }]
        : []),
      { to: "/teams", label: t("navTeams"), keywords: "teams 团队" },
      ...(supervisedEvolutionEnabled || selfEvolutionEnabled
        ? [{ to: "/evolution/workspace", label: t("navEvolution"), keywords: "evolution 进化 supervised 监督进化 self 自进化" }]
        : []),
      { to: "/kernel", label: "Kernel", keywords: "kernel 内核 任务" },
      { to: "/memory", label: t("navMemory"), keywords: "memory 记忆" },
      { to: "/agents", label: t("navAgents"), keywords: "agents 智能体 助手 prompts skills tools" },
      // 设置页导航：落地位置由 settingsNavigation 统一裁决（意图 > 上次停留 > 默认）。
      { to: "/config", label: t("navConfig"), keywords: "config settings 配置 设置 偏好 preferences" },
    ];
    // MRU 只记命令面板内执行的条目；会话模式走上面分支，不经过这里。
    const runWithRecent = (commandId: string, run: () => void) => () => {
      recordRecentPaletteCommand(commandId);
      run();
    };
    const baseItems = [
      ...navItems.map((item) => ({
        id: `nav:${item.to}`,
        label: item.label,
        detail: lang === "en" ? "Navigation" : "导航",
        group: lang === "en" ? "Navigation" : "导航",
        keywords: item.keywords,
        onRun: runWithRecent(`nav:${item.to}`, () => navigate(item.to)),
      })),
      {
        id: "action:open-session-search",
        label: lang === "en" ? "Search all sessions" : "搜索全部会话",
        detail: lang === "en" ? "Open the session search dialog (Ctrl+P)" : "打开会话搜索（Ctrl+P）",
        group: lang === "en" ? "Actions" : "动作",
        keywords: "search session 会话 搜索 find",
        onRun: runWithRecent("action:open-session-search", () => setSearchOpen(true)),
      },
    ];
    // `>` 命令模式过滤掉导航条目；有记录时注入「最近使用」分组置顶（去重）。
    const scopedItems = paletteScope.kind === "commands" ? baseItems.filter(isCommandItem) : baseItems;
    return withRecentGroupTop(scopedItems, recentCommandIds, lang === "en" ? "Recent" : "最近使用");
  }, [
    chatEnabled,
    supervisedEvolutionEnabled,
    selfEvolutionEnabled,
    lang,
    navigate,
    t,
    paletteScope,
    paletteSessionSearch.sessions,
    openSession,
    recordRecentPaletteCommand,
    recentCommandIds,
  ]);

  // scope 决定输入提示与空态文案；默认模式保持现状。
  const paletteLabels = useMemo(() => {
    if (paletteScope.kind === "sessions") {
      return {
        searchPlaceholder: lang === "en" ? "Search sessions…" : "搜索会话…",
        emptyTitle: lang === "en" ? "No matching sessions" : "没有匹配的会话",
        hint: lang === "en" ? "↑↓ select · Enter open · Esc close" : "↑↓ 选择 · Enter 打开 · Esc 关闭",
      };
    }
    if (paletteScope.kind === "commands") {
      return {
        searchPlaceholder: lang === "en" ? "Run a command…" : "运行命令…",
        emptyTitle: lang === "en" ? "No matching commands" : "没有匹配的命令",
        hint: lang === "en" ? "↑↓ select · Enter run · Esc close" : "↑↓ 选择 · Enter 执行 · Esc 关闭",
      };
    }
    return {
      searchPlaceholder: lang === "en" ? "Search commands or navigation…" : "搜索命令或导航…",
      emptyTitle: lang === "en" ? "No matching commands" : "没有匹配的命令",
      hint: lang === "en" ? "↑↓ select · Enter run · Esc close" : "↑↓ 选择 · Enter 执行 · Esc 关闭",
    };
  }, [lang, paletteScope]);

  const sessionItems = useMemo(
    () =>
      catalogSearch.sessions.map((session) => ({
        id: session.id,
        title: session.title || session.id,
        detail: session.taskSummary || session.resultCard?.summary || "",
        meta: [session.agentDisplayName || session.agentId || "", session.updatedAt || session.lastActive || ""]
          .filter(Boolean)
          .join(" · "),
        highlight: catalogSearch.debouncedQueryText,
        onOpen: () => openSession(session.id),
      })),
    [catalogSearch.sessions, catalogSearch.debouncedQueryText, openSession],
  );

  return (
    <>
      <VCommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        items={paletteItems}
        labels={paletteLabels}
        // `#` 会话模式：server 已过滤，空串 = 按传入顺序原样列出；
        // `>` 命令模式：用去前缀文本做本地模糊匹配。
        matchQuery={
          paletteScope.kind === "sessions" ? "" : paletteScope.kind === "commands" ? paletteScope.text : undefined
        }
        maxVisible={7}
        query={paletteQuery}
        onQueryChange={setPaletteQuery}
        data-vui="global-command-palette"
      />
      <VSessionSearchDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        query={searchQuery}
        onQueryChange={setSearchQuery}
        items={sessionItems}
        loading={catalogSearch.isLoading}
        hasMore={catalogSearch.hasMore}
        loadingMore={catalogSearch.isLoadingMore}
        onLoadMore={() => void catalogSearch.loadMore()}
        totalEstimate={catalogSearch.totalEstimate}
        labels={{
          searchPlaceholder: lang === "en" ? "Search all sessions…" : "搜索全部会话…",
          emptyTitle: lang === "en" ? "No matching sessions" : "没有匹配的会话",
          emptyHint: lang === "en" ? "Try another keyword" : "换个关键词试试",
          loadMore: lang === "en" ? "Load more" : "加载更多",
          loadingMore: lang === "en" ? "Loading…" : "加载中…",
          hint: lang === "en" ? "↑↓ select · Enter open · Esc close" : "↑↓ 选择 · Enter 打开 · Esc 关闭",
          resultSummary: (loaded: number, total: number) =>
            lang === "en" ? `Loaded ${loaded} of about ${total}` : `已加载 ${loaded} / 共约 ${total} 条`,
        }}
        data-vui="global-session-search"
      />
    </>
  );
}
