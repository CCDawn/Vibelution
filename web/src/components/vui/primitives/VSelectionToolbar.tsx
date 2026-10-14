import type { ReactNode } from "react";

import type { SelectionToolbarAnchorRect } from "../../layout/selectionToolbarPosition";
import { ShadcnSelectionToolbar } from "../renderers/shadcn/ShadcnSelectionToolbar";

export type VSelectionToolbarProps = {
  anchorRect: SelectionToolbarAnchorRect;
  ariaLabel: string;
  children: ReactNode;
  className?: string;
};

/** Non-modal selection actions; selection and action state stay with the caller. */
export function VSelectionToolbar(props: VSelectionToolbarProps) {
  return <ShadcnSelectionToolbar {...props} />;
}
