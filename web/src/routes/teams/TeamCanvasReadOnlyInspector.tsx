import { Eye } from "lucide-react";

import type { TeamCanvasNode } from "../../api/types";
import { VStatusChip } from "../../components/vui";
import { canvasNodeStatusLabel, teamNodeFunctionLabel } from "./teamRouteShellModel";
import styles from "./TeamCanvasReadOnlyInspector.styles";
import { canvasNodeTitle, canvasNodeSecondaryLines } from "./teamCanvasNodePresentation";

export type TeamCanvasReadOnlyInspectorProps = {
  lang: "zh" | "en";
  node: TeamCanvasNode | null;
  agentName?: string;
  functionLabel?: string;
  validationIssues: Array<{ code: string; message: string; nodeId?: string; edgeId?: string }>;
  className?: string;
  noticeClassName?: string;
  nodeClassName?: string;
  nodeWideClassName?: string;
  emptyClassName?: string;
  issueListClassName?: string;
  issueClassName?: string;
};

/**
 * Read-only canvas inspector: node identity + validation issues (no write actions).
 */
export function TeamCanvasReadOnlyInspector({
  lang,
  node,
  agentName,
  functionLabel,
  validationIssues,
  className = styles.panel,
  noticeClassName = styles.notice,
  nodeClassName = styles.fields,
  nodeWideClassName = "",
  emptyClassName = "",
  issueListClassName = styles.issues,
  issueClassName = "",
}: TeamCanvasReadOnlyInspectorProps) {
  const title = node ? canvasNodeTitle(node, agentName) : "";
  const role = node ? functionLabel || teamNodeFunctionLabel(node, "", lang) : "";
  const secondary = node ? canvasNodeSecondaryLines(node, agentName || node.agentName || node.agentCode || "", role, title) : null;
  return (
    <section
      className={className}
      aria-label={lang === "zh" ? "只读组织画布详情" : "Read-only organization canvas details"}
      data-testid="team-canvas-read-only-inspector"
    >
      <div className={noticeClassName}>
        <Eye size={14} aria-hidden="true" />
        <span>{lang === "zh" ? "组织关系 · 只读" : "Organization · Read only"}</span>
      </div>
      {node ? (
        <>
          <div className={styles.identity}>
            <h3>{title}</h3>
            <VStatusChip tone={node.status === "stale" || !node.agentId ? "warning" : "neutral"}>
              {canvasNodeStatusLabel(node, lang)}
            </VStatusChip>
          </div>
          <div className={nodeClassName}>
          <div>
            <span>{lang === "zh" ? "职责" : "Role"}</span>
            <strong>{role}</strong>
          </div>
          {secondary?.agent ? <div>
            <span>Agent</span>
            <strong>{secondary.agent}</strong>
          </div> : null}
          {secondary?.purpose ? <div className={nodeWideClassName}>
            <span>{lang === "zh" ? "说明" : "Purpose"}</span>
            <strong>{secondary.purpose}</strong>
          </div> : null}
          </div>
        </>
      ) : (
        <div className={emptyClassName}>
          {lang === "zh" ? "选择一个节点查看详情。" : "Select a node to inspect details."}
        </div>
      )}
      {validationIssues.length ? <div className={issueListClassName} role="status">
          {validationIssues.map((issue) => (
            <div key={`${issue.code}-${issue.nodeId}-${issue.edgeId}`} className={issueClassName}>
              <strong>{issue.code}</strong>
              <span>{issue.message}</span>
            </div>
          ))}
      </div> : null}
    </section>
  );
}

// Keep helper available for call sites that already compute labels via teamNodeFunctionLabel.
export { teamNodeFunctionLabel };
