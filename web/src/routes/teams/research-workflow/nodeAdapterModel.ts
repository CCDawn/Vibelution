/**
 * Task 6: map fixed workflow nodes → inspector adapter slots.
 * Adapters describe what to mount; they do not copy stage page business logic.
 */

import type { ActorKind, ChallengeCupNodeId } from "../../../api/types/researchWorkflow";
import { CHALLENGE_CUP_NODE_IDS } from "../../../api/types/researchWorkflow";

export type NodeAdapterSlot =
  | "knowledge_ops"
  | "experiment_ops"
  | "iteration_ops"
  | "human_gate"
  | "system_run"
  | "result_package"
  | "bindings";

export type NodeAdapterSpec = {
  nodeId: ChallengeCupNodeId;
  stageId: "knowledge_collection" | "experiment_design" | "execution_iteration";
  label: string;
  labelEn: string;
  actorKind: ActorKind;
  /** Inspector body slot — one write path owner per slot family. */
  slot: NodeAdapterSlot;
  /** Primary command keys shown in inspector (not route navigations). */
  commands: string[];
  /** Legacy surface this adapter replaces as primary entry. */
  replaces: string;
};

/**
 * Commands with a LIVE business handler today. `commands` above is the
 * target-state declaration (roadmap); the inspector renders ONLY wired
 * commands (plus the `open_session` link/disabled slot), so a declared but
 * unwired command can never surface as a button that ends in
 * "尚未接入业务服务".
 */
export const WIRED_COMMANDS = ["accept_handoff", "reject_handoff", "revise"] as const;

const ADAPTERS: NodeAdapterSpec[] = [
  {
    nodeId: "source_finding",
    stageId: "knowledge_collection",
    label: "资料寻找",
    labelEn: "Source finding",
    actorKind: "agent",
    slot: "knowledge_ops",
    commands: ["start_agent_task", "open_session"],
    replaces: "researchView=knowledge_collection&collectionStage=finding",
  },
  {
    nodeId: "source_extraction",
    stageId: "knowledge_collection",
    label: "资料提炼",
    labelEn: "Source extraction",
    actorKind: "agent",
    slot: "knowledge_ops",
    commands: ["start_agent_task", "fork_evidence_remediation", "open_session"],
    replaces: "collectionStage=extraction",
  },
  {
    nodeId: "evidence_relations",
    stageId: "knowledge_collection",
    label: "证据关系",
    labelEn: "Evidence relations",
    actorKind: "agent",
    slot: "knowledge_ops",
    commands: ["open_evidence_graph", "open_session"],
    replaces: "researchView=graph",
  },
  {
    nodeId: "knowledge_ingestion",
    stageId: "knowledge_collection",
    label: "知识入库",
    labelEn: "Knowledge ingestion",
    actorKind: "agent",
    slot: "knowledge_ops",
    commands: ["start_agent_task", "open_session"],
    replaces: "researchView=ingestion",
  },
  {
    nodeId: "knowledge_handoff",
    stageId: "knowledge_collection",
    label: "知识包交接",
    labelEn: "Knowledge handoff",
    actorKind: "human",
    slot: "human_gate",
    commands: ["accept_handoff", "reject_handoff", "revise"],
    replaces: "researchView=coordination completion flow",
  },
  {
    nodeId: "hypothesis_design",
    stageId: "experiment_design",
    label: "假设设计",
    labelEn: "Hypothesis design",
    actorKind: "agent",
    slot: "experiment_ops",
    commands: ["start_agent_task", "open_session"],
    replaces: "researchView=experiment",
  },
  {
    nodeId: "protocol_design",
    stageId: "experiment_design",
    label: "协议设计",
    labelEn: "Protocol design",
    actorKind: "agent",
    slot: "experiment_ops",
    commands: ["start_agent_task", "open_session"],
    replaces: "protocol design draft",
  },
  {
    nodeId: "protocol_review",
    stageId: "experiment_design",
    label: "协议评审",
    labelEn: "Protocol review",
    actorKind: "agent",
    slot: "experiment_ops",
    commands: ["start_agent_task", "open_session"],
    replaces: "experiment_evidence_review task",
  },
  {
    nodeId: "protocol_freeze",
    stageId: "experiment_design",
    label: "协议冻结",
    labelEn: "Protocol freeze",
    actorKind: "human",
    slot: "human_gate",
    commands: ["accept_handoff", "reject_handoff"],
    replaces: "protocol freeze CTA",
  },
  {
    nodeId: "smoke_gate",
    stageId: "experiment_design",
    label: "Smoke 放行",
    labelEn: "Smoke gate",
    actorKind: "human",
    slot: "human_gate",
    commands: ["run_smoke", "accept_handoff", "reject_handoff"],
    replaces: "smoke gate panel",
  },
  {
    nodeId: "controlled_run",
    stageId: "execution_iteration",
    label: "受控运行",
    labelEn: "Controlled run",
    actorKind: "system",
    slot: "system_run",
    commands: ["start_controlled_run", "view_artifacts"],
    replaces: "formal_runner entry",
  },
  {
    nodeId: "result_evaluation",
    stageId: "execution_iteration",
    label: "结果评价",
    labelEn: "Result evaluation",
    actorKind: "agent",
    slot: "iteration_ops",
    commands: ["start_agent_task", "open_session"],
    replaces: "iteration evaluation",
  },
  {
    nodeId: "iteration_decision",
    stageId: "execution_iteration",
    label: "迭代决策",
    labelEn: "Iteration decision",
    actorKind: "agent",
    slot: "iteration_ops",
    commands: ["start_agent_task", "open_session"],
    replaces: "iteration_decision task",
  },
  {
    nodeId: "candidate_promotion",
    stageId: "execution_iteration",
    label: "候选晋升",
    labelEn: "Candidate promotion",
    actorKind: "human",
    slot: "human_gate",
    commands: ["accept_handoff", "reject_handoff"],
    replaces: "promotion human confirm",
  },
  {
    nodeId: "result_package",
    stageId: "execution_iteration",
    label: "结果打包",
    labelEn: "Result package",
    actorKind: "system",
    slot: "result_package",
    commands: ["build_package", "view_artifacts"],
    replaces: "result package",
  },
];

const BY_ID = Object.fromEntries(ADAPTERS.map((a) => [a.nodeId, a])) as Record<
  ChallengeCupNodeId,
  NodeAdapterSpec
>;

export function listNodeAdapters(): NodeAdapterSpec[] {
  return ADAPTERS.slice();
}

export function getNodeAdapter(nodeId: string | null | undefined): NodeAdapterSpec | null {
  if (!nodeId) return null;
  if (!(CHALLENGE_CUP_NODE_IDS as readonly string[]).includes(nodeId)) return null;
  return BY_ID[nodeId as ChallengeCupNodeId] ?? null;
}

export function adaptersForStage(
  stageId: NodeAdapterSpec["stageId"],
): NodeAdapterSpec[] {
  return ADAPTERS.filter((a) => a.stageId === stageId);
}

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
    fork_evidence_remediation: "创建证据补救运行",
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
    fork_evidence_remediation: "Create evidence remediation run",
  };
  return (lang === "zh" ? zh : en)[command] || command;
}
