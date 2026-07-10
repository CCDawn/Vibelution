import { type ReactNode, type Ref } from "react";

import { VButton, type VButtonProps } from "./VButton";
import { VTooltip } from "./VTooltip";

export type VIconButtonProps = Omit<
  VButtonProps,
  "children" | "icon" | "isIconOnly" | "aria-label"
> & {
  label: string;
  icon: ReactNode;
  title?: string;
  tooltip?: ReactNode;
};

type UnknownHandler = (...args: unknown[]) => unknown;

function assignButtonRef(
  ref: NonNullable<Ref<HTMLButtonElement>>,
  value: HTMLButtonElement | null,
): void {
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  ref.current = value;
}

function composeButtonProps(
  callerProps: VButtonProps,
  triggerProps: VButtonProps,
): VButtonProps {
  const mergedProps = { ...callerProps, ...triggerProps } as VButtonProps;
  const callerRecord = callerProps as unknown as Record<string, unknown>;
  const triggerRecord = triggerProps as unknown as Record<string, unknown>;
  const mergedRecord = mergedProps as unknown as Record<string, unknown>;

  for (const key of Object.keys(callerRecord)) {
    const callerHandler = callerRecord[key];
    const triggerHandler = triggerRecord[key];
    if (
      /^on[A-Z]/.test(key) &&
      typeof callerHandler === "function" &&
      typeof triggerHandler === "function"
    ) {
      mergedRecord[key] = (...args: unknown[]) => {
        (callerHandler as UnknownHandler)(...args);
        (triggerHandler as UnknownHandler)(...args);
      };
    }
  }

  const callerRef = callerProps.ref;
  const triggerRef = triggerProps.ref;
  if (callerRef && triggerRef) {
    mergedProps.ref = (value) => {
      assignButtonRef(callerRef, value);
      assignButtonRef(triggerRef, value);
    };
  }

  return mergedProps;
}

export function VIconButton({ label, icon, title, tooltip, ...props }: VIconButtonProps) {
  return (
    <VTooltip
      content={tooltip ?? label}
      renderTrigger={(tooltipTriggerProps) => {
        const {
          children: _triggerChildren,
          className: triggerClassName,
          role: _triggerRole,
          tabIndex: _triggerTabIndex,
          ...triggerProps
        } = tooltipTriggerProps;
        const buttonTriggerProps = triggerProps as unknown as VButtonProps;
        const mergedButtonProps = composeButtonProps(props, buttonTriggerProps);

        return (
          <VButton
            {...mergedButtonProps}
            data-vui="icon-button"
            isIconOnly
            aria-label={label}
            title={title ?? label}
            className={[
              triggerClassName,
              "h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] aspect-square flex-none shrink-0 px-0",
              props.className,
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {icon}
          </VButton>
        );
      }}
    >
      {icon}
    </VTooltip>
  );
}
