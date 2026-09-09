import type { SupervisedWorktreeRun } from "../../api/types";
import { VMetricStrip, VSection } from "../../components/vui";

export function SupervisedStepResult({ run, title, summary }: {
  run: SupervisedWorktreeRun | null;
  title: string;
  summary: string;
}) {
  const decision = run?.decision;
  const cleanSummary = summary.split(/SUPERVISED_AGENT_JUDGMENT:|```|证据包：/)[0].trim();
  return (
    <VSection title={title} className="grid gap-4 p-4">
      <VMetricStrip ariaLabel="本轮评分对比" metrics={[
        { id: "baseline", label: "基线得分", value: decision?.baselineScore ?? "待评测" },
        { id: "candidate", label: "候选得分", value: decision?.candidateScore ?? "待评测" },
        { id: "delta", label: "评分变化", value: decision?.scoreDelta == null ? "待复评" : `${decision.scoreDelta >= 0 ? "+" : ""}${decision.scoreDelta}` },
        { id: "result", label: "评估状态", value: decision?.evaluationState ? ({ VALID: "有效", INVALID: "无效", ERROR: "评估失败", INCONCLUSIVE: "尚无定论" }[decision.evaluationState] ?? decision.evaluationState) : "待评估" },
      ]} />
      <p className="m-0 max-w-prose whitespace-pre-line break-words text-sm leading-7">
        {cleanSummary || "当前阶段尚未生成结论。运行后将在这里显示结果和下一步建议。"}
      </p>
      {decision?.reason && decision.reason.trim() !== cleanSummary ? <p className="m-0 max-w-prose text-sm leading-7">{decision.reason}</p> : null}
    </VSection>
  );
}
