import {
  forwardRef,
  useContext,
  useId,
  type ChangeEvent,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";
import { Check } from "lucide-react";

import {
  type VuiDensity,
  vuiControlMinHeightClass,
} from "../shared/buttonVariants";
import { FieldRowIdContext } from "../../forms/fieldRowContext";

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
    const fieldRowId = useContext(FieldRowIdContext);
    const autoId = useId();
    const inputId = id ?? fieldRowId ?? autoId;
    const isDisabledResolved = Boolean(disabled || isDisabled);
    const controlled = isSelected !== undefined;
    const hasLabel = Boolean(children);

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
      onChange?.(event.target.checked);
    };

    return (
      <label
        className={[
          "inline-flex min-w-0 items-center gap-2 rounded-[var(--radius-control)] text-sm text-vui-fg-secondary",
          hasLabel
            ? `${vuiControlMinHeightClass(density)} px-1`
            : "size-8 justify-center",
          "transition-[color,background-color] duration-150 motion-reduce:transition-none",
          "has-[:checked]:text-vui-fg-primary",
          "hover:bg-[color-mix(in_srgb,var(--vui-control-muted)_72%,transparent)]",
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
          <span
            data-slot="checkbox-control"
            className="relative inline-grid size-5 shrink-0 place-items-center"
          >
            <input
              {...props}
              ref={ref}
              id={inputId}
              type="checkbox"
              className={[
                "peer absolute inset-0 size-full cursor-pointer appearance-none opacity-0",
                "focus-visible:outline-none",
                "disabled:cursor-not-allowed",
              ].join(" ")}
              checked={controlled ? Boolean(isSelected) : undefined}
              defaultChecked={!controlled ? defaultSelected : undefined}
              disabled={isDisabledResolved}
              aria-label={ariaLabel}
              onChange={handleChange}
            />
            <span
              data-slot="checkbox-indicator"
              aria-hidden="true"
              className={[
                "pointer-events-none grid size-5 place-items-center rounded-[6px] border",
                "border-[var(--vui-border-strong)] bg-[var(--vui-surface-panel)] text-[var(--vui-surface-base)]",
                "shadow-[inset_0_1px_0_color-mix(in_srgb,var(--vui-surface-panel)_70%,transparent)]",
                "transition-[background-color,border-color,box-shadow] duration-150 motion-reduce:transition-none",
                "peer-checked:border-[var(--accent-cool)] peer-checked:bg-[var(--accent-cool)]",
                "peer-focus-visible:ring-2 peer-focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
                "peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[var(--vui-surface-panel)]",
                "[&_svg]:opacity-0 peer-checked:[&_svg]:opacity-100",
              ].join(" ")}
            >
              <Check size={14} strokeWidth={2.5} aria-hidden="true" />
            </span>
          </span>
          {children ? <span className="min-w-0">{children}</span> : null}
        </span>
      </label>
    );
  },
);
