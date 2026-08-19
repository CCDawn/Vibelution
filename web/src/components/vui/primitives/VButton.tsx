import {
  forwardRef,
  type ButtonHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";
import { LoaderCircle } from "lucide-react";

import { ShadcnButton } from "../renderers/shadcn/ShadcnButton";
import {
  type VuiButtonVariant,
  type VuiDensity,
} from "../renderers/shared/buttonVariants";
import { vuiButtonGeometryClass } from "../renderers/shared/buttonSlots";
// Eager: lazy+Suspense reused the same button element as fallback and children,
// remounting Radix trigger hosts until React 19 hit error #185.
import { VTooltip } from "./VTooltip";

export type VButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "disabled" | "children"
> & {
  contentLayout?: "label" | "plain";
  variant?: VuiButtonVariant;
  density?: VuiDensity;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
  children?: ReactNode;
  disabledReason?: ReactNode;
  tooltip?: ReactNode;
  "data-vui"?: string;
  role?: string;
  title?: string;
  /** HeroUI-era disabled flag — mapped to native disabled. */
  isDisabled?: boolean;
  /**
   * Async / mutation pending. Disables the control, sets aria-busy,
   * and shows a spinner (shadcn Button loading pattern).
   */
  isPending?: boolean;
  /** Square icon layout flag (VIconButton). */
  isIconOnly?: boolean;
  /** HeroUI-era press handler — still supported, fires after onClick. */
  onPress?: (event: MouseEvent<HTMLButtonElement>) => void;
};

function hasFullRootWidth(className: VButtonProps["className"]): boolean {
  if (typeof className !== "string") {
    return false;
  }
  return className.trim().split(/\s+/).filter(Boolean).some((token) => {
    if (token.startsWith("[&")) {
      return false;
    }
    return /(?:^|:)!?w-full$/.test(token);
  });
}

export const VButton = forwardRef<HTMLButtonElement, VButtonProps>(function VButton(
  {
    contentLayout = "label",
    variant = "secondary",
    density = "compact",
    icon,
    trailingIcon,
    className,
    children,
    disabledReason,
    tooltip,
    "data-vui": dataVui,
    title,
    isDisabled,
    isPending = false,
    isIconOnly,
    onPress,
    ...props
  },
  ref,
) {
  const blocked = Boolean(isDisabled || isPending);
  // `title` is a native, zero-state hint. Only the explicit `tooltip` and
  // disabled reason contracts should mount a Radix overlay. Treating every
  // title as VTooltip nests tooltip triggers inside popover/menu triggers and
  // can make startup session restoration recompose state-setting refs until
  // React aborts with #185.
  const tooltipContent = isDisabled && disabledReason ? disabledReason : tooltip;
  const hasTooltip = tooltipContent !== undefined && tooltipContent !== null && tooltipContent !== "";
  const titleProps = title && !hasTooltip ? ({ title } as Record<string, string>) : undefined;
  const iconOnly = Boolean(isIconOnly);
  const pendingIcon = (
    <LoaderCircle
      size={14}
      strokeWidth={2.25}
      className="animate-spin motion-reduce:animate-none"
      aria-hidden="true"
      data-slot="vui-button-pending"
    />
  );

  const button = (
    <ShadcnButton
      {...props}
      {...titleProps}
      ref={ref}
      data-vui={dataVui ?? "button"}
      variant={variant}
      density={density}
      isDisabled={isDisabled}
      isPending={isPending}
      isIconOnly={iconOnly}
      onPress={onPress}
      className={[
        vuiButtonGeometryClass(className, contentLayout),
        "min-w-0",
        // Plain multi-line/card buttons must escape fixed density height.
        contentLayout === "plain" ? "!h-auto" : null,
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {contentLayout === "plain" ? (
        <>
          {isPending ? pendingIcon : icon}
          {children}
          {trailingIcon}
        </>
      ) : (
        <span
          data-slot="vui-button-content"
          className="inline-flex min-w-0 max-w-full items-center justify-center gap-1.5"
        >
          {isPending ? (
            <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
              {pendingIcon}
            </span>
          ) : icon ? (
            <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
              {icon}
            </span>
          ) : null}
          {iconOnly && children && !isPending ? (
            <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
              {children}
            </span>
          ) : children ? (
            <span data-slot="vui-button-label" className="min-w-0 truncate whitespace-nowrap">
              {children}
            </span>
          ) : null}
          {!isPending && trailingIcon ? (
            <span data-slot="vui-button-trailing-icon" className="inline-grid shrink-0 place-items-center">
              {trailingIcon}
            </span>
          ) : null}
        </span>
      )}
    </ShadcnButton>
  );

  if (!hasTooltip) {
    return button;
  }

  if (blocked && isDisabled) {
    const actionLabel = typeof props["aria-label"] === "string"
      ? props["aria-label"]
      : typeof children === "string"
        ? children
        : undefined;
    const reasonLabel = typeof tooltipContent === "string" ? tooltipContent : undefined;
    return (
      <VTooltip content={tooltipContent} tone={disabledReason ? "warning" : "neutral"}>
        <span
          data-vui="disabled-tooltip-trigger"
          role="note"
          tabIndex={0}
          aria-label={[actionLabel, reasonLabel].filter(Boolean).join("：") || undefined}
          className={[
            "inline-flex max-w-full shrink-0 justify-self-start rounded-[var(--radius-control)] focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]",
            hasFullRootWidth(className) ? "w-full" : "w-fit",
          ].join(" ")}
        >
          {button}
        </span>
      </VTooltip>
    );
  }

  return <VTooltip content={tooltipContent}>{button}</VTooltip>;
});
