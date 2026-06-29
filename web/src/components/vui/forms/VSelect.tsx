import { ListBox, Select, type SelectProps } from "@heroui/react";
import { type ReactNode } from "react";

import { type VuiDensity } from "../renderers/heroui/heroVariants";
import { vuiFormControlClass, vuiFormHelperClass } from "./formClasses";

export type VSelectOption = {
  id: string | number;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
};

export type VSelectProps = Omit<SelectProps<VSelectOption>, "children" | "items" | "variant"> & {
  density?: VuiDensity;
  options: VSelectOption[];
  placeholder?: string;
  "data-vui"?: string;
};

export function VSelect({
  density = "compact",
  options,
  placeholder = "Select",
  className,
  "data-vui": dataVui,
  ...props
}: VSelectProps) {
  return (
    <Select<VSelectOption>
      {...props}
      data-vui={dataVui ?? "select"}
      variant="secondary"
      className={["w-full min-w-0", className].filter(Boolean).join(" ")}
    >
      <Select.Trigger className={vuiFormControlClass(density)}>
        <Select.Value>{placeholder}</Select.Value>
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover className="border border-vui-border-subtle bg-vui-surface-card p-1 shadow-[var(--vui-shadow-soft)]">
        <ListBox<VSelectOption> items={options} className="max-h-64 min-w-44 outline-none">
          {(item) => (
            <ListBox.Item
              id={item.id}
              textValue={typeof item.label === "string" ? item.label : String(item.id)}
              isDisabled={item.disabled}
              className="rounded-md px-2 py-1.5 text-sm text-vui-fg-primary outline-none data-[focused=true]:bg-vui-control-muted data-[selected=true]:bg-vui-status-info-bg"
            >
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate">{item.label}</span>
                {item.description ? (
                  <span className={vuiFormHelperClass}>{item.description}</span>
                ) : null}
              </span>
            </ListBox.Item>
          )}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
