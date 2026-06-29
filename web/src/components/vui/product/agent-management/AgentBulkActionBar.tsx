import { type ReactNode } from "react";

import { VActionGroup, VSurface, VToolbar } from "../../index";

export type AgentBulkActionBarProps = {
  ariaLabel: string;
  summary: ReactNode;
  selectionActions?: ReactNode;
  promptPicker?: ReactNode;
  mutationActions?: ReactNode;
  destructiveActions?: ReactNode;
  className?: string;
};

export function AgentBulkActionBar({
  ariaLabel,
  summary,
  selectionActions,
  promptPicker,
  mutationActions,
  destructiveActions,
  className,
}: AgentBulkActionBarProps) {
  return (
    <VSurface
      as="section"
      data-vui="agent-bulk-action-bar"
      data-vui-product="agent-bulk-action-bar"
      ariaLabel={ariaLabel}
      padding="none"
      tone="toolbar"
      className={["px-1.5 py-1", className].filter(Boolean).join(" ")}
    >
      <VToolbar
        ariaLabel={ariaLabel}
        className="w-full !flex-nowrap overflow-x-auto gap-1.5 [scrollbar-width:thin] [&_button]:whitespace-nowrap"
      >
        <div className="inline-flex min-h-[26px] shrink-0 items-center gap-1.5 text-[0.76rem] font-semibold text-vui-fg-secondary [&>strong]:text-vui-fg-primary">
          {summary}
        </div>
        {selectionActions ? (
          <VActionGroup ariaLabel={`${ariaLabel} selection`} className="shrink-0 !flex-nowrap justify-start">
            {selectionActions}
          </VActionGroup>
        ) : null}
        {promptPicker ? (
          <div className="min-w-[160px] flex-[1_0_180px]">{promptPicker}</div>
        ) : null}
        {mutationActions ? (
          <VActionGroup ariaLabel={`${ariaLabel} mutation`} className="shrink-0 !flex-nowrap justify-end">
            {mutationActions}
          </VActionGroup>
        ) : null}
        {destructiveActions ? (
          <VActionGroup ariaLabel={`${ariaLabel} destructive`} className="shrink-0 !flex-nowrap justify-end">
            {destructiveActions}
          </VActionGroup>
        ) : null}
      </VToolbar>
    </VSurface>
  );
}
