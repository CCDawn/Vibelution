import { Eye } from "lucide-react";

import type { TeamCanvasNode } from "../../api/types";
import { canvasNodeStatusLabel, teamNodeFunctionLabel } from "./teamRouteShellModel";

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
  className = "",
  noticeClassName = "",
  nodeClassName = "",
  nodeWideClassName = "",
  emptyClassName = "",
  issueListClassName = "",
  issueClassName = "",
}: TeamCanvasReadOnlyInspectorProps) {
  return (
    <section
      className={className}
      aria-label={lang === "zh" ? "只读组织画布详情" : "Read-only organization canvas details"}
      data-testid="team-canvas-read-only-inspector"
    >
      <div className={noticeClassName}>
        <Eye size={15} />
        <div>
          <strong>{lang === "zh" ? "只读组织画布" : "Read-only canvas"}</strong>
          <span>
            {lang === "zh"
              ? "这里仅展示科研团队节点关系，不写回画布配置。"
              : "This view shows research-team relationships without writing canvas config."}
          </span>
        </div>
      </div>
      {node ? (
        <div className={nodeClassName}>
          <div>
            <span>{lang === "zh" ? "节点" : "Node"}</span>
            <strong>{node.label}</strong>
          </div>
          <div>
            <span>{lang === "zh" ? "职责" : "Role"}</span>
            <strong>{functionLabel || node.role || node.type}</strong>
          </div>
          <div>
            <span>Agent</span>
            <strong>
              {agentName || node.agentName || node.agentCode || (lang === "zh" ? "未绑定" : "unbound")}
            </strong>
          </div>
          <div>
            <span>{lang === "zh" ? "状态" : "Status"}</span>
            <strong>{canvasNodeStatusLabel(node, lang)}</strong>
          </div>
          <div className={nodeWideClassName}>
            <span>{lang === "zh" ? "目的" : "Purpose"}</span>
            <strong>{node.purpose || (lang === "zh" ? "暂无说明" : "No purpose yet")}</strong>
          </div>
        </div>
      ) : (
        <div className={emptyClassName}>
          {lang === "zh" ? "选择一个节点查看详情。" : "Select a node to inspect details."}
        </div>
      )}
      <div className={issueListClassName}>
        {validationIssues.length ? (
          validationIssues.map((issue) => (
            <div key={`${issue.code}-${issue.nodeId}-${issue.edgeId}`} className={issueClassName}>
              <strong>{issue.code}</strong>
              <span>{issue.message}</span>
            </div>
          ))
        ) : (
          <span>{lang === "zh" ? "画布校验通过" : "Canvas validation passed"}</span>
        )}
      </div>
    </section>
  );
}

// Keep helper available for call sites that already compute labels via teamNodeFunctionLabel.
export { teamNodeFunctionLabel };
