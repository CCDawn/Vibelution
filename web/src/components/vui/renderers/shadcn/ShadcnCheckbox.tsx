import {
  forwardRef,
  useId,
  type ChangeEvent,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";

import {
  type VuiDensity,
  vuiControlMinHeightClass,
} from "../shared/buttonVariants";

/**
 * Shadcn-style native checkbox renderer.
 * Pages must not import this — only VUI form primitives consume it.
 *
 * Keeps HeroUI-era contracts:
 * - isSelected / defaultSelected
 * - onChange(isSelected: boolean)
 * - isDisabled
 * - data-slot structure expected by form smoke tests
 */
export type ShadcnCheckboxProps = Omit<
  ComponentPropsWithoutRef<"input">,
  "type" | "checked" | "defaultChecked" | "onChange" | "children" | "disabled"
> & {
  children?: ReactNode;
  /** Controlled selection (HeroUI-era). */
  isSelected?: boolean;
  /** Uncontrolled initial selection (HeroUI-era). */
  defaultSelected?: boolean;
  /** HeroUI-era change handler — receives the next boolean, not a DOM event. */
  onChange?: (isSelected: boolean) => void;
  isDisabled?: boolean;
  disabled?: boolean;
  density?: VuiDensity;
  "data-vui"?: string;
};

export const ShadcnCheckbox = forwardRef<HTMLInputElement, ShadcnCheckboxProps>(
  function ShadcnCheckbox(
    {
      children,
      className,
      isSelected,
      defaultSelected,
      onChange,
      isDisabled = false,
      disabled,
      density = "compact",
      id,
      "data-vui": dataVui,
      "aria-label": ariaLabel,
      ...props
    },
    ref,
  ) {
    const autoId = useId();
    const inputId = id ?? autoId;
    const isDisabledResolved = Boolean(disabled || isDisabled);
    const controlled = isSelected !== undefined;

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
      onChange?.(event.target.checked);
    };

    return (
      <label
        className={[
          "inline-flex min-w-0 items-center gap-2 rounded-[var(--radius-control)]",
          vuiControlMinHeightClass(density),
          "border border-vui-border-subtle bg-vui-control-muted px-2 text-sm text-vui-fg-secondary shadow-none",
          "transition-colors",
          "has-[:checked]:border-vui-accent-cool has-[:checked]:text-vui-fg-primary",
          isDisabledResolved ? "cursor-not-allowed opacity-55" : "cursor-pointer",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        data-vui={dataVui ?? "checkbox"}
        data-renderer="shadcn"
        data-density={density}
        data-selected={controlled ? (isSelected ? "true" : "false") : undefined}
        data-disabled={isDisabledResolved ? "true" : undefined}
      >
        <span data-slot="checkbox-content" className="inline-flex min-w-0 items-center gap-2">
          <span data-slot="checkbox-control" className="inline-flex shrink-0 items-center justify-center">
            <input
              {...props}
              ref={ref}
              id={inputId}
              type="checkbox"
              className={[
                "h-4 w-4 min-w-4 rounded border border-vui-border-subtle",
                "bg-vui-control-muted text-vui-accent-cool shadow-none accent-[var(--accent-cool)]",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-vui-accent-cool",
                "disabled:cursor-not-allowed",
              ].join(" ")}
              checked={controlled ? Boolean(isSelected) : undefined}
              defaultChecked={!controlled ? defaultSelected : undefined}
              disabled={isDisabledResolved}
              aria-label={ariaLabel}
              onChange={handleChange}
            />
            <span data-slot="checkbox-indicator" aria-hidden="true" className="sr-only" />
          </span>
          {children ? <span className="min-w-0">{children}</span> : null}
        </span>
      </label>
    );
  },
);
