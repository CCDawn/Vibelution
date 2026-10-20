import { fetchResearchWorkflowSnapshot } from "../../api/research-workflow/runs";
import { submitResearchWorkflowCommandOffer } from "../../api/research-workflow/commands";
import type { CommandOffer, CommandReceipt } from "../../api/types/research-workflow/commands";
import type { HumanAttentionNotificationPayload } from "./humanAttentionNotifications";

/**
 * Human-gate inline approval for the assistant-window notice card: resolve the
 * decision through the research workflow snapshot + command-offer mechanism
 * (same authority the run panel uses), never a bespoke HTTP path. Offers are
 * matched on `resolve_human_task` + taskId + decision variant — the offer id
 * suffix (`offer:<runId>:<nodeId>:resolve_human_task:<taskId>:<decision>`) is a
 * fallback for offers whose payload does not repeat the two facts.
 */

export type HumanGateScope = {
  teamId: string;
  runId: string;
  taskId: string;
};

/** Inline buttons need all three routing facts; anything less navigates instead. */
export function humanGateScopeFor(payload: HumanAttentionNotificationPayload): HumanGateScope | null {
  const meta = payload.meta;
  if (!meta?.teamId || !meta.runId || !meta.taskId) {
    return null;
  }
  return { teamId: meta.teamId, runId: meta.runId, taskId: meta.taskId };
}

export function findHumanGateOffer(
  offers: readonly CommandOffer[],
  taskId: string,
  decision: string,
): CommandOffer | null {
  const idSuffix = `:resolve_human_task:${taskId}:${decision}`;
  for (const offer of offers) {
    if (offer.command !== "resolve_human_task") {
      continue;
    }
    const payload = offer.payload ?? {};
    const payloadTaskId = typeof payload.taskId === "string" ? payload.taskId : "";
    const payloadDecision = typeof payload.decision === "string" ? payload.decision : "";
    const rawId = (offer as { id?: unknown }).id;
    const offerId = typeof rawId === "string" ? rawId : "";
    const matchedById = Boolean(offerId) && offerId.endsWith(idSuffix);
    if (
      (payloadTaskId === taskId || matchedById)
      && (payloadDecision === decision || matchedById)
    ) {
      return offer;
    }
  }
  return null;
}

export type HumanGateSubmissionOutcome =
  | { outcome: "submitted"; receipt: CommandReceipt }
  /** The gate offer expired or was already decided; the caller navigates to the run. */
  | { outcome: "unavailable" };

export async function submitHumanGateDecision(input: {
  teamId: string;
  runId: string;
  taskId: string;
  decision: string;
  signal?: AbortSignal;
  /** Injectable for tests; defaults to the shared API client functions. */
  fetchSnapshot?: typeof fetchResearchWorkflowSnapshot;
  submitOffer?: typeof submitResearchWorkflowCommandOffer;
}): Promise<HumanGateSubmissionOutcome> {
  const fetchSnapshot = input.fetchSnapshot ?? fetchResearchWorkflowSnapshot;
  const submitOffer = input.submitOffer ?? submitResearchWorkflowCommandOffer;
  const loadOffers = async (): Promise<CommandOffer[]> => {
    const snapshot = await fetchSnapshot({
      teamId: input.teamId,
      runId: input.runId,
      signal: input.signal,
    });
    return snapshot?.commandOffers ?? [];
  };
  let offer: CommandOffer | null = null;
  try {
    offer = findHumanGateOffer(await loadOffers(), input.taskId, input.decision);
    if (!offer) {
      // Offers are already-decision-sensitive; one silent refetch before
      // falling back to navigation so a stale snapshot never blocks approval.
      offer = findHumanGateOffer(await loadOffers(), input.taskId, input.decision);
    }
  } catch {
    return { outcome: "unavailable" };
  }
  if (!offer) {
    return { outcome: "unavailable" };
  }
  const receipt = await submitOffer({
    teamId: input.teamId,
    runId: input.runId,
    offer,
    signal: input.signal,
  });
  return { outcome: "submitted", receipt };
}
