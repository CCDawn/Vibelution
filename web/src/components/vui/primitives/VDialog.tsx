import { type ReactNode } from "react";

import {
  ShadcnDialog,
  type ShadcnDialogSize,
} from "../renderers/shadcn/ShadcnDialog";
import { VButton } from "./VButton";

export type VDialogSize = ShadcnDialogSize;

export type VDialogProps = {
  open?: boolean;
  /** HeroUI-era alias for controlled open. */
  isOpen?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: VDialogSize;
  className?: string;
  contentClassName?: string;
  hideClose?: boolean;
  "aria-label"?: string;
};

/**
 * Product dialog API. Implementation is Radix/shadcn under the hood.
 * Prefer this over hand-rolled fixed overlays in routes.
 */
export function VDialog(props: VDialogProps) {
  return <ShadcnDialog {...props} />;
}

export type VConfirmDialogTone = "neutral" | "danger";

export type VConfirmDialogProps = {
  open?: boolean;
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  /** Body content under the description (optional). */
  children?: ReactNode;
  tone?: VConfirmDialogTone;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmPending?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel?: () => void;
  size?: VDialogSize;
  hideClose?: boolean;
};

/**
 * Compact confirm/danger dialog with standard cancel + confirm actions.
 */
export function VConfirmDialog({
  open,
  isOpen,
  onOpenChange,
  title,
  description,
  children,
  tone = "neutral",
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  confirmPending = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
  size = "sm",
  hideClose = false,
}: VConfirmDialogProps) {
  const controlledOpen = open ?? isOpen;
  const close = () => onOpenChange?.(false);

  const footer = (
    <>
      <VButton
        type="button"
        variant="secondary"
        density="compact"
        isDisabled={confirmPending}
        onPress={() => {
          onCancel?.();
          close();
        }}
      >
        {cancelLabel}
      </VButton>
      <VButton
        type="button"
        variant={tone === "danger" ? "danger" : "primary"}
        density="compact"
        isDisabled={confirmDisabled || confirmPending}
        onPress={() => {
          onConfirm();
        }}
      >
        {confirmPending ? `${confirmLabel}…` : confirmLabel}
      </VButton>
    </>
  );

  return (
    <VDialog
      open={controlledOpen}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      size={size}
      hideClose={hideClose}
      footer={footer}
    >
      {children}
    </VDialog>
  );
}
