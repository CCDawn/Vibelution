import { VWorkflowCanvas } from "../../../components/vui";
import type { WorkflowLayoutInput } from "../../../components/vui/product/workflow/workflowCanvasTypes";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";
import { workflowCatalogClasses } from "./WorkflowCatalog.styles";

const demoGraph: WorkflowLayoutInput = {
  stages: [
    { stageId: "knowledge_collection", label: "知识采集", nodeIds: ["kc_search", "kc_verify"], stageTone: "done" },
    { stageId: "experiment_design", label: "实验设计", nodeIds: ["ed_design", "ed_decision"], stageTone: "active" },
    { stageId: "execution_iteration", label: "执行迭代", nodeIds: ["ei_run"], stageTone: "idle" },
  ],
  nodes: [
    {
      nodeId: "kc_search",
      stageId: "knowledge_collection",
      label: "知识检索",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "succeeded",
    },
    {
      nodeId: "kc_verify",
      stageId: "knowledge_collection",
      label: "证据核验",
      actorKind: "system",
      visualKind: "system_task",
      status: "succeeded",
    },
    {
      nodeId: "ed_design",
      stageId: "experiment_design",
      label: "实验方案",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "running",
      isRuntimeCurrent: true,
    },
    {
      nodeId: "ed_decision",
      stageId: "experiment_design",
      label: "方案决策",
      actorKind: "agent",
      visualKind: "decision",
      status: "pending",
    },
    {
      nodeId: "ei_run",
      stageId: "execution_iteration",
      label: "迭代执行",
      actorKind: "system",
      visualKind: "system_task",
      status: "pending",
    },
  ],
  edges: [
    {
      edgeId: "e1",
      fromNodeId: "kc_search",
      toNodeId: "kc_verify",
      label: "提交核验",
      gateKind: "evidence_review",
      semanticKind: "main",
      pathState: "traversed",
      labelAlwaysVisible: false,
    },
    {
      edgeId: "e2",
      fromNodeId: "kc_verify",
      toNodeId: "ed_design",
      label: "进入设计",
      gateKind: "handoff",
      semanticKind: "main",
      pathState: "active",
      labelAlwaysVisible: true,
    },
    {
      edgeId: "e3",
      fromNodeId: "ed_decision",
      toNodeId: "ei_run",
      label: "通过",
      gateKind: "human_approval",
      semanticKind: "main",
      pathState: "idle",
      labelAlwaysVisible: false,
    },
  ],
  run: {
    runId: "run-demo",
    status: "running",
    runtimeCurrentNodeIds: ["ed_design"],
  },
};

export function WorkflowCatalog() {
  return (
    <VuiPreviewSection title="Workflow">
      <VuiPreviewCard name="VWorkflowCanvas" className={workflowCatalogClasses.card}>
        <div className={workflowCatalogClasses.host}>
          <VWorkflowCanvas graph={demoGraph} height="100%" />
        </div>
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
