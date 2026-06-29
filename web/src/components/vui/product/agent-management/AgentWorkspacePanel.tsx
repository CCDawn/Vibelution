import { type ReactNode } from "react";

import { VSurface } from "../../index";

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
    <VSurface
      as={Element}
      data-vui-product="agent-workspace-panel"
      ariaLabel={ariaLabel}
      padding="none"
      tone="glass"
      className={[
        "grid min-h-0 content-start gap-[var(--agent-density-gap)] p-[var(--agent-panel-pad)]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </VSurface>
  );
}
