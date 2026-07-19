import {
  forwardRef,
  useMemo,
  type ChangeEvent,
  type ComponentPropsWithoutRef,
  type Key,
  type ReactNode,
} from "react";

import { type VuiDensity } from "../shared/buttonVariants";
import { vuiFormControlClass } from "../../forms/formClasses";

export type ShadcnSelectOption = {
  id: string | number;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
};

export type ShadcnSelectProps = Omit<
  ComponentPropsWithoutRef<"select">,
  "children" | "value" | "defaultValue" | "onChange" | "disabled"
> & {
  density?: VuiDensity;
  options: ShadcnSelectOption[];
  placeholder?: string;
  /** Controlled selection (HeroUI-era). */
  selectedKey?: Key | null;
  /** Uncontrolled initial selection (HeroUI-era). */
  defaultSelectedKey?: Key | null;
  /** HeroUI-era change handler. */
  onSelectionChange?: (key: Key | null) => void;
  isDisabled?: boolean;
  disabled?: boolean;
  "data-vui"?: string;
};

function optionText(option: ShadcnSelectOption): string {
  if (typeof option.label === "string" || typeof option.label === "number") {
    return String(option.label);
  }
  if (typeof option.description === "string") {
    return `${String(option.id)} — ${option.description}`;
  }
  return String(option.id);
}

function hasEnabledOption(options: ShadcnSelectOption[], key: string): boolean {
  return options.some((option) => String(option.id) === key && !option.disabled);
}

/**
 * Shadcn-style native select renderer.
 * Pages must not import this — only VUI form primitives consume it.
 */
export const ShadcnSelect = forwardRef<HTMLSelectElement, ShadcnSelectProps>(function ShadcnSelect(
  {
    density = "compact",
    options,
    placeholder = "Select",
    selectedKey,
    defaultSelectedKey,
    onSelectionChange,
    isDisabled = false,
    disabled,
    className,
    "data-vui": dataVui,
    "aria-label": ariaLabel,
    ...props
  },
  ref,
) {
  const controlled = selectedKey !== undefined;
  const normalizedSelected =
    selectedKey === undefined || selectedKey === null ? null : String(selectedKey);
  const normalizedDefault =
    defaultSelectedKey === undefined || defaultSelectedKey === null
      ? null
      : String(defaultSelectedKey);

  const resolvedSelected = useMemo(() => {
    if (!controlled) {
      return null;
    }
    if (normalizedSelected === null) {
      return null;
    }
    return hasEnabledOption(options, normalizedSelected) ? normalizedSelected : null;
  }, [controlled, normalizedSelected, options]);

  const isPlaceholder = controlled
    ? resolvedSelected === null
    : normalizedDefault === null || !hasEnabledOption(options, normalizedDefault);

  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    // Empty string can be a real option; only null means cleared/placeholder-only.
    if (isPlaceholder && next === "" && !hasEnabledOption(options, "")) {
      onSelectionChange?.(null);
      return;
    }
    if (!hasEnabledOption(options, next)) {
      onSelectionChange?.(null);
      return;
    }
    onSelectionChange?.(next);
  };

  return (
    <select
      {...props}
      ref={ref}
      aria-label={ariaLabel}
      disabled={Boolean(disabled || isDisabled)}
      data-vui={dataVui ?? "select"}
      data-vui-select-trigger="true"
      data-density={density}
      data-renderer="shadcn"
      data-placeholder={isPlaceholder ? "true" : undefined}
      className={[
        vuiFormControlClass(density),
        "w-full min-w-0 appearance-none",
        "bg-[length:12px_12px] bg-[right_0.55rem_center] bg-no-repeat pr-7",
        // Theme-token chevron (dark/light) — avoid hardcoded fill hex.
        "bg-[image:var(--vui-select-chevron)]",
        "[color-scheme:inherit]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      value={controlled ? (resolvedSelected ?? "") : undefined}
      defaultValue={!controlled ? (normalizedDefault ?? "") : undefined}
      onChange={handleChange}
    >
      {isPlaceholder || !hasEnabledOption(options, "") ? (
        <option value="" disabled={hasEnabledOption(options, "") ? undefined : true} hidden={!isPlaceholder && hasEnabledOption(options, "")}>
          {placeholder}
        </option>
      ) : null}
      {options.map((option) => (
        <option
          key={String(option.id)}
          value={String(option.id)}
          disabled={option.disabled}
          title={typeof option.description === "string" ? option.description : undefined}
        >
          {optionText(option)}
        </option>
      ))}
    </select>
  );
});
