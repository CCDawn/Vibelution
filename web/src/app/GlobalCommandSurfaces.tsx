/**
 * 全局命令面（workbench 根路由挂载，与 AppShell 并列）：全局快捷键分发 +
 * 命令面板 + 会话搜索。
 *
 * - Ctrl+K / ⌘K 唤起 VCommandPalette（命令源：壳层主导航 + 壳层动作，非 mock）；
 * - Ctrl+P / ⌘P 唤起 VSessionSearchDialog（数据源：useSessionSearchQuery，server 分页）；
 * - 快捷键基建见 web/src/shortcuts/；用户覆盖静默持久化到
 *   localStorage（vibelution.shortcuts.overrides），设置页改键 UI 属后续任务。
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
  writeStoredShortcutOverrides,
} from "../shortcuts/shortcutOverrides";
import { isAppleKeyboardPlatform } from "../shortcuts/platform";
import { useGlobalShortcuts } from "../shortcuts/useGlobalShortcuts";
import { serializeChatRouteSelection } from "../routes/chat/chatSelectionProjection";
import { useSessionSearchQuery } from "../routes/useSessionSearchQuery";
import { isWorkbenchDomainEnabled, isWorkbenchModeEnabled } from "./workbenchContract";

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
  // 用户覆盖：本轮只做静默持久化（读取+写回），改键 UI 属后续设置页任务。
  const [overrides] = useState<ShortcutOverrides>(() => readStoredShortcutOverrides());
  useEffect(() => {
    writeStoredShortcutOverrides(overrides);
  }, [overrides]);

  const effective = useMemo(() => resolveEffectiveBindings(overrides), [overrides]);
  const isApple = useMemo(() => isAppleKeyboardPlatform(), []);

  const catalogSearch = useSessionSearchQuery({
    queryText: searchQuery,
    filters: { agentId: "", teamId: "" },
    enabled: searchOpen,
  });

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
    const navItems: { to: string; label: string; keywords: string }[] = [
      ...(chatEnabled ? [{ to: "/chat", label: t("navChat"), keywords: "chat 对话 会话" }] : []),
      ...(chatEnabled
        ? [{ to: "/companions", label: t("navCompanions"), keywords: "companions 伴侣 虚拟人" }]
        : []),
      ...(supervisedEvolutionEnabled
        ? [{ to: "/supervised-evolution", label: t("navSupervisedEvolution"), keywords: "supervised 监督进化" }]
        : []),
      ...(selfEvolutionEnabled
        ? [{ to: "/self-evolution", label: t("navSelfEvolution"), keywords: "self evolution 自进化" }]
        : []),
      { to: "/teams", label: t("navTeams"), keywords: "teams 团队" },
      { to: "/kernel", label: "Kernel", keywords: "kernel 内核 任务" },
      { to: "/memory", label: t("navMemory"), keywords: "memory 记忆" },
      { to: "/agents", label: t("navAgents"), keywords: "agents 智能体 助手 prompts skills tools" },
    ];
    return [
      ...navItems.map((item) => ({
        id: `nav:${item.to}`,
        label: item.label,
        detail: lang === "en" ? "Navigation" : "导航",
        group: lang === "en" ? "Navigation" : "导航",
        keywords: item.keywords,
        onRun: () => navigate(item.to),
      })),
      {
        id: "action:open-session-search",
        label: lang === "en" ? "Search all sessions" : "搜索全部会话",
        detail: lang === "en" ? "Open the session search dialog (Ctrl+P)" : "打开会话搜索（Ctrl+P）",
        group: lang === "en" ? "Actions" : "动作",
        keywords: "search session 会话 搜索 find",
        onRun: () => setSearchOpen(true),
      },
    ];
  }, [chatEnabled, supervisedEvolutionEnabled, selfEvolutionEnabled, lang, navigate, t]);

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
        labels={{
          searchPlaceholder: lang === "en" ? "Search commands or navigation…" : "搜索命令或导航…",
          emptyTitle: lang === "en" ? "No matching commands" : "没有匹配的命令",
          hint: lang === "en" ? "↑↓ select · Enter run · Esc close" : "↑↓ 选择 · Enter 执行 · Esc 关闭",
        }}
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
