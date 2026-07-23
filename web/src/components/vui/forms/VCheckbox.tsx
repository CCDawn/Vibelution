import {
  ShadcnCheckbox,
  type ShadcnCheckboxProps,
} from "../renderers/shadcn/ShadcnCheckbox";

export type VCheckboxProps = ShadcnCheckboxProps;

/**
 * Product checkbox API. Implementation is the shadcn-style native renderer.
 * Keeps isSelected / onChange(boolean) for existing call sites.
 */
export function VCheckbox({
  density = "compact",
  "data-vui": dataVui,
  ...props
}: VCheckboxProps) {
  return <ShadcnCheckbox {...props} density={density} data-vui={dataVui ?? "checkbox"} />;
}
