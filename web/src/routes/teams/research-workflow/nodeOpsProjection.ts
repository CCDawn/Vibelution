/**
 * Task 6: project node-local ops facts from workflow run snapshot.
 * One read path — does not invent unlock from "has sources/plans".
 */

import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import { getNodeAdapter } from "./nodeAdapterModel";

export type NodeOpsFact = {
  label: string;
  value: string;
  tone?: "neutral" | "ready" | "blocked" | "done";
};

export type NodeOpsProjection = {
  nodeId: string;
  title: string;
  facts: NodeOpsFact[];
  primaryCommands: string[];
  blockedReason?: string;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function projectNodeOps(options: {
  nodeId: string | null | undefined;
  run: WorkflowRunRecord | null | undefined;
  runtimeCurrentNodeIds?: string[];
}): NodeOpsProjection | null {
  const nodeId = String(options.nodeId || "").trim();
  const adapter = getNodeAdapter(nodeId);
  if (!adapter) return null;

  const run = options.run;
  const lg = asRecord(run?.langGraph);
  const completed = new Set(
    Array.isArray(lg.completedNodeIds) ? lg.completedNodeIds.map(String) : [],
  );
  const runtimeIds = options.runtimeCurrentNodeIds ?? run?.runtimeCurrentNodeIds ?? [];
  const isCurrent = runtimeIds.includes(nodeId);
  const isDone = completed.has(nodeId);

  const artifacts = asRecord(lg.artifacts);
  const knowledgeOk = Boolean(lg.knowledgePackageAccepted);
  const protocolOk = Boolean(lg.frozenProtocolAccepted);
  const smokeOk = Boolean(lg.smokeAccepted);

  const facts: NodeOpsFact[] = [
    {
      label: "状态",
      value: isCurrent ? "运行当前" : isDone ? "已完成" : "待命",
      tone: isCurrent ? "ready" : isDone ? "done" : "neutral",
    },
  ];

  let blockedReason: string | undefined;

  if (adapter.stageId === "experiment_design" || nodeId === "hypothesis_design") {
    facts.push({
      label: "知识包",
      value: knowledgeOk ? "已接受" : "未接受",
      tone: knowledgeOk ? "done" : "blocked",
    });
    if (!knowledgeOk && (nodeId === "hypothesis_design" || adapter.stageId === "experiment_design")) {
      if (nodeId === "hypothesis_design" || !["source_finding", "source_extraction", "evidence_relations", "knowledge_ingestion", "knowledge_handoff"].includes(nodeId)) {
        if (nodeId === "hypothesis_design") {
          blockedReason = "需要 accepted Knowledge Package（不能仅因有资料解锁）";
        }
      }
    }
  }

  if (nodeId === "hypothesis_design" && !knowledgeOk) {
    blockedReason = "需要 accepted Knowledge Package（不能仅因有资料解锁）";
  }

  if (nodeId === "controlled_run") {
    facts.push({
      label: "冻结协议",
      value: protocolOk ? "已冻结" : "未冻结",
      tone: protocolOk ? "done" : "blocked",
    });
    facts.push({
      label: "试跑",
      value: smokeOk ? "已放行" : "未放行",
      tone: smokeOk ? "done" : "blocked",
    });
    if (!protocolOk || !smokeOk) {
      blockedReason = "需要冻结协议和试跑人工放行（不能仅因有实验计划解锁）";
    }
  }

  if (adapter.slot === "human_gate") {
    facts.push({
      label: "人工门",
      value: isCurrent ? "等待处理" : isDone ? "已处理" : "未到达",
      tone: isCurrent ? "ready" : isDone ? "done" : "neutral",
    });
  }

  if (Object.keys(artifacts).length > 0) {
    facts.push({
      label: "产物数",
      value: String(Object.keys(artifacts).length),
      tone: "neutral",
    });
  }

  const snaps = Array.isArray(run?.bindingSnapshots) ? run!.bindingSnapshots! : [];
  const snap = snaps.find((item) => String(item.nodeId) === nodeId);
  if (snap) {
    facts.push({
      label: "绑定",
      value: String(snap.agentId || "未绑定"),
      tone: snap.agentId ? "done" : "blocked",
    });
  }

  return {
    nodeId,
    title: adapter.label,
    facts,
    primaryCommands: adapter.commands,
    blockedReason,
  };
}
