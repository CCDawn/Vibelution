export type ActionSceneId =
  | "not_started"
  | "awaiting_confirmation"
  | "running"
  | "recoverable"
  | "blocked"
  | "history";

export type GuardStateId = "ready" | "loading" | "scope_mismatch";
export type PreviewViewportId = "desktop" | "mobile";
export type ActionSceneTone = "neutral" | "accent" | "success" | "warning" | "danger";

export type ActionScene = {
  id: ActionSceneId;
  label: string;
  eyebrow: string;
  statusLabel: string;
  statusTone: ActionSceneTone;
  title: string;
  summary: string;
  currentNodeId: string;
  selectedNodeId: string;
  authority: string;
  footerAction?: string;
  footerActionKind?: "progress" | "navigation";
  footerIdle: string;
};

export type WorkflowNode = {
  id: string;
  title: string;
  subtitle: string;
  x: number;
  y: number;
};

export const ACTION_SCENES: ActionScene[] = [
  {
    id: "not_started",
    label: "尚未开始",
    eyebrow: "当前任务 · 实验启动",
    statusLabel: "等待启动",
    statusTone: "neutral",
    title: "选择题目并开始实验",
    summary: "当前没有正式运行快照，也没有可继续的假说任务。确认题目后，从这里创建本次实验。",
    currentNodeId: "launch",
    selectedNodeId: "launch",
    authority: "无正式快照 · 无下一任务",
    footerAction: "开始实验",
    footerActionKind: "progress",
    footerIdle: "确认题目后可开始",
  },
  {
    id: "awaiting_confirmation",
    label: "等待人工确认",
    eyebrow: "当前任务 · 结论确认",
    statusLabel: "等待你确认",
    statusTone: "warning",
    title: "第 1 轮假说结论已整理",
    summary: "系统保留了 3 条假说并登记 4 个证据缺口。确认后会自动进入资料补充。",
    currentNodeId: "review",
    selectedNodeId: "review",
    authority: "正式运行快照 · awaiting_approval",
    footerAction: "确认并继续",
    footerActionKind: "progress",
    footerIdle: "确认后自动交接下一任务",
  },
  {
    id: "running",
    label: "系统运行中",
    eyebrow: "当前任务 · 实验执行",
    statusLabel: "系统运行中",
    statusTone: "accent",
    title: "实验正在执行",
    summary: "系统已接管本轮执行，新的人工操作会造成重复运行，因此推进按钮暂时隐藏。",
    currentNodeId: "experiment",
    selectedNodeId: "experiment",
    authority: "正式运行快照 · running",
    footerIdle: "系统处理中，无需操作",
  },
  {
    id: "recoverable",
    label: "可恢复错误",
    eyebrow: "当前任务 · 资料补充",
    statusLabel: "可恢复",
    statusTone: "danger",
    title: "资料补充需要处理",
    summary: "2 个资料源暂时无法访问；已完成的 5 条证据和 checkpoint 都会保留。",
    currentNodeId: "collection",
    selectedNodeId: "collection",
    authority: "正式运行快照 · collection_recovery",
    footerAction: "重试搜集",
    footerActionKind: "progress",
    footerIdle: "只重试失败来源，不重跑整轮",
  },
  {
    id: "blocked",
    label: "不可恢复阻塞",
    eyebrow: "当前任务 · 运行阻塞",
    statusLabel: "需要外部处理",
    statusTone: "danger",
    title: "当前环境无法继续实验",
    summary: "所选执行环境不满足协议要求。该问题不能通过重复点击恢复，推进按钮保持隐藏。",
    currentNodeId: "experiment",
    selectedNodeId: "experiment",
    authority: "正式运行快照 · blocked",
    footerIdle: "解除环境阻塞后自动刷新",
  },
  {
    id: "history",
    label: "历史回顾",
    eyebrow: "历史回顾 · 只读",
    statusLabel: "只读",
    statusTone: "neutral",
    title: "研究问题 · 历史记录",
    summary: "你正在查看已经归档的研究问题；它不能覆盖当前的资料补充任务。",
    currentNodeId: "collection",
    selectedNodeId: "question",
    authority: "查看位置 · 非写操作权威",
    footerAction: "返回当前任务",
    footerActionKind: "navigation",
    footerIdle: "当前任务仍是资料补充",
  },
];

export const WORKFLOW_NODES: WorkflowNode[] = [
  { id: "question", title: "研究问题", subtitle: "SCI-002 已确认", x: 10, y: 22 },
  { id: "hypothesis", title: "候选假说", subtitle: "5 条候选", x: 36, y: 22 },
  { id: "review", title: "团队评审", subtitle: "第 1 轮", x: 64, y: 22 },
  { id: "collection", title: "资料补充", subtitle: "5/7 条证据", x: 76, y: 58 },
  { id: "launch", title: "实验启动", subtitle: "等待题目", x: 47, y: 70 },
  { id: "experiment", title: "实验执行", subtitle: "受控运行", x: 18, y: 70 },
];

export const GUARD_STATES: Array<{ id: GuardStateId; label: string; description: string }> = [
  { id: "ready", label: "数据已同步", description: "显示当前权威状态允许的动作" },
  { id: "loading", label: "切换加载中", description: "隐藏旧任务动作，等待新快照" },
  { id: "scope_mismatch", label: "范围不一致", description: "隐藏动作并要求重新同步" },
];

export const PREVIEW_VIEWPORTS: Array<{ id: PreviewViewportId; label: string; width: number }> = [
  { id: "desktop", label: "1440 桌面", width: 1440 },
  { id: "mobile", label: "390 移动", width: 390 },
];

export function actionSceneById(id: ActionSceneId): ActionScene {
  return ACTION_SCENES.find((scene) => scene.id === id) ?? ACTION_SCENES[0];
}
