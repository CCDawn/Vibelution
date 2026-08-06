import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import {
  forwardRef,
  useMemo,
  type Key,
  type ReactNode,
} from "react";

import { cn } from "../../lib/cn";
import { vuiFormControlClass } from "../../forms/formClasses";
import {
  type VuiDensity,
  vuiControlDensityClass,
} from "../shared/buttonVariants";

export type ShadcnSelectOption = {
  id: string | number;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
};

export type ShadcnSelectProps = {
  density?: VuiDensity;
  options: ShadcnSelectOption[];
  placeholder?: string;
  className?: string;
  /** Controlled selection (HeroUI-era). */
  selectedKey?: Key | null;
  /** Uncontrolled initial selection (HeroUI-era). */
  defaultSelectedKey?: Key | null;
  /** HeroUI-era change handler. */
  onSelectionChange?: (key: Key | null) => void;
  isDisabled?: boolean;
  disabled?: boolean;
  "data-vui"?: string;
  "aria-label"?: string;
  name?: string;
  id?: string;
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

function optionValue(key: string): string {
  return `vui-select:${encodeURIComponent(key)}`;
}

function optionKey(
  options: ShadcnSelectOption[],
  value: string,
): string | null {
  const option = options.find(
    (candidate) => optionValue(String(candidate.id)) === value,
  );
  return option && !option.disabled ? String(option.id) : null;
}

/**
 * Radix/shadcn Select renderer.
 * Pages must not import this — only VUI form primitives consume it.
 * Keeps selectedKey / onSelectionChange for product call sites.
 */
export const ShadcnSelect = forwardRef<HTMLButtonElement, ShadcnSelectProps>(
  function ShadcnSelect(
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
      name,
      id,
    },
    ref,
  ) {
    const controlled = selectedKey !== undefined;
    const normalizedSelected =
      selectedKey === undefined || selectedKey === null
        ? undefined
        : String(selectedKey);
    const normalizedDefault =
      defaultSelectedKey === undefined || defaultSelectedKey === null
        ? undefined
        : String(defaultSelectedKey);

    const resolvedSelectedKey = useMemo(() => {
      if (!controlled) {
        return undefined;
      }
      if (normalizedSelected === undefined) {
        return undefined;
      }
      return hasEnabledOption(options, normalizedSelected)
        ? normalizedSelected
        : undefined;
    }, [controlled, normalizedSelected, options]);

    const resolvedDefaultKey =
      !controlled &&
      normalizedDefault !== undefined &&
      hasEnabledOption(options, normalizedDefault)
        ? normalizedDefault
        : undefined;

    const activeKey = controlled ? resolvedSelectedKey : resolvedDefaultKey;
    const isPlaceholder = activeKey === undefined;
    const activeOption = activeKey !== undefined
      ? options.find((option) => String(option.id) === activeKey)
      : undefined;
    // SSR/static markup: Radix Value may not hydrate label text; mirror known selection.
    const activeLabel = activeOption ? activeOption.label : null;

    const disabledAll = Boolean(disabled || isDisabled);

    return (
      <>
        {name ? (
          <input
            type="hidden"
            name={name}
            value={activeKey ?? ""}
            disabled={disabledAll}
          />
        ) : null}
        <SelectPrimitive.Root
          value={
            controlled && resolvedSelectedKey !== undefined
              ? optionValue(resolvedSelectedKey)
              : undefined
          }
          defaultValue={
            !controlled && resolvedDefaultKey !== undefined
              ? optionValue(resolvedDefaultKey)
              : undefined
          }
          onValueChange={(next) => {
            const nextKey = optionKey(options, next);
            if (nextKey === null) {
              onSelectionChange?.(null);
              return;
            }
            onSelectionChange?.(nextKey);
          }}
          disabled={disabledAll}
        >
          <SelectPrimitive.Trigger
            ref={ref}
            id={id}
            aria-label={ariaLabel}
            data-vui={dataVui ?? "select"}
            data-vui-select-trigger="true"
            data-density={density}
            data-renderer="radix"
            data-placeholder={isPlaceholder ? "true" : undefined}
            className={cn(
              vuiFormControlClass(density),
              "inline-flex w-full min-w-0 items-center justify-between gap-2",
              "appearance-none pr-2 text-left",
              "data-[placeholder]:text-vui-fg-tertiary",
              "[&>span]:min-w-0 [&>span]:truncate",
              className,
            )}
          >
            <SelectPrimitive.Value placeholder={placeholder}>
              {activeLabel}
            </SelectPrimitive.Value>
            <SelectPrimitive.Icon asChild>
              <ChevronDown
                size={14}
                strokeWidth={2.25}
                className="shrink-0 text-[var(--fg-tertiary)] opacity-80"
                aria-hidden="true"
              />
            </SelectPrimitive.Icon>
          </SelectPrimitive.Trigger>
          <SelectPrimitive.Portal>
            <SelectPrimitive.Content
              position="popper"
              sideOffset={4}
              className={cn(
                "z-[100] max-h-[min(18rem,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden",
                "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)]",
                "bg-[var(--vui-surface-panel)] text-[var(--fg-primary)] shadow-[var(--vui-elevation-overlay)]",
              )}
              data-vui="select-content"
              data-renderer="radix"
            >
              <SelectPrimitive.Viewport className="grid max-h-[inherit] gap-0.5 overflow-y-auto p-1">
                {options.map((option) => {
                  const key = String(option.id);
                  return (
                    <SelectPrimitive.Item
                      key={key}
                      value={optionValue(key)}
                      disabled={option.disabled}
                      className={cn(
                        "relative flex w-full cursor-default select-none items-start gap-2 rounded-[calc(var(--radius-control)-2px)]",
                        "py-1.5 pl-2 pr-8 text-left outline-none",
                        "data-[highlighted]:bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)]",
                        "data-[disabled]:pointer-events-none data-[disabled]:opacity-45",
                        vuiControlDensityClass(density).includes("md")
                          ? "min-h-[var(--vui-control-height-md)]"
                          : "min-h-[var(--vui-control-height-sm)]",
                      )}
                      title={typeof option.description === "string" ? option.description : undefined}
                    >
                      <span className="grid min-w-0 flex-1 gap-0.5">
                        <SelectPrimitive.ItemText className="block min-w-0 truncate text-sm font-medium text-[var(--fg-primary)]">
                          {option.label}
                        </SelectPrimitive.ItemText>
                        {option.description ? (
                          <span className="block min-w-0 truncate text-[11px] text-[var(--fg-tertiary)]">
                            {option.description}
                          </span>
                        ) : null}
                      </span>
                      <SelectPrimitive.ItemIndicator className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--fg-primary)]">
                        <Check size={14} strokeWidth={2.25} aria-hidden="true" />
                      </SelectPrimitive.ItemIndicator>
                    </SelectPrimitive.Item>
                  );
                })}
              </SelectPrimitive.Viewport>
            </SelectPrimitive.Content>
          </SelectPrimitive.Portal>
        </SelectPrimitive.Root>
      </>
    );
  },
);
