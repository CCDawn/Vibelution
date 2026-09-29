import {
  forwardRef,
  useContext,
  useId,
  type ChangeEvent,
  type ComponentPropsWithoutRef,
} from "react";

import {
  type VuiDensity,
  vuiControlMinHeightClass,
} from "../shared/buttonVariants";
import { FieldRowIdContext } from "../../forms/fieldRowContext";

/**
 * Shadcn-style native switch renderer.
 * Pages must not import this — only VUI form primitives consume it.
 *
 * HeroUI-era contract kept for parity with ShadcnCheckbox:
 * - isSelected / defaultSelected
 * - onChange(isSelected: boolean)
 * - isDisabled
 * Native <input type="checkbox"> carries the switch semantics (role=switch)
 * so keyboard + form behavior stay native; the track/thumb are pure visuals.
 */
export type ShadcnSwitchProps = Omit<
  ComponentPropsWithoutRef<"input">,
  "type" | "checked" | "defaultChecked" | "onChange" | "children" | "disabled"
> & {
  /** Controlled on-state. */
  isSelected?: boolean;
  /** Uncontrolled initial on-state. */
  defaultSelected?: boolean;
  /** Change handler — receives the next boolean, not a DOM event. */
  onChange?: (isSelected: boolean) => void;
  isDisabled?: boolean;
  disabled?: boolean;
  density?: VuiDensity;
  "data-vui"?: string;
};

export const ShadcnSwitch = forwardRef<HTMLInputElement, ShadcnSwitchProps>(
  function ShadcnSwitch(
    {
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

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
      onChange?.(event.target.checked);
    };

    return (
      <span
        className={[
          "relative inline-grid place-items-center",
          vuiControlMinHeightClass(density),
          isDisabledResolved ? "cursor-not-allowed opacity-55" : "cursor-pointer",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        data-vui={dataVui ?? "switch"}
        data-renderer="shadcn"
        data-density={density}
        data-selected={controlled ? (isSelected ? "true" : "false") : undefined}
        data-disabled={isDisabledResolved ? "true" : undefined}
      >
        <span data-slot="switch-content" className="relative inline-grid place-items-center">
          <input
            {...props}
            ref={ref}
            id={inputId}
            type="checkbox"
            role="switch"
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
            data-slot="switch-track"
            aria-hidden="true"
            className={[
              "pointer-events-none relative inline-block h-[18px] w-8 shrink-0 rounded-full border",
              "border-[var(--vui-border-strong)] bg-[color-mix(in_srgb,var(--vui-control-muted)_80%,transparent)]",
              "transition-[background-color,border-color] duration-150 motion-reduce:transition-none",
              "peer-checked:border-[var(--accent-cool)] peer-checked:bg-[var(--accent-cool)]",
              // peer variants only reach siblings of the input, so the thumb move
              // hangs off the track as a descendant arbitrary variant.
              "peer-checked:[&_[data-slot=switch-thumb]]:[translate:16px_-50%]",
              "peer-focus-visible:ring-2 peer-focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]",
              "peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[var(--vui-surface-panel)]",
            ].join(" ")}
          >
            <span
              data-slot="switch-thumb"
              className={[
                "absolute top-1/2 left-px block size-3.5 -translate-y-1/2 rounded-full",
                "bg-[var(--vui-surface-panel)] shadow-sm",
                "transition-[translate] duration-150 motion-reduce:transition-none",
              ].join(" ")}
            />
          </span>
        </span>
      </span>
    );
  },
);
