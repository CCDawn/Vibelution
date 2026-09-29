import { useState } from "react";

import type { ConversationMessage } from "../../api/types";
import { VButton } from "../vui";
import { ConversationShareExportDialog } from "./ConversationShareExportDialog";

export type ConversationShareExportButtonProps = {
  sessionId: string;
  /** Settled conversation transcript used to build the turn selection list. */
  messages: ConversationMessage[];
  language?: "zh" | "en";
  isDisabled?: boolean;
};

/**
 * Conversation toolbar entry for the local HTML export (designs/product/
 * conversation.md). Owns only the dialog switch — the dialog owns selection
 * state and the export call. Not wired into ConversationView by this task;
 * the integrator renders it with the session id and the live transcript.
 */
export function ConversationShareExportButton({
  sessionId,
  messages,
  language = "zh",
  isDisabled = false,
}: ConversationShareExportButtonProps) {
  const zh = language === "zh";
  const [open, setOpen] = useState(false);
  return (
    <>
      <VButton
        data-vui="conversation-share-export-button"
        variant="ghost"
        density="compact"
        isDisabled={isDisabled}
        onPress={() => setOpen(true)}
      >
        {zh ? "导出 HTML" : "Export HTML"}
      </VButton>
      <ConversationShareExportDialog
        open={open}
        sessionId={sessionId}
        messages={messages}
        language={language}
        onOpenChange={setOpen}
      />
    </>
  );
}
