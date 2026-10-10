export type PreviewScene = "running" | "completed" | "error" | "empty";
export type PreviewView = "team" | "chat";

export const sceneLabels: Record<PreviewScene, string> = {
  running: "讨论中", completed: "已完成", error: "异常", empty: "空状态",
};

export const members = [
  { id: "planner", name: "规划师", role: "需求规划", initials: "规", color: "bg-blue-50 text-blue-700", model: "gpt-6.1-sol" },
  { id: "developer-a", name: "开发工程师 A", role: "编码实现", initials: "A", color: "bg-violet-50 text-violet-700", model: "gpt-6.1-sol" },
  { id: "developer-b", name: "开发工程师 B", role: "并行实现", initials: "B", color: "bg-amber-50 text-amber-800", model: "gpt-6.1-sol" },
  { id: "reviewer", name: "评审员", role: "独立评审", initials: "审", color: "bg-emerald-50 text-emerald-700", model: "gpt-6.1-sol" },
] as const;

export type PreviewMember = typeof members[number];

export function getMember(id: string) {
  return members.find((member) => member.id === id) ?? members[0];
}

export type PreviewMessage = { id: string; author: string; time: string; body: string; round: number; process?: boolean; file?: string };

export const messages: PreviewMessage[] = [
  { id: "m1", author: "user", time: "10:24", round: 1, body: "优化登录按钮的反馈。点击后显示“正在登录”，失败后允许重试，避免重复提交。" },
  { id: "m2", author: "planner", time: "10:25", round: 1, body: "拆成两项：@开发工程师 A 处理加载状态与重复提交；@开发工程师 B 处理失败提示和重试。@评审员 最后检查完整流程。" },
  { id: "m3", author: "developer-a", time: "10:31", round: 1, body: "按钮加载时显示“正在登录”，同时禁用再次提交。键盘回车也经过同一个提交入口。", process: true, file: "LoginButton.tsx" },
  { id: "m4", author: "developer-b", time: "10:33", round: 1, body: "失败提示放在输入框附近，保留已填内容。请求结束后恢复按钮，用户可以直接重试。", process: true, file: "LoginForm.tsx" },
  { id: "m5", author: "user", time: "10:36", round: 2, body: "错误提示不要跳出弹窗，保持在表单里。请检查窄屏。" },
  { id: "m6", author: "developer-b", time: "10:38", round: 2, body: "已调整为行内提示。390px 下输入框与按钮完整显示，错误出现时不会挡住操作。" },
  { id: "m6b", author: "developer-b", time: "10:39", round: 2, body: "补充：再次提交时清除旧错误，输入内容保持不变。" },
  { id: "m7", author: "reviewer", time: "10:41", round: 2, body: "加载、失败重试和窄屏已检查。还在核对快速双击与回车同时触发的情况。", process: true },
];

export const taskRows = [
  { id: "loading", title: "加载反馈与重复提交", owner: "developer-a", status: "已完成", note: "按钮、回车共用提交入口" },
  { id: "retry", title: "失败提示与重试", owner: "developer-b", status: "已完成", note: "保留输入，错误就地提示" },
  { id: "review", title: "完整流程与窄屏评审", owner: "reviewer", status: "评审中", note: "核对快速双击与键盘提交" },
] as const;
