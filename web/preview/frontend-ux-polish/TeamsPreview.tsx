import { useState } from "react";
import {
  VButton, VCanvasWorkbenchPage, VDenseOpsPage, VPanelHeader, VStatusChip,
  type WorkflowLayoutInput,
} from "../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import { ResearchRunLaunchPanel } from "../../src/routes/teams/research-workflow/ResearchRunLaunchPanel";
import { ResearchWorkflowCanvasPane } from "../../src/routes/teams/research-workflow/ResearchWorkflowCanvasPane";
import { clearResearchRunLaunchDraft } from "../../src/routes/teams/research-workflow/researchRunLaunchDraft";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../src/api/types/researchWorkflow";
import { type ResearchWorkflowLaunchOptionsResponse } from "../../src/api/researchWorkflow";

export const PREVIEW_TEAM_ID = "preview-frontend-ux-polish";
export const launchFixture: ResearchWorkflowLaunchOptionsResponse = {
  workflowId: CHALLENGE_CUP_WORKFLOW_ID,
  teamId: PREVIEW_TEAM_ID,
  questions: [
    { questionId: "SCI-001", title: "人工智能如何帮助发现可验证的新假说？", scope: "人工智能", domain: "artificial_intelligence" },
    { questionId: "SCI-002", title: "能否建立可靠的复杂系统预测方法？", scope: "数学", domain: "mathematical_sciences" },
    { questionId: "SCI-003", title: "What patterns connect prime numbers and the Riemann hypothesis?", scope: "数学", domain: "mathematical_sciences" },
  ].map((question) => ({ ...question, catalogId: "preview", reviewRunId: "", artifactSha256: "", launchable: true, checkpoint: null })),
  experiments: [],
};

const graph: WorkflowLayoutInput = {
  stages: [{ stageId: "hypothesis", label: "假说研究", nodeIds: ["generate", "review", "converge"] }],
  nodes: [
    { nodeId: "generate", stageId: "hypothesis", label: "生成候选假说", actorKind: "agent", visualKind: "agent_task", status: "ready", description: "模拟：待生成候选假说" },
    { nodeId: "review", stageId: "hypothesis", label: "评审与证据检查", actorKind: "agent", visualKind: "agent_task", status: "pending" },
    { nodeId: "converge", stageId: "hypothesis", label: "收敛与人工确认", actorKind: "human", visualKind: "human_gate", status: "pending" },
  ],
  edges: [
    { edgeId: "generation-review", fromNodeId: "generate", toNodeId: "review", label: "候选假说", gateKind: "auto", semanticKind: "main", pathState: "idle", labelAlwaysVisible: false },
    { edgeId: "review-converge", fromNodeId: "review", toNodeId: "converge", label: "评审结果", gateKind: "human", semanticKind: "human_gate", pathState: "idle", labelAlwaysVisible: true },
  ],
};

export function TeamsPreview() {
  const [questionId, setQuestionId] = useState("");
  const [showCanvas, setShowCanvas] = useState(false);
  const [nodeId, setNodeId] = useState<string | null>("generate");
  const [resetCount, setResetCount] = useState(0);
  const question = launchFixture.questions.find((item) => item.questionId === questionId);
  const node = graph.nodes.find((item) => item.nodeId === nodeId);
  const start = (id: string) => { setQuestionId(id); setNodeId("generate"); setShowCanvas(true); };
  const context = <div className="flex min-w-0 items-center gap-2"><strong>研究团队</strong><VStatusChip tone="neutral">模拟数据</VStatusChip></div>;

  if (showCanvas) return (
    <VCanvasWorkbenchPage
      ariaLabel="研究流程预览"
      title="研究团队"
      hideHeader
      layoutId={WORKBENCH_LAYOUT_IDS.researchFlow}
      responsive={{ enabled: true, inspector: { label: "节点详情" } }}
      toolbar={<div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-2">{context}<VButton variant="secondary" onClick={() => setShowCanvas(false)}>重新选题</VButton></div>}
      canvas={<ResearchWorkflowCanvasPane graph={graph} selectedNodeId={nodeId} runtimeCurrentNodeIds={[]} error={null} onSelectNode={setNodeId} />}
      inspector={<div className="teams-inspector"><VPanelHeader title={node?.label ?? "选择节点"} />
        <p>{question?.questionId} · {question?.title}</p>
        <VStatusChip tone="neutral">尚未执行 · 仅布局预览</VStatusChip>
        <dl><dt>所属团队</dt><dd>研究团队</dd><dt>当前节点</dt><dd>{node?.label ?? "未选择"}</dd></dl>
        <p>正式接入后，这里继续显示现有流程、对话和证据。当前点击不创建运行、不发送模型请求。</p>
      </div>}
    />
  );

  return <VDenseOpsPage ariaLabel="团队选题预览" title="研究团队" hideHeader toolbarSlot={<div className="flex items-center justify-between p-3">{context}</div>}>
    <div className="teams-launch-main">
      <div className="teams-launch-form">
        <div className="teams-launch-context"><VStatusChip tone="neutral">主区选题</VStatusChip><span className="text-vui-fg-secondary text-vui-xs">未选题时直接搜索与开始，不再留下空画布。</span></div>
        <ResearchRunLaunchPanel key={resetCount} teamId={PREVIEW_TEAM_ID} busy={false} initialQuestionId={questionId}
          onStartHypothesis={start} onSubmit={async (input) => { start(input.questionId); }}
          onCancel={() => { clearResearchRunLaunchDraft(PREVIEW_TEAM_ID); setQuestionId(""); setResetCount((value) => value + 1); }} />
      </div>
    </div>
  </VDenseOpsPage>;
}
