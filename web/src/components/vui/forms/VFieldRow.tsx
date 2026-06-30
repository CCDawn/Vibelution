import { CircleHelp } from "lucide-react";
import { type ReactNode } from "react";

import { VNativeButton } from "../primitives/VNativeButton";
import { VTooltip } from "../primitives/VTooltip";
import { vuiFormHelperClass, vuiFormLabelClass } from "./formClasses";

export type VFieldRowProps = {
  label: ReactNode;
  children: ReactNode;
  className?: string;
  description?: ReactNode;
  htmlFor?: string;
  tooltip?: ReactNode;
  "data-vui"?: string;
};

export function VFieldRow({
  label,
  children,
  className,
  description,
  htmlFor,
  tooltip,
  "data-vui": dataVui,
}: VFieldRowProps) {
  const labelNode = htmlFor ? (
    <label className={vuiFormLabelClass} htmlFor={htmlFor}>
      {label}
    </label>
  ) : (
    <span className={vuiFormLabelClass}>{label}</span>
  );

  return (
    <div
      data-vui={dataVui ?? "field-row"}
      className={["grid min-w-0 gap-1", className].filter(Boolean).join(" ")}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        {labelNode}
        {tooltip ? (
          <VTooltip content={tooltip}>
            <VNativeButton
              aria-label="Field details"
              data-vui="field-tooltip"
              type="button"
              className="inline-flex size-4 items-center justify-center rounded-full text-vui-fg-tertiary hover:text-vui-fg-secondary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-vui-accent-cool"
            >
              <CircleHelp size={13} strokeWidth={1.7} />
            </VNativeButton>
          </VTooltip>
        ) : null}
      </div>
      {children}
      {description ? <span className={vuiFormHelperClass}>{description}</span> : null}
    </div>
  );
}
