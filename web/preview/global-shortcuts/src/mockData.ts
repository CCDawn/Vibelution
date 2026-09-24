/**
 * 确定性 mock 数据 —— 预览专用，无生产接口、无随机数。
 */

import type { VCommandPaletteItem } from "../../../src/components/vui/product/workbench-shell/VCommandPalette";
import type { VSessionSearchDialogItem } from "../../../src/components/vui/product/workbench-shell/VSessionSearchDialog";

import type { ShortcutCommandId } from "./shortcuts/commands";

/** mock 会话目录（「服务端」返回形状；客户端子串过滤模拟 server q）。 */
export const MOCK_SESSIONS: readonly {
  id: string;
  title: string;
  detail: string;
  meta: string;
}[] = [
  { id: "s01", title: "会话渲染隔离测试修复", detail: "讨论 stream isolation 的测量与路径缺陷", meta: "Atlas · 运行中 · 3 分钟前" },
  { id: "s02", title: "命令面板全局挂载方案", detail: "VCommandPalette 从 Teams 局部挂载改为全局", meta: "Nova · 运行中 · 12 分钟前" },
  { id: "s03", title: "知识库导入清洗管线", detail: "Markdown 导入的来源隔离与删除重建语义", meta: "Orion · 已暂停 · 1 小时前" },
  { id: "s04", title: "Launcher 无控制台红线复查", detail: "后台子进程 spawn 路径的 CREATE_NO_WINDOW 审计", meta: "Vega · 已完成 · 2 小时前" },
  { id: "s05", title: "会话搜索分页接口对齐", detail: "server q 与 totalEstimate 的契约确认", meta: "Atlas · 运行中 · 3 小时前" },
  { id: "s06", title: "密度切换回归清单", detail: "紧凑/舒适两档下的布局回归点", meta: "Lyra · 已完成 · 5 小时前" },
  { id: "s07", title: "主题令牌迁移盘点", detail: "tokens.css 与 vui-provider-theme 的变量归属", meta: "Nova · 已完成 · 昨天" },
  { id: "s08", title: "快捷键冲突检测评审", detail: "保留键黑名单与物理等价归一口径", meta: "Orion · 运行中 · 昨天" },
  { id: "s09", title: "侧栏持久化布局记忆", detail: "WORKBENCH_LAYOUT_IDS 与 pane persistence", meta: "Vega · 已暂停 · 昨天" },
  { id: "s10", title: "会话转录投影一致性", detail: "Journal 与 SSE 的唯一权威边界", meta: "Lyra · 已完成 · 前天" },
  { id: "s11", title: "Composer follow-up 队列", detail: "追问队列的到达顺序与展示", meta: "Atlas · 已完成 · 前天" },
  { id: "s12", title: "Workbench 空态设计走查", detail: "VStateSurface 的空态/加载态文案", meta: "Nova · 已完成 · 3 天前" },
];

/** 会话搜索命中：title/detail 子串匹配，输出高亮条目。 */
export function filterMockSessions(query: string): VSessionSearchDialogItem[] {
  const needle = query.trim().toLowerCase();
  const hits = MOCK_SESSIONS.filter((session) => {
    if (!needle) return true;
    return (
      session.title.toLowerCase().includes(needle) ||
      session.detail.toLowerCase().includes(needle)
    );
  });
  return hits.map((session) => ({
    id: session.id,
    title: session.title,
    detail: session.detail,
    meta: session.meta,
    highlight: needle || undefined,
    active: false,
    onOpen: () => undefined,
  }));
}

/** 命令面板条目工厂：onRun 由预览应用注入。 */
export function buildMockPaletteItems(handlers: {
  onNavigate: (target: string) => void;
  onCycleDensity: () => void;
  onSwitchTheme: () => void;
  onOpenSessionSearch: () => void;
  onClearLog: () => void;
}): VCommandPaletteItem[] {
  return [
    {
      id: "nav-teams",
      label: "打开团队工作台",
      detail: "导航 · 演示动作，只记日志",
      group: "导航",
      keywords: "teams 团队 导航 go",
      onRun: () => handlers.onNavigate("团队工作台"),
    },
    {
      id: "nav-knowledge",
      label: "打开知识库",
      detail: "导航 · 演示动作，只记日志",
      group: "导航",
      keywords: "knowledge 知识库 导航",
      onRun: () => handlers.onNavigate("知识库"),
    },
    {
      id: "nav-tasks",
      label: "打开任务面板",
      detail: "导航 · 演示动作，只记日志",
      group: "导航",
      keywords: "tasks 任务 导航",
      onRun: () => handlers.onNavigate("任务面板"),
    },
    {
      id: "action-density",
      label: "切换信息密度",
      detail: "视图 · 与全局快捷键同一命令",
      group: "动作",
      keywords: "density 密度 紧凑 舒适",
      onRun: handlers.onCycleDensity,
    },
    {
      id: "action-theme",
      label: "切换明暗主题",
      detail: "视图 · 与全局快捷键同一命令",
      group: "动作",
      keywords: "theme 主题 明 暗",
      onRun: handlers.onSwitchTheme,
    },
    {
      id: "action-search",
      label: "搜索全部会话",
      detail: "跨面板联动：从命令面板打开会话搜索",
      group: "动作",
      keywords: "search 会话 搜索 session",
      onRun: handlers.onOpenSessionSearch,
    },
    {
      id: "action-clear-log",
      label: "清空操作日志",
      detail: "预览 · 清空右侧演示日志",
      group: "动作",
      keywords: "clear log 日志 清空",
      onRun: handlers.onClearLog,
    },
  ];
}

/** 命令面板的 i18n 标签（预览固定中文）。 */
export const PALETTE_LABELS = {
  searchPlaceholder: "搜索命令或导航…",
  emptyTitle: "没有匹配的命令",
  hint: "↑↓ 选择 · Enter 执行 · Esc 关闭",
};

/** 会话搜索的 i18n 标签（预览固定中文）。 */
export const SESSION_SEARCH_LABELS = {
  searchPlaceholder: "搜索全部会话…",
  emptyTitle: "没有匹配的会话",
  emptyHint: "换个关键词试试；搜索词会高亮显示",
  loadMore: "加载更多",
  loadingMore: "加载中…",
  hint: "↑↓ 选择 · Enter 打开 · Esc 关闭",
  resultSummary: (loaded: number, total: number) => `已加载 ${loaded} / 共约 ${total} 条`,
};

/** URL 参数驱动的确定性初始态（截图与分享用）。 */
export type PreviewBootState =
  | "default"
  | "palette"
  | "palette-empty"
  | "search"
  | "search-filtered"
  | "search-empty"
  | "conflict"
  | "recording"
  | "cleared";

export function readPreviewBootState(): PreviewBootState {
  const value = new URLSearchParams(window.location.search).get("state");
  const known: PreviewBootState[] = [
    "palette",
    "palette-empty",
    "search",
    "search-filtered",
    "search-empty",
    "conflict",
    "recording",
    "cleared",
  ];
  return known.includes(value as PreviewBootState) ? (value as PreviewBootState) : "default";
}

/** 冲突演示用的固定尝试：把命令面板的默认键绑到会话搜索。 */
export const CONFLICT_DEMO = {
  commandId: "openSessionSearch" as ShortcutCommandId,
  binding: "CmdOrCtrl+k",
};

/** 空态演示的固定搜索词（保证零命中）。 */
export const SEARCH_EMPTY_QUERY = "不存在的会话xyz";

/** 过滤态演示的固定搜索词（命中若干条）。 */
export const SEARCH_FILTERED_QUERY = "会话";
