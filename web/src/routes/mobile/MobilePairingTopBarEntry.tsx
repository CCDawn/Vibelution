import { useState } from "react";
import { Smartphone } from "lucide-react";

import { VIconButton } from "../../components/vui/primitives/VIconButton";

import { MobilePairingDialog } from "./MobilePairingDialog";

export type MobilePairingTopBarEntryProps = {
  lang?: string;
};

/**
 * Top-bar entry point for phone pairing.
 *
 * Kept self-contained so the shell only renders one element: the button owns
 * its own open state and the dialog it controls. That keeps the shell diff to
 * an import plus one line instead of threading new state through AppShell.
 */
export function MobilePairingTopBarEntry({ lang = "zh" }: MobilePairingTopBarEntryProps) {
  const [open, setOpen] = useState(false);
  const label = lang === "en" ? "Connect a phone" : "连接手机";

  return (
    <>
      <VIconButton
        type="button"
        variant="secondary"
        onPress={() => setOpen(true)}
        label={label}
        title={label}
        icon={<Smartphone size={16} />}
      />
      <MobilePairingDialog open={open} onOpenChange={setOpen} lang={lang} />
    </>
  );
}
