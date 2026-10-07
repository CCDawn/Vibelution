export const FINANCE_WORKSPACE_GROUPS = [
  { id: "research", zh: "研究", en: "Research", areas: [
    { id: "workspace", zh: "股票研究", en: "Stock research" },
    { id: "general", zh: "主题研究", en: "Topic research" },
    { id: "team", zh: "分析员协作", en: "Analysts" },
    { id: "tasks", zh: "研究任务", en: "Tasks" },
    { id: "dashboard", zh: "总览", en: "Overview" },
  ] },
  { id: "market", zh: "行情", en: "Market", areas: [
    { id: "watchlist", zh: "自选行情", en: "Watchlist" },
    { id: "screen", zh: "股票筛选", en: "Screener" },
  ] },
  { id: "assets", zh: "资产", en: "Assets", areas: [
    { id: "account", zh: "模拟账户", en: "Paper account" },
    { id: "portfolio", zh: "组合研究", en: "Portfolio" },
    { id: "review", zh: "交易复盘", en: "Review" },
  ] },
  { id: "library", zh: "资料", en: "Library", areas: [
    { id: "reports", zh: "报告中心", en: "Reports" },
    { id: "memory", zh: "研究记忆", en: "Memory" },
    { id: "skills", zh: "技能中心", en: "Skills" },
    { id: "learning", zh: "学习中心", en: "Learning" },
  ] },
] as const;

export function financeWorkspaceGroup(area: string) {
  return FINANCE_WORKSPACE_GROUPS.find(group => group.areas.some(item => item.id === area)) ?? FINANCE_WORKSPACE_GROUPS[0];
}
