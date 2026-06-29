import { type ReactNode } from "react";

import { VButton, VIconButton, VHStack, VToolbar } from "../../index";

export type AgentPageHeaderAction = {
  id: string;
  label: string;
  icon?: ReactNode;
  onPress?: () => void;
  disabled?: boolean;
};

export type AgentPageHeaderProps = {
  eyebrow: string;
  title: string;
  actions?: AgentPageHeaderAction[];
};

export function AgentPageHeader({
  eyebrow,
  title,
  actions = [],
}: AgentPageHeaderProps) {
  return (
    <header
      data-vui-product="agent-page-header"
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b border-vui-border-hairline bg-vui-surface-page/76 px-3 py-1"
    >
      <div className="grid min-w-0 gap-0.5">
        <span className="truncate text-[0.64rem] font-semibold uppercase tracking-[0.06em] text-vui-fg-tertiary">
          {eyebrow}
        </span>
        <h1 className="m-0 truncate text-[0.95rem] font-bold leading-tight text-vui-fg-primary">
          {title}
        </h1>
      </div>
      <VToolbar ariaLabel={`${title} actions`} className="justify-end">
        {actions.map((action) => (
          <VHStack key={action.id}>
            {action.icon ? (
              <VIconButton
                label={action.label}
                icon={action.icon}
                onPress={action.onPress}
                isDisabled={action.disabled}
              />
            ) : (
              <VButton onPress={action.onPress} isDisabled={action.disabled}>
                {action.label}
              </VButton>
            )}
          </VHStack>
        ))}
      </VToolbar>
    </header>
  );
}
