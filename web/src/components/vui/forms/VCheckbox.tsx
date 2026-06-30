import { Checkbox, type CheckboxProps } from "@heroui/react";
import { type ReactNode } from "react";

export type VCheckboxProps = Omit<CheckboxProps, "children" | "variant"> & {
  children?: ReactNode;
  "data-vui"?: string;
};

export function VCheckbox({
  children,
  className,
  "data-vui": dataVui,
  ...props
}: VCheckboxProps) {
  return (
    <Checkbox
      {...props}
      data-vui={dataVui ?? "checkbox"}
      variant="secondary"
      className={[
        "inline-flex min-h-8 min-w-0 items-center gap-2 rounded-md",
        "border border-vui-border-subtle bg-vui-control-muted px-2 text-sm text-vui-fg-secondary shadow-none",
        "transition-colors data-[selected=true]:border-vui-accent-cool data-[selected=true]:text-vui-fg-primary",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Checkbox>
  );
}
