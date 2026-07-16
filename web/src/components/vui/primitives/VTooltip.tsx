import {
  Tooltip,
  type TooltipContentProps,
  type TooltipProps,
  type TooltipTriggerProps,
} from "@heroui/react";
import {
  cloneElement,
  isValidElement,
  type ReactElement,
  type ReactNode,
  type Ref,
} from "react";

export type VTooltipTriggerRender = NonNullable<TooltipTriggerProps<"button">["render"]>;

export type VTooltipTone = "neutral" | "warning" | "danger";
export type VTooltipWidth = "compact" | "default" | "wide";

export type VTooltipProps = Omit<TooltipProps, "children"> & {
  children: ReactNode;
  content: ReactNode;
  className?: string;
  renderTrigger?: VTooltipTriggerRender;
  showArrow?: boolean;
  tone?: VTooltipTone;
  width?: VTooltipWidth;
};

const toneClassName: Record<VTooltipTone, string> = {
  neutral:
    "border-[color-mix(in_srgb,var(--vui-border-subtle)_82%,var(--accent-cool)_18%)] text-vui-fg-secondary",
  warning:
    "border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] text-vui-fg-primary",
  danger:
    "border-[color-mix(in_srgb,var(--state-error)_44%,var(--vui-border-subtle))] text-vui-fg-primary",
};

const widthClassName: Record<VTooltipWidth, string> = {
  compact: "max-w-56",
  default: "max-w-80",
  wide: "max-w-[min(26rem,calc(100vw-1.5rem))]",
};

type TooltipElementProps = Record<string, unknown> & {
  className?: string;
  ref?: Ref<Element>;
};

type UnknownHandler = (...args: unknown[]) => unknown;

function assignElementRef(ref: NonNullable<Ref<Element>>, value: Element | null): void {
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  ref.current = value;
}

function mergeTooltipTriggerProps(
  childProps: TooltipElementProps,
  triggerProps: TooltipElementProps,
): TooltipElementProps {
  const merged: TooltipElementProps = { ...triggerProps, ...childProps };

  // HeroUI includes the trigger element in its render props. Forwarding that
  // value as `children` breaks void elements such as input and img.
  if (!Object.prototype.hasOwnProperty.call(childProps, "children")) {
    delete merged.children;
  }

  for (const key of Object.keys(childProps)) {
    const childHandler = childProps[key];
    const triggerHandler = triggerProps[key];
    if (
      /^on[A-Z]/.test(key)
      && typeof childHandler === "function"
      && typeof triggerHandler === "function"
    ) {
      merged[key] = (...args: unknown[]) => {
        (childHandler as UnknownHandler)(...args);
        (triggerHandler as UnknownHandler)(...args);
      };
    }
  }

  merged.className = [triggerProps.className, childProps.className].filter(Boolean).join(" ");

  if (childProps.ref && triggerProps.ref) {
    merged.ref = (value) => {
      assignElementRef(childProps.ref as NonNullable<Ref<Element>>, value);
      assignElementRef(triggerProps.ref as NonNullable<Ref<Element>>, value);
    };
  }

  return merged;
}

export function VTooltip({
  delay = 320,
  closeDelay = 100,
  children,
  content,
  className,
  renderTrigger,
  showArrow = true,
  tone = "neutral",
  width = "default",
  ...props
}: VTooltipProps) {
  const resolvedRenderTrigger = renderTrigger ?? (
    isValidElement(children)
      ? (tooltipTriggerProps: TooltipElementProps) => {
          const child = children as ReactElement<TooltipElementProps>;
          return cloneElement(
            child,
            mergeTooltipTriggerProps(child.props, tooltipTriggerProps),
          );
        }
      : undefined
  );
  const contentProps: TooltipContentProps = {
    className: [
      "pointer-events-none z-[100] whitespace-normal break-words rounded-[10px] border bg-[color-mix(in_srgb,var(--vui-surface-panel)_96%,transparent)] px-3 py-2 text-[var(--vui-font-xs)] font-medium leading-[1.5] shadow-[var(--vui-elevation-overlay)] backdrop-blur-xl [text-wrap:pretty]",
      widthClassName[width],
      toneClassName[tone],
      className,
    ]
      .filter(Boolean)
      .join(" "),
    children: content,
    showArrow,
  };

  return (
    <Tooltip {...props} delay={delay} closeDelay={closeDelay}>
      <Tooltip.Trigger<"button"> render={resolvedRenderTrigger as VTooltipTriggerRender | undefined}>
        {children}
      </Tooltip.Trigger>
      <Tooltip.Content {...contentProps} data-vui="tooltip-content" />
    </Tooltip>
  );
}
