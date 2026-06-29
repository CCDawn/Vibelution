import { type ReactNode } from "react";

type AgentWorkspacePanelElement = "aside" | "main" | "section";

export type AgentWorkspacePanelProps = {
  as?: AgentWorkspacePanelElement;
  ariaLabel?: string;
  className?: string;
  children: ReactNode;
};

export function AgentWorkspacePanel({
  as: Element = "section",
  ariaLabel,
  className,
  children,
}: AgentWorkspacePanelProps) {
  return (
    <Element
      data-vui-product="agent-workspace-panel"
      aria-label={ariaLabel}
      className={[
        "grid min-h-0 min-w-0 content-start gap-[var(--agent-density-gap)] rounded-[var(--radius-panel)] border border-vui-border-hairline bg-vui-surface-panel/82 p-[var(--agent-panel-pad)] shadow-none",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Element>
  );
}
