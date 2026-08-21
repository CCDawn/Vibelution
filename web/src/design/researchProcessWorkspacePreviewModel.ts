export type PreviewSceneId =
  | "generation"
  | "candidate_approval"
  | "selection"
  | "review_processing"
  | "review_approval"
  | "collection"
  | "recovery"
  | "blocked"
  | "archive";

export type PreviewViewportId = "desktop" | "tablet" | "compact";
export type PreviewTone = "neutral" | "accent" | "success" | "warning" | "danger";
export type PreviewNodeTone = "done" | "current" | "next" | "idle" | "blocked";

export type PreviewScene = {
  id: PreviewSceneId;
  label: string;
  phase: string;
  progress: string;
  currentNodeId: string;
  statusLabel: string;
  statusTone: PreviewTone;
  title: string;
  summary: string;
  activity?: string;
  nextExpectation: string;
  primaryAction?: string;
  secondaryAction?: string;
  disabledAction?: string;
  disabledReason?: string;
  archive?: boolean;
};

export type PreviewNode = {
  id: string;
  phaseId: string;
  title: string;
  subtitle: string;
  x: number;
  y: number;
};

export type PreviewPhase = {
  id: string;
  index: string;
  title: string;
  description: string;
};

export const PREVIEW_VIEWPORTS: Array<{ id: PreviewViewportId; label: string; width: number }> = [
  { id: "desktop", label: "1440 桌面", width: 1440 },
  { id: "tablet", label: "1024 中屏", width: 1024 },
  { id: "compact", label: "760 窄屏", width: 760 },
];

export const PREVIEW_PHASES: PreviewPhase[] = [
  { id: "question", index: "01", title: "问题定义", description: "明确题目与研究边界" },
  { id: "hypothesis", index: "02", title: "假说先行", description: "形成、选择并评审假说" },
  { id: "evidence", index: "03", title: "证据补充", description: "围绕缺口搜集资料" },
  { id: "protocol", index: "04", title: "实验与交付", description: "协议、执行与成果归档" },
];

export const PREVIEW_NODES: PreviewNode[] = [
  { id: "question", phaseId: "question", title: "研究问题", subtitle: "SCI-004 已确认", x: 7, y: 18 },
  { id: "hf_generation", phaseId: "hypothesis", title: "候选形成", subtitle: "团队自动讨论", x: 31, y: 18 },
  { id: "hf_selection", phaseId: "hypothesis", title: "假说选择", subtitle: "选择进入评审的候选", x: 56, y: 18 },
  { id: "hf_meeting", phaseId: "hypothesis", title: "团队评审", subtitle: "整理结论与证据缺口", x: 78, y: 47 },
  { id: "hf_collection", phaseId: "evidence", title: "资料补充", subtitle: "自动搜集并交接", x: 53, y: 70 },
  { id: "protocol", phaseId: "protocol", title: "协议设计", subtitle: "形成可执行方案", x: 27, y: 70 },
  { id: "delivery", phaseId: "protocol", title: "成果归档", subtitle: "审计与交付", x: 7, y: 70 },
];

export const PREVIEW_SCENES: PreviewScene[] = [
  {
    id: "generation", label: "候选生成中", phase: "假说先行", progress: "第 1 步，共 4 步",
    currentNodeId: "hf_generation", statusLabel: "系统处理中", statusTone: "accent",
    title: "团队正在形成候选假说",
    summary: "系统正在汇总不同角色的观点，并把重复内容合并成可比较的候选清单。你现在无需操作。",
    activity: "已收到 3/4 位成员的观点，正在等待方法论评审员",
    nextExpectation: "完成后会自动进入“确认候选清单”，并在这里通知你。",
  },
  {
    id: "candidate_approval", label: "候选待确认", phase: "假说先行", progress: "第 1 步，共 4 步",
    currentNodeId: "hf_generation", statusLabel: "等待你确认", statusTone: "warning",
    title: "候选清单已整理完成",
    summary: "系统保留了 5 条差异明确、可被证据验证的候选。确认后会自动进入假说选择。",
    nextExpectation: "确认只会冻结本轮候选，不会直接进入实验执行。",
    primaryAction: "确认候选清单", secondaryAction: "退回重新整理",
  },
  {
    id: "selection", label: "假说选择", phase: "假说先行", progress: "第 2 步，共 4 步",
    currentNodeId: "hf_selection", statusLabel: "需要你选择", statusTone: "warning",
    title: "选择要进入第 1 轮评审的假说",
    summary: "已选择 3 条候选。系统会围绕它们发起一次评审讨论，并自动整理证据缺口。",
    nextExpectation: "提交后自动开启评审，无需再返回画布寻找入口。",
    primaryAction: "记录选择并开启评审", disabledAction: "未选择候选",
    disabledReason: "至少选择 1 条假说后才能开启评审",
  },
  {
    id: "review_processing", label: "评审整理中", phase: "假说先行", progress: "第 3 步，共 4 步 · 第 1 轮",
    currentNodeId: "hf_meeting", statusLabel: "系统处理中", statusTone: "accent",
    title: "第 1 轮评审正在整理",
    summary: "系统正在把团队讨论整理成“保留结论、反对意见、证据缺口”三部分。这就是原来的“正在生成纪要”。",
    activity: "讨论已结束，正在核对结论是否引用了本轮真实发言",
    nextExpectation: "整理完成后，你会在同一位置看到可确认的本轮结论。",
  },
  {
    id: "review_approval", label: "评审待确认", phase: "假说先行", progress: "第 3 步，共 4 步 · 第 1 轮",
    currentNodeId: "hf_meeting", statusLabel: "等待你确认", statusTone: "warning",
    title: "第 1 轮结论已整理",
    summary: "3 条假说暂时保留，识别出 4 个证据缺口。确认后系统会自动创建资料补充任务并交接。",
    nextExpectation: "确认会结束本轮评审，但不会结束整个研究流程。",
    primaryAction: "确认并结束本轮", secondaryAction: "退回重新整理",
  },
  {
    id: "collection", label: "资料补充中", phase: "证据补充", progress: "第 4 步，共 4 步",
    currentNodeId: "hf_collection", statusLabel: "自动搜集中", statusTone: "accent",
    title: "正在补充评审提出的证据缺口",
    summary: "系统已拆成 4 个检索任务，优先查找可追溯的论文、数据集和反例。无需手动启动团队讨论。",
    activity: "2/4 个检索任务完成 · 已登记 7 条可追溯证据",
    nextExpectation: "全部完成后自动交接回假说阶段，并显示下一项可操作任务。",
  },
  {
    id: "recovery", label: "可恢复失败", phase: "证据补充", progress: "第 4 步，共 4 步",
    currentNodeId: "hf_collection", statusLabel: "需要恢复", statusTone: "danger",
    title: "2 个资料源暂时无法访问",
    summary: "已完成的 5 条证据不会丢失。重试只处理失败来源，不会重复整轮搜集。",
    nextExpectation: "恢复成功后系统会继续自动交接。",
    primaryAction: "重试失败来源", secondaryAction: "查看已保留结果",
  },
  {
    id: "blocked", label: "人工裁决", phase: "假说先行", progress: "预算已用完 · 第 1 轮",
    currentNodeId: "hf_meeting", statusLabel: "等待人工裁决", statusTone: "warning",
    title: "本轮无法自动收敛",
    summary: "正反证据仍冲突，自动评审预算已经用完。请选择保留、淘汰或追加一次定向搜集。",
    nextExpectation: "裁决会被记录到科研档案，后续节点继续沿用该结论。",
    primaryAction: "开始人工裁决", secondaryAction: "查看冲突证据",
  },
  {
    id: "archive", label: "科研档案", phase: "科研档案", progress: "SCI-004 · 只读记录",
    currentNodeId: "hf_meeting", statusLabel: "已归档", statusTone: "success",
    title: "SCI-004 科研档案",
    summary: "集中查看题目、假说版本、评审轮次、证据来源与交接记录。档案不承担当前任务写操作。",
    nextExpectation: "返回当前任务后继续第 1 轮评审确认。",
    primaryAction: "返回当前任务", archive: true,
  },
];

export function sceneById(id: PreviewSceneId): PreviewScene {
  return PREVIEW_SCENES.find((scene) => scene.id === id) ?? PREVIEW_SCENES[0];
}

export function nodeTone(nodeId: string, scene: PreviewScene): PreviewNodeTone {
  const order = PREVIEW_NODES.map((node) => node.id);
  const currentIndex = order.indexOf(scene.currentNodeId);
  const nodeIndex = order.indexOf(nodeId);
  if (nodeId === scene.currentNodeId) return scene.id === "recovery" || scene.id === "blocked" ? "blocked" : "current";
  if (nodeIndex < currentIndex) return "done";
  if (nodeIndex === currentIndex + 1) return "next";
  return "idle";
}
