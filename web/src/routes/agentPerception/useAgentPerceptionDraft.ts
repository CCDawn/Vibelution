import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";

import {
  agentPerceptionPoliciesEqual,
  cloneAgentPerceptionPolicy,
  defaultAgentPerceptionPolicy,
} from "./agentPerceptionDraft";
import type { AgentPerceptionConfiguration, AgentPerceptionPolicy } from "./types";

type DraftState = {
  key: string;
  policyFingerprint: string;
  policy: AgentPerceptionPolicy;
  touched: boolean;
};

export type AgentPerceptionDraftState = Record<string, DraftState>;

export type AgentPerceptionDraftStore = {
  drafts: AgentPerceptionDraftState;
  setDrafts: Dispatch<SetStateAction<AgentPerceptionDraftState>>;
};

function createDraft(configuration: AgentPerceptionConfiguration, key: string): DraftState {
  const policy = cloneAgentPerceptionPolicy(configuration.policy);
  return {
    key,
    policyFingerprint: configuration.policyFingerprint,
    policy: cloneAgentPerceptionPolicy(policy),
    touched: false,
  };
}

function reconcileDraft(
  existing: DraftState,
  configuration: AgentPerceptionConfiguration,
  key: string,
): DraftState {
  if (existing.key === key) {
    return existing;
  }
  if (existing.policyFingerprint === configuration.policyFingerprint) {
    // Agent metadata can change without changing the perception policy.
    // Rebase the optimistic-concurrency token while preserving the user's draft.
    return {
      ...existing,
      key,
    };
  }
  if (
    !existing.touched
    || agentPerceptionPoliciesEqual(existing.policy, configuration.policy)
  ) {
    return createDraft(configuration, key);
  }
  // A different policy arrived while the user was editing. Keep their work
  // visible and let the panel offer an explicit reload instead of overwriting it.
  return existing;
}

function configurationKey(agentId: string, configuration: AgentPerceptionConfiguration | null) {
  if (!configuration || configuration.agentId !== agentId) {
    return "";
  }
  return [configuration.agentId, configuration.agentUpdatedAt, configuration.policyFingerprint].join(":");
}

export function useAgentPerceptionDraft(
  agentId: string,
  configuration: AgentPerceptionConfiguration | null,
  draftStore?: AgentPerceptionDraftStore,
) {
  const key = configurationKey(agentId, configuration);
  const [localDrafts, setLocalDrafts] = useState<AgentPerceptionDraftState>({});
  const drafts = draftStore?.drafts ?? localDrafts;
  const setDrafts = draftStore?.setDrafts ?? setLocalDrafts;
  const activeConfiguration = configuration?.agentId === agentId ? configuration : null;
  const activeDraft = drafts[agentId] ?? null;

  useEffect(() => {
    if (!key || !activeConfiguration) {
      return;
    }
    setDrafts((current) => {
      const existing = current[agentId];
      const next = existing
        ? reconcileDraft(existing, activeConfiguration, key)
        : createDraft(activeConfiguration, key);
      if (next === existing) {
        return current;
      }
      return { ...current, [agentId]: next };
    });
  }, [activeConfiguration, agentId, key]);

  const draft = activeDraft?.policy ?? (activeConfiguration
    ? cloneAgentPerceptionPolicy(activeConfiguration.policy)
    : defaultAgentPerceptionPolicy());
  const isReady = Boolean(key);
  const isDirty = Boolean(activeConfiguration && activeDraft && !agentPerceptionPoliciesEqual(
    draft,
    activeConfiguration.policy,
  ));
  const hasConflict = Boolean(
    activeConfiguration
    && activeDraft
    && activeDraft.policyFingerprint !== activeConfiguration.policyFingerprint
    && activeDraft.touched
    && !agentPerceptionPoliciesEqual(activeDraft.policy, activeConfiguration.policy),
  );

  const update = useCallback((updater: (current: AgentPerceptionPolicy) => AgentPerceptionPolicy) => {
    setDrafts((current) => {
      if (!key || !activeConfiguration) {
        return current;
      }
      const existing = current[agentId];
      const base = existing
        ? reconcileDraft(existing, activeConfiguration, key)
        : createDraft(activeConfiguration, key);
      const policy = updater(cloneAgentPerceptionPolicy(base.policy));
      return {
        ...current,
        [agentId]: {
          key: base.key,
          policyFingerprint: base.policyFingerprint,
          policy,
          touched: true,
        },
      };
    });
  }, [activeConfiguration, agentId, key]);

  const reset = useCallback(() => {
    if (!key || !activeConfiguration) {
      return;
    }
    setDrafts((current) => {
      return {
        ...current,
        [agentId]: createDraft(activeConfiguration, key),
      };
    });
  }, [activeConfiguration, agentId, key]);

  return useMemo(() => ({
    policy: draft,
    isDirty,
    isReady,
    hasConflict,
    update,
    reset,
  }), [draft, hasConflict, isDirty, isReady, reset, update]);
}
