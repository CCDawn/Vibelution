import { type Key, type ReactNode } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import {
  ShadcnSelect,
  type ShadcnSelectOption,
} from "../renderers/shadcn/ShadcnSelect";

export type VSelectOption = {
  id: string | number;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
};

export type VSelectProps = {
  density?: VuiDensity;
  options: VSelectOption[];
  placeholder?: string;
  className?: string;
  "data-vui"?: string;
  "aria-label"?: string;
  /** Controlled selection (HeroUI-era). */
  selectedKey?: Key | null;
  /** Uncontrolled initial selection (HeroUI-era). */
  defaultSelectedKey?: Key | null;
  onSelectionChange?: (key: Key | null) => void;
  isDisabled?: boolean;
  disabled?: boolean;
  name?: string;
  id?: string;
};

/**
 * Product select API. Implementation is the shadcn-style native renderer.
 * Keeps selectedKey/onSelectionChange for existing call sites.
 */
export function VSelect({
  density = "compact",
  options,
  placeholder = "Select",
  className,
  "data-vui": dataVui,
  "aria-label": ariaLabel,
  selectedKey,
  defaultSelectedKey,
  onSelectionChange,
  isDisabled,
  disabled,
  name,
  id,
}: VSelectProps) {
  const shadcnOptions: ShadcnSelectOption[] = options.map((option) => ({
    id: option.id,
    label: option.label,
    description: option.description,
    disabled: option.disabled,
  }));

  return (
    <span className={["inline-flex w-full min-w-0", className].filter(Boolean).join(" ")} data-vui="select-shell">
      <ShadcnSelect
        density={density}
        options={shadcnOptions}
        placeholder={placeholder}
        selectedKey={selectedKey}
        defaultSelectedKey={defaultSelectedKey}
        onSelectionChange={onSelectionChange}
        isDisabled={isDisabled}
        disabled={disabled}
        data-vui={dataVui ?? "select"}
        aria-label={ariaLabel}
        name={name}
        id={id}
      />
    </span>
  );
}
