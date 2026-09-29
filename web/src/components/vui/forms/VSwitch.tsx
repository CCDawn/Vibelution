import {
  ShadcnSwitch,
  type ShadcnSwitchProps,
} from "../renderers/shadcn/ShadcnSwitch";

export type VSwitchProps = ShadcnSwitchProps;

/**
 * Product switch API. Implementation is the shadcn-style native renderer.
 * Keeps isSelected / onChange(boolean) for parity with VCheckbox.
 */
export function VSwitch({
  density = "compact",
  "data-vui": dataVui,
  ...props
}: VSwitchProps) {
  return <ShadcnSwitch {...props} density={density} data-vui={dataVui ?? "switch"} />;
}
