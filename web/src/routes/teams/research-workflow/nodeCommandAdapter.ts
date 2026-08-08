/**
 * Frontend node-command registry for the research workflow inspector.
 *
 * Rendering is driven by the BACKEND capability list (node detail `commands`):
 * only commands the backend reports as available get an enabled button; the
 * frontend never invents a handler or fakes success. This module maps each
 * command to its real execution path (or an explicit unavailable reason).
 */
import {
  postResearchWorkflowNodeCommand,
  resolveResearchWorkflowHumanTask,
} from "../../../api/researchWorkflow";
import type { NodeCommandCapability } from "../../../api/types/researchWorkflow";

export type NodeCommandContext = {
  runId: string;
  nodeId: string;
  teamId: string;
  /** Node-scoped pending HumanTask id (never the global first task). */
  pendingHumanTaskId?: string;
};

export type NodeCommandResult = {
  command: string;
  message: string;
  raw?: Record<string, unknown>;
};

/** Commands whose backend handler exists and can be invoked. */
const EXECUTABLE = new Set([
  "start_agent_task",
  "run_smoke",
  "start_controlled_run",
  "view_artifacts",
  "rebind_node",
  "accept_handoff",
  "reject_handoff",
  "revise",
]);

/** Commands with no backend service: must render disabled, never clickable. */
export const EXPLICITLY_UNAVAILABLE = new Map([
  ["build_package", "结果包服务尚未接入后端"],
  ["open_evidence_graph", "证据图服务尚未接入后端"],
]);

export function commandLabel(command: string, lang: "zh" | "en" = "zh"): string {
  const zh: Record<string, string> = {
    start_agent_task: "启动 Agent 任务",
    open_session: "打开精确会话",
    open_evidence_graph: "打开证据图",
    accept_handoff: "接受交接",
    reject_handoff: "拒绝交接",
    revise: "要求修订",
    run_smoke: "运行 Smoke",
    start_controlled_run: "启动受控运行",
    view_artifacts: "查看产物",
    build_package: "生成结果包",
    rebind_node: "受控换绑",
  };
  const en: Record<string, string> = {
    start_agent_task: "Start agent task",
    open_session: "Open session anchor",
    open_evidence_graph: "Open evidence graph",
    accept_handoff: "Accept handoff",
    reject_handoff: "Reject handoff",
    revise: "Request revision",
    run_smoke: "Run smoke",
    start_controlled_run: "Start controlled run",
    view_artifacts: "View artifacts",
    build_package: "Build result package",
    rebind_node: "Controlled rebind",
  };
  return (lang === "zh" ? zh : en)[command] || command;
}

/**
 * Disable reason for a capability: backend-declared reason wins; commands the
 * frontend knows have no handler are always disabled even if the backend
 * were to list them.
 */
export function disableReasonFor(capability: NodeCommandCapability): string {
  if (!capability.available) {
    return capability.reason || "该操作当前不可用";
  }
  if (EXPLICITLY_UNAVAILABLE.has(capability.command)) {
    return EXPLICITLY_UNAVAILABLE.get(capability.command) ?? "该操作当前不可用";
  }
  return "";
}

/**
 * Executes one command through the real backend adapter. Throws with the
 * backend message on failure (the caller surfaces the VUI error state).
 */
export async function executeNodeCommand(
  context: NodeCommandContext,
  capability: NodeCommandCapability,
): Promise<NodeCommandResult> {
  const { runId, nodeId } = context;
  const command = capability.command;

  if (!capability.available) {
    throw new Error(capability.reason || "该操作当前不可用");
  }
  if (!EXECUTABLE.has(command)) {
    throw new Error(`命令 ${command} 尚未接入业务服务`);
  }

  if (command === "accept_handoff" || command === "reject_handoff" || command === "revise") {
    const accept = command === "accept_handoff";
    const task = await resolveResearchWorkflowHumanTask(runId, contextPendingTaskId(context), {
      accept,
      resolvedBy: "operator",
    });
    return {
      command,
      message: accept ? "已接受交接" : "已拒绝交接",
      raw: { task },
    };
  }

  const raw = await postResearchWorkflowNodeCommand(runId, nodeId, command, {});
  return {
    command,
    message: `${commandLabel(command)}已提交`,
    raw,
  };
}

/** Pending HumanTask id for the CURRENT node (never the global first). */
export function contextPendingTaskId(context: NodeCommandContext): string {
  // The workspace supplies the node-scoped pending task id via context.
  if (!("pendingHumanTaskId" in context) || !context.pendingHumanTaskId) {
    throw new Error("当前节点没有待处理的人工任务");
  }
  return context.pendingHumanTaskId;
}

export function isHumanGateCommand(command: string): boolean {
  return command === "accept_handoff" || command === "reject_handoff" || command === "revise";
}
