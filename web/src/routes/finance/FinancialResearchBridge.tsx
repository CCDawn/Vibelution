import { createContext, useContext, useEffect, useRef } from "react";
import type { AssistantConversationTurn, ConversationMessage, SessionLlmModelOption, SessionLlmOptions, SessionModelSelection } from "../../api/types";
import type { ResearchDepth } from "./stockResearchModel";

/** UI requests only. Native Session and the composer remain the authorities. */
export type FinancialDraftRequest = {
  id: number;
  sessionId: string;
  text: string;
  submit?: boolean;
  depth?: ResearchDepth;
  /** Explicit selection from the source research view; undefined keeps the target session's existing pin. */
  modelSelection?: SessionModelSelection | null;
};
export type FinancialSessionView = {
  sessionId: string;
  title: string;
  status: string;
  busy: boolean;
  stopping: boolean;
  terminalReason?: string;
  lastTurnStatus?: string;
  lastTurnTerminalTurnId?: string;
  messages?: readonly ConversationMessage[];
  phase?: string;
  error?: string;
  submitPending?: boolean;
  transcriptPending?: boolean;
  approvalPending?: boolean;
  agentId?: string;
  sessionLlmOptions?: SessionLlmOptions;
  sessionLlmOptionsLoading?: boolean;
  sessionLlmOptionsError?: boolean;
  turnModelSelection?: SessionModelSelection | null;
  onTurnModelSelectionChange?: (sessionId: string, selection: SessionModelSelection | null) => void;
};
type FinancialResearchBridgeValue = {
  agentId: string;
  draftRequest: FinancialDraftRequest | null;
  onSessionView: (view: FinancialSessionView) => void;
  onDraftSubmitted?: (id: number) => void;
  onActiveTurn?: (sessionId: string, turn: AssistantConversationTurn | null) => void;
};
export const FinancialResearchBridgeContext = createContext<FinancialResearchBridgeValue | null>(null);

const REASONING_EFFORTS = ["minimal", "low", "medium", "high", "xhigh"] as const;
const DEPTH_REASONING_EFFORT: Record<ResearchDepth, (typeof REASONING_EFFORTS)[number]> = {
  brief: "minimal",
  basic: "low",
  standard: "medium",
  detailed: "high",
  exhaustive: "xhigh",
};

type NativeModelChoiceState = SessionLlmModelOption & {
  contextWindow?: number;
  runtimeSelectable?: boolean;
  providerHealthy?: boolean;
  missingApiKey?: boolean;
};

export type FinancialResearchModelUnavailableReason =
  | "missing_context_window"
  | "not_runtime_selectable"
  | "provider_unavailable"
  | "missing_credentials";

/** Readiness fields come from the native SessionLlmOptions candidate payload. */
export function financialResearchModelUnavailableReason(
  model: SessionLlmModelOption | null | undefined,
): FinancialResearchModelUnavailableReason | null {
  if (!model) return "not_runtime_selectable";
  const nativeModel = model as NativeModelChoiceState;
  if (typeof nativeModel.contextWindow !== "number" || !Number.isFinite(nativeModel.contextWindow) || nativeModel.contextWindow <= 0) {
    return "missing_context_window";
  }
  if (nativeModel.runtimeSelectable === false) return "not_runtime_selectable";
  if (nativeModel.providerHealthy === false) return "provider_unavailable";
  if (nativeModel.missingApiKey === true) return "missing_credentials";
  return null;
}

function nativeModelChoice(
  options: SessionLlmOptions,
  modelId: string,
): SessionLlmModelOption | undefined {
  const choices = options.choices ?? [];
  return choices.find((choice) => choice.modelRef === modelId || choice.modelId === modelId);
}

/** Map requested depth to the selected model's declared reasoning choices. */
export function financialResearchModelSelection(
  depth: ResearchDepth | undefined,
  options: SessionLlmOptions | undefined,
  current: SessionModelSelection | null | undefined,
): SessionModelSelection | null {
  if (!depth || !options) return null;
  // Native validates the session-bound dialogue model before applying a
  // per-turn override, so a valid alternative cannot bypass a broken default.
  if (!options.model || financialResearchModelUnavailableReason(options.model)) return null;
  const modelId = current?.modelId || options.currentModelId;
  const model = nativeModelChoice(options, modelId) ?? (!current ? options.model ?? undefined : undefined);
  if (!model || financialResearchModelUnavailableReason(model)) return null;

  const canonicalModelId = model.modelRef || model.modelId;
  const requested = DEPTH_REASONING_EFFORT[depth];
  const declaredEfforts = model.supportsReasoningEffort
    ? new Set([...(model.reasoningEffortValues ?? []), ...(model.reasoningEffortOptions ?? []).map((option) => option.value)])
    : new Set<string>();
  const requestedIndex = REASONING_EFFORTS.indexOf(requested);
  const supported = [...REASONING_EFFORTS.slice(0, requestedIndex + 1)].reverse()
    .find((effort) => declaredEfforts.has(effort))
    ?? REASONING_EFFORTS.find((effort) => declaredEfforts.has(effort));

  // Prefer a supported effort at or below the request. If none exists, use the
  // model's lowest declared effort so Quick cannot silently become its default.
  return { modelId: canonicalModelId, ...(supported ? { reasoningEffort: supported } : {}) };
}

type PendingModelSelection = {
  requestId: number;
  sessionId: string;
  selection: SessionModelSelection | null;
  previous: SessionModelSelection | null;
  waitingForOptions: boolean;
  draftCommitted: boolean;
  blocked: boolean;
};

function sameModelSelection(left: SessionModelSelection | null | undefined, right: SessionModelSelection | null | undefined) {
  return (left?.modelId ?? "") === (right?.modelId ?? "")
    && (left?.reasoningEffort ?? "") === (right?.reasoningEffort ?? "");
}

export function useFinancialResearchSessionBridge({
  sessionId, agentId, title, status, busy, stopping, terminalReason, lastTurnStatus, lastTurnTerminalTurnId, messages, phase, error, submitPending, transcriptPending, approvalPending,
  onComposerChange, onFocusComposer, composerValue, onSubmit, sessionLlmOptions, sessionLlmOptionsLoading = false, sessionLlmOptionsError = false, turnModelSelection, onTurnModelSelectionChange,
}: FinancialSessionView & {
  agentId?: string;
  sessionLlmOptions?: SessionLlmOptions;
  sessionLlmOptionsLoading?: boolean;
  sessionLlmOptionsError?: boolean;
  turnModelSelection?: SessionModelSelection | null;
  onTurnModelSelectionChange?: (sessionId: string, selection: SessionModelSelection | null) => void;
  onComposerChange: (text: string) => void;
  onFocusComposer: (sessionId: string) => void;
  composerValue?: string;
  onSubmit?: () => void;
}) {
  const bridge = useContext(FinancialResearchBridgeContext);
  const consumedRequest = useRef<number | null>(null);
  const submittedRequest = useRef<number | null>(null);
  const pendingModelSelection = useRef<PendingModelSelection | null>(null);
  const authorized = Boolean(bridge && sessionId && agentId === bridge.agentId);
  const request = bridge?.draftRequest;
  const optionsMatchSession = sessionLlmOptions?.sessionId === sessionId;
  const currentSessionOptions = optionsMatchSession ? sessionLlmOptions : undefined;
  useEffect(() => {
    if (!authorized || !request || request.sessionId !== sessionId || consumedRequest.current === request.id) return;
    consumedRequest.current = request.id;
    const previousPending = pendingModelSelection.current;
    const previousSelection = previousPending?.sessionId === sessionId
      ? previousPending.previous
      : turnModelSelection ?? null;
    if (previousPending && previousPending.requestId !== request.id) {
      onTurnModelSelectionChange?.(previousPending.sessionId, previousPending.previous);
      pendingModelSelection.current = null;
    }
    if (request.submit && request.depth && onTurnModelSelectionChange) {
      if (sessionLlmOptionsLoading || (!sessionLlmOptionsError && !optionsMatchSession)) {
        pendingModelSelection.current = { requestId: request.id, sessionId, selection: null, previous: previousSelection, waitingForOptions: true, draftCommitted: false, blocked: false };
      } else {
        const requestedSelection = request.modelSelection === undefined ? previousSelection : request.modelSelection;
        const selection = sessionLlmOptionsError || !currentSessionOptions
          ? null
          : financialResearchModelSelection(request.depth, currentSessionOptions, requestedSelection);
        pendingModelSelection.current = { requestId: request.id, sessionId, selection, previous: previousSelection, waitingForOptions: false, draftCommitted: false, blocked: !selection };
        if (selection) {
          onTurnModelSelectionChange(sessionId, selection);
        }
      }
    }
    onComposerChange(request.text);
    onFocusComposer(sessionId);
  }, [authorized, onComposerChange, onFocusComposer, onTurnModelSelectionChange, request, sessionId, sessionLlmOptions, sessionLlmOptionsError, sessionLlmOptionsLoading, turnModelSelection]);
  useEffect(() => {
    const pending = pendingModelSelection.current;
    if (!pending?.waitingForOptions || !authorized || !request || request.id !== pending.requestId || request.sessionId !== sessionId
      || sessionLlmOptionsLoading || (!sessionLlmOptionsError && !optionsMatchSession) || !onTurnModelSelectionChange) return;
    const requestedSelection = request.modelSelection === undefined ? pending.previous : request.modelSelection;
    const selection = sessionLlmOptionsError || !currentSessionOptions
      ? null
      : financialResearchModelSelection(request.depth, currentSessionOptions, requestedSelection);
    pendingModelSelection.current = { ...pending, selection, waitingForOptions: false, blocked: !selection };
    if (selection) {
      onTurnModelSelectionChange(sessionId, selection);
    } else {
      return;
    }
  }, [authorized, currentSessionOptions, onTurnModelSelectionChange, optionsMatchSession, request, sessionId, sessionLlmOptionsError, sessionLlmOptionsLoading]);
  useEffect(() => {
    const pending = pendingModelSelection.current;
    if (!pending) return;
    const requestMatches = authorized && request?.id === pending.requestId && request.sessionId === pending.sessionId && sessionId === pending.sessionId;
    if (requestMatches && composerValue === request.text) {
      if (!pending.draftCommitted) pendingModelSelection.current = { ...pending, draftCommitted: true };
      return;
    }
    if (requestMatches && !pending.draftCommitted) return;
    pendingModelSelection.current = null;
    onTurnModelSelectionChange?.(pending.sessionId, pending.previous);
  }, [authorized, composerValue, onTurnModelSelectionChange, request, sessionId]);
  const submitted = bridge?.onDraftSubmitted;
  useEffect(() => {
    if (!authorized || !request?.submit || request.sessionId !== sessionId || submittedRequest.current === request.id
      || consumedRequest.current !== request.id || composerValue !== request.text || busy || stopping || submitPending || transcriptPending
      || (request.depth && sessionLlmOptionsLoading) || !onSubmit) return;
    const pending = pendingModelSelection.current;
    if (request.depth && (!pending || pending.requestId !== request.id || pending.waitingForOptions || pending.blocked
      || (pending.selection && !sameModelSelection(turnModelSelection, pending.selection)))) return;
    // Submit only after the native composer has committed this exact draft.
    // The native mutation remains the only writer and owns its submission gate.
    submittedRequest.current = request.id;
    try {
      onSubmit();
      submitted?.(request.id);
    } finally {
      if (pending?.requestId === request.id) {
        pendingModelSelection.current = null;
        onTurnModelSelectionChange?.(pending.sessionId, pending.previous);
      }
    }
  }, [authorized, busy, composerValue, onSubmit, onTurnModelSelectionChange, request, sessionId, sessionLlmOptionsLoading, stopping, submitPending, submitted, transcriptPending, turnModelSelection]);
  const publish = bridge?.onSessionView;
  const publishedSessionLlmOptions = optionsMatchSession ? sessionLlmOptions : undefined;
  const publishedSessionLlmOptionsLoading = sessionLlmOptionsLoading || Boolean(sessionLlmOptions && !optionsMatchSession);
  useEffect(() => {
    if (authorized) publish?.({
      sessionId, agentId, title, status, busy, stopping, terminalReason, lastTurnStatus,
      lastTurnTerminalTurnId, messages, phase, error, submitPending, transcriptPending,
      approvalPending, sessionLlmOptions: publishedSessionLlmOptions,
      sessionLlmOptionsLoading: publishedSessionLlmOptionsLoading,
      sessionLlmOptionsError, turnModelSelection: turnModelSelection ?? null,
      onTurnModelSelectionChange,
    });
  }, [agentId, approvalPending, authorized, busy, error, lastTurnStatus, lastTurnTerminalTurnId, messages, onTurnModelSelectionChange, phase, publish, publishedSessionLlmOptions, publishedSessionLlmOptionsLoading, sessionId, sessionLlmOptionsError, status, stopping, submitPending, terminalReason, title, transcriptPending, turnModelSelection]);
  return bridge !== null;
}
