import { useCallback, useEffect, useState } from "react";

import { submitResearchWorkflowCommandOffer } from "../../../api/research-workflow/commands";
import type { CommandOffer, CommandReceipt } from "../../../api/types/research-workflow/commands";

export function useResearchWorkflowCommand(
  teamId: string,
  runId: string,
  nodeId: string | null,
): {
  submit: (offer: CommandOffer) => Promise<CommandReceipt>;
  busy: boolean;
  commandError: string | null;
  clearCommandError: () => void;
} {
  const [busy, setBusy] = useState(false);
  const [commandError, setCommandError] = useState<string | null>(null);

  useEffect(() => {
    setCommandError(null);
  }, [runId, nodeId]);

  const clearCommandError = useCallback(() => {
    setCommandError(null);
  }, []);

  const submit = useCallback(
    async (offer: CommandOffer) => {
      if (!offer.available) {
        const message = offer.reasonCode || "command_unavailable";
        setCommandError(message);
        throw new Error(message);
      }
      setBusy(true);
      setCommandError(null);
      try {
        return await submitResearchWorkflowCommandOffer({ teamId, runId, offer });
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : String(reason);
        setCommandError(message);
        throw reason;
      } finally {
        setBusy(false);
      }
    },
    [runId, teamId],
  );

  return {
    submit,
    busy,
    commandError,
    clearCommandError,
  };
}
