import {
  forwardRef,
  lazy,
  Suspense,
  type ButtonHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

import { ShadcnButton } from "../renderers/shadcn/ShadcnButton";
import {
  type VuiButtonVariant,
  type VuiDensity,
} from "../renderers/shared/buttonVariants";
import { vuiButtonGeometryClass } from "../renderers/shared/buttonSlots";

/** Keep Radix/floating-ui out of the shell entry until a button actually needs a tooltip. */
const VTooltip = lazy(async () => {
  const module = await import("./VTooltip");
  return { default: module.VTooltip };
});

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
    isIconOnly,
    onPress,
    ...props
  },
  ref,
) {
  const tooltipContent = isDisabled && disabledReason ? disabledReason : tooltip ?? title;
  const hasTooltip = tooltipContent !== undefined && tooltipContent !== null && tooltipContent !== "";
  const titleProps = title && !hasTooltip ? ({ title } as Record<string, string>) : undefined;
  const iconOnly = Boolean(isIconOnly);

  const button = (
    <ShadcnButton
      {...props}
      {...titleProps}
      ref={ref}
      data-vui={dataVui ?? "button"}
      variant={variant}
      density={density}
      isDisabled={isDisabled}
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
          {icon}
          {children}
          {trailingIcon}
        </>
      ) : (
        <span
          data-slot="vui-button-content"
          title={hasTooltip ? undefined : title}
          className="inline-flex min-w-0 max-w-full items-center justify-center gap-1.5"
        >
          {icon ? (
            <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
              {icon}
            </span>
          ) : null}
          {iconOnly && children ? (
            <span data-slot="vui-button-icon" className="inline-grid shrink-0 place-items-center">
              {children}
            </span>
          ) : children ? (
            <span data-slot="vui-button-label" className="min-w-0 truncate whitespace-nowrap">
              {children}
            </span>
          ) : null}
          {trailingIcon ? (
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

  if (isDisabled) {
    const actionLabel = typeof props["aria-label"] === "string"
      ? props["aria-label"]
      : typeof children === "string"
        ? children
        : undefined;
    const reasonLabel = typeof tooltipContent === "string" ? tooltipContent : undefined;
    return (
      <Suspense fallback={button}>
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
      </Suspense>
    );
  }

  return (
    <Suspense fallback={button}>
      <VTooltip content={tooltipContent}>{button}</VTooltip>
    </Suspense>
  );
});
