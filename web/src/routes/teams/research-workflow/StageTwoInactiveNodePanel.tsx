/**
 * Read-only explanation surface for a grayed stage-two canvas node.
 *
 * Stage two never auto-activates (allowPhaseTwoAdvance=false), so selecting one
 * of the ten inactive protocol/experiment nodes explains the per-question
 * activation semantics instead of rendering runtime controls. Pure display:
 * no command, no navigation, no activation entry point.
 */
import { VStatusChip, VSurface } from "../../../components/vui";

export const STAGE_TWO_INACTIVE_PANEL_TEST_ID = "stage-two-inactive-node-panel";

export function StageTwoInactiveNodePanel({
  nodeId,
  nodeLabel,
  lang = "zh",
}: {
  nodeId: string;
  nodeLabel?: string;
  lang?: "zh" | "en";
}) {
  const isZh = lang === "zh";
  return (
    <VSurface
      tone="panel"
      padding="normal"
      data-testid={STAGE_TWO_INACTIVE_PANEL_TEST_ID}
      data-vui-product="stage-two-inactive-node-panel"
      className="grid content-start justify-items-start gap-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <strong className="[font-size:var(--vui-font-md)]">
          {nodeLabel || nodeId}
        </strong>
        <VStatusChip tone="neutral">{isZh ? "未激活" : "Inactive"}</VStatusChip>
      </div>
      <p className="m-0 [font-size:var(--vui-font-xs)] leading-5 text-[var(--fg-secondary)]">
        {isZh
          ? "第二阶段未激活，需按题显式开启。当前运行的流程图在「假说生成」收口后即结束；此节点属于「研究计划与实验」阶段，只有按题显式开启二阶段后才会执行。"
          : "Stage two is inactive and must be enabled explicitly per question. This run's graph ends at hypothesis generation; this node belongs to the research-plan & experiment stage and only executes after stage two is explicitly enabled."}
      </p>
    </VSurface>
  );
}
