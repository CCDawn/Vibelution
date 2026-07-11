import { type Key, type ReactNode } from "react";

import { VSelect, type VSelectOption } from "./VSelect";

export type VStringSelectOption = {
  value: string;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
};

export type VStringSelectProps = {
  ariaLabel: string;
  className?: string;
  isDisabled?: boolean;
  onValueChange: (value: string) => void;
  options: readonly VStringSelectOption[];
  placeholder?: string;
  value: string;
};

function resolveStringSelectSelectedKey(
  value: string,
  options: readonly VStringSelectOption[],
): string | null {
  const option = options.find((candidate) => candidate.value === value);
  return option && !option.disabled ? option.value : null;
}

export function resolveStringSelectChange(
  key: Key | null,
  options: readonly VStringSelectOption[],
): string | null {
  return key == null ? null : resolveStringSelectSelectedKey(String(key), options);
}

export function VStringSelect({
  ariaLabel,
  className,
  isDisabled,
  onValueChange,
  options,
  placeholder,
  value,
}: VStringSelectProps) {
  const vuiOptions: VSelectOption[] = options.map((option) => ({
    id: option.value,
    label: option.label,
    description: option.description,
    disabled: option.disabled,
  }));

  return (
    <VSelect
      aria-label={ariaLabel}
      className={className}
      isDisabled={isDisabled}
      options={vuiOptions}
      placeholder={placeholder}
      selectedKey={resolveStringSelectSelectedKey(value, options)}
      onSelectionChange={(key) => {
        const nextValue = resolveStringSelectChange(key, options);
        if (nextValue !== null && nextValue !== value) onValueChange(nextValue);
      }}
    />
  );
}
