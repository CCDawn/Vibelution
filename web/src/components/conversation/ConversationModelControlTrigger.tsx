import { ChevronDown } from "lucide-react";
import { forwardRef } from "react";

import { VButton, type VButtonProps } from "../vui";
import styles from "./ConversationModelControlTrigger.styles";

type ConversationModelControlTriggerProps = Omit<
  VButtonProps,
  "children" | "icon" | "trailingIcon" | "className" | "title" | "contentLayout" | "variant" | "density"
> & {
  label: string;
  fullName?: string;
  open: boolean;
};

/** Shared presentation only; each host owns its model actions and popover. */
export const ConversationModelControlTrigger = forwardRef<
  HTMLButtonElement,
  ConversationModelControlTriggerProps
>(function ConversationModelControlTrigger({ label, fullName = label, open, ...props }, ref) {
  return (
    <VButton
      {...props}
      ref={ref}
      type="button"
      variant="ghost"
      contentLayout="plain"
      className={styles.trigger}
      aria-haspopup="dialog"
      aria-expanded={open}
      data-open={open ? "true" : "false"}
      data-vui="conversation-model-control-trigger"
      title={fullName}
    >
      <span className={styles.label}>{label}</span>
      <ChevronDown className={styles.chevron} size={12} aria-hidden="true" />
    </VButton>
  );
});
