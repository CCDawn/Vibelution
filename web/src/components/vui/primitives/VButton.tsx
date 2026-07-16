import { Button, type ButtonProps } from "@heroui/react";
import { type ReactNode } from "react";

import {
  vuiButtonBaseClass,
  vuiButtonDangerClass,
  vuiButtonHoverClass,
  vuiButtonPrimaryClass,
} from "../renderers/heroui/heroSlots";
import {
  type VuiButtonVariant,
  type VuiDensity,
  vuiControlHeight,
} from "../renderers/heroui/heroVariants";
import { VTooltip } from "./VTooltip";

export type VButtonProps = Omit<
  ButtonProps,
  "variant" | "color" | "size" | "startContent" | "endContent"
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
};

function variantClass(variant: VuiButtonVariant | undefined): string {
  if (variant === "primary") {
    return `${vuiButtonBaseClass} ${vuiButtonHoverClass} ${vuiButtonPrimaryClass}`;
  }
  if (variant === "danger") {
    return `${vuiButtonBaseClass} ${vuiButtonHoverClass} ${vuiButtonDangerClass}`;
  }
  if (variant === "ghost") {
    return `border border-transparent bg-transparent text-vui-fg-secondary shadow-none ${vuiButtonHoverClass}`;
  }
  return `${vuiButtonBaseClass} ${vuiButtonHoverClass}`;
}

function classNameTokens(className: VButtonProps["className"]): string[] {
  return typeof className === "string" ? className.trim().split(/\s+/).filter(Boolean) : [];
}

function hasExplicitRootWidth(className: VButtonProps["className"]): boolean {
  return classNameTokens(className).some((token) => {
    if (token.startsWith("[&")) {
      return false;
    }
    return /(?:^|:)!?w-(?:auto|fit|full|max|min|\[|[0-9])/.test(token);
  });
}

function hasFullRootWidth(className: VButtonProps["className"]): boolean {
  return classNameTokens(className).some((token) => {
    if (token.startsWith("[&")) {
      return false;
    }
    return /(?:^|:)!?w-full$/.test(token);
  });
}

function buttonGeometryClass(
  className: VButtonProps["className"],
  contentLayout: NonNullable<VButtonProps["contentLayout"]>,
): string {
  return [
    "inline-flex max-w-full shrink-0 justify-self-start",
    contentLayout === "label" ? "whitespace-nowrap" : null,
    hasExplicitRootWidth(className) ? null : "w-fit",
  ]
    .filter(Boolean)
    .join(" ");
}

export function VButton({
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
  ...props
}: VButtonProps) {
  const tooltipContent = props.isDisabled && disabledReason ? disabledReason : tooltip ?? title;
  const hasTooltip = tooltipContent !== undefined && tooltipContent !== null && tooltipContent !== "";
  const titleProps = title && !hasTooltip ? ({ title } as Record<string, string>) : undefined;
  const isIconOnly = Boolean(props.isIconOnly);

  const button = (
    <Button
      {...props}
      {...titleProps}
      data-vui={dataVui ?? "button"}
      size={vuiControlHeight(density)}
      className={[
        variantClass(variant),
        buttonGeometryClass(className, contentLayout),
        "min-w-0 px-2 text-[var(--vui-font-sm)] font-semibold",
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
          {isIconOnly && children ? (
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
    </Button>
  );

  if (!hasTooltip) {
    return button;
  }

  if (props.isDisabled) {
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
}
