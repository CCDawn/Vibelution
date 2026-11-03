import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ConversationMessage } from "../../api/types";
import {
  assistantFinalAnswerText,
  assistantTurnIsStreaming,
} from "../../routes/chatTurnProtocol";
import type { AgentMessageOperationGroups } from "./agentMessageOperations";
import type { AgentMessageRenderState } from "./agentMessageRenderState";
import type { AgentMessageTimelineItem } from "./agentMessageTimeline";
import {
  preserveConversationExpansionDefaults,
  shouldRefreshConversationExpansionDefault,
  type ConversationSectionExpansion,
} from "./conversationExpansionDefaults";
import { projectedConversationMessageIds } from "./conversationMessageIdentity";
import type { ResponseSegment } from "./messageResponseSegments";
import { getCachedResponseSegments as getCachedResponseSegmentsFromCache } from "./conversationResponseSegmentCache";
import type { RetiredOverlayAlias } from "./useAgentMessageTimelineProjection";

const DEFAULT_EXPANDED_RESPONSE_TAIL_COUNT = 3;
const RESPONSE_PARSE_CACHE_LIMIT = 80;
const RESPONSE_PREWARM_MESSAGE_LIMIT = 8;

/**
 * Moves explicit expansion records from retired overlay row ids onto the rows
 * that replaced them (pure; exported for tests). A target section the user
 * already toggled explicitly wins, and re-reported aliases are natural no-ops
 * because the source record moves away on the first application.
 */
export function migrateSectionExpansionRecords(
  expansion: ConversationSectionExpansion,
  aliases: ReadonlyArray<RetiredOverlayAlias>,
): ConversationSectionExpansion {
  let next: ConversationSectionExpansion | null = null;
  for (const { fromMessageId, toMessageId } of aliases) {
    if (!fromMessageId || !toMessageId || fromMessageId === toMessageId) {
      continue;
    }
    const source = (next ?? expansion)[fromMessageId];
    if (!source) {
      continue;
    }
    if (!next) {
      next = { ...expansion };
    }
    delete next[fromMessageId];
    next[toMessageId] = { ...source, ...(next[toMessageId] ?? {}) };
  }
  return next ?? expansion;
}

export type UseConversationProcessExpansionInput = {
  sessionId: string;
  timelineMessages: ConversationMessage[];
  activeTimelineMessages: ConversationMessage[];
  agentRenderStatesByMessageId: Map<string, AgentMessageRenderState>;
  agentTimelineItemsByMessageId: Map<string, AgentMessageTimelineItem[]>;
  agentOperationGroupsByMessageId: Map<string, AgentMessageOperationGroups>;
  /**
   * Overlay→durable row id pairs reported by the timeline projection when a
   * settled turn retires its live overlay rows. Explicit toggles bound to a
   * retired id migrate onto the replacing row so the user's expand choices
   * survive the live→durable identity change. Absent/empty = no-op, so
   * callers that do not project overlays keep today's behavior exactly.
   */
  retiredOverlayAliases?: ReadonlyArray<RetiredOverlayAlias>;
};

export type UseConversationProcessExpansionResult = {
  sectionExpansion: ConversationSectionExpansion;
  defaultExpandedResponseIds: Set<string>;
  preserveCurrentExpansionDefaults: () => void;
  /**
   * Clears expansion defaults, explicit toggles, and the segment cache.
   * The shell calls this from its existing sessionId effect so the clear
   * stays after timeline-follow effects and beside scroll-anchor reset.
   */
  resetSessionExpansion: () => void;
  getCachedResponseSegments: (content: string) => ResponseSegment[];
  getExpansionState: (messageId: string, section: string, defaultExpanded: boolean) => boolean;
  toggleSection: (messageId: string, section: string, defaultExpanded: boolean) => void;
};

/**
 * Expanded-response tail, section defaults, explicit toggles, response-segment
 * parse cache, and idle prewarm. Extracted from ConversationView; the shell
 * still calls this beside `useConversationTimelineFollow` and passes
 * `preserveCurrentExpansionDefaults` into that follow hook. Explicit toggles
 * follow their row across the live→durable identity change via the projection's
 * `retiredOverlayAliases`.
 */
export function useConversationProcessExpansion({
  sessionId,
  timelineMessages,
  activeTimelineMessages,
  agentRenderStatesByMessageId,
  agentTimelineItemsByMessageId,
  agentOperationGroupsByMessageId,
  retiredOverlayAliases,
}: UseConversationProcessExpansionInput): UseConversationProcessExpansionResult {
  const defaultExpansionRef = useRef<Record<string, Record<string, boolean>>>({});
  const responseSegmentCacheRef = useRef<Map<string, ResponseSegment[]>>(new Map());
  const [sectionExpansion, setSectionExpansion] = useState<ConversationSectionExpansion>({});

  const defaultExpandedResponseIds = useMemo(() => {
    const ids = new Set<string>();
    let expandedResponseCount = 0;
    for (let index = activeTimelineMessages.length - 1; index >= 0; index -= 1) {
      const message = activeTimelineMessages[index];
      const agentRenderState = agentRenderStatesByMessageId.get(message.id);
      if (!agentRenderState?.sectionState.hasResponseBlock) {
        continue;
      }
      expandedResponseCount += 1;
      ids.add(message.id);
      for (const projectedId of projectedConversationMessageIds(message)) {
        ids.add(projectedId);
      }
      if (expandedResponseCount >= DEFAULT_EXPANDED_RESPONSE_TAIL_COUNT) {
        break;
      }
    }
    return ids;
  }, [activeTimelineMessages, agentRenderStatesByMessageId]);

  const resetSessionExpansion = useCallback(() => {
    defaultExpansionRef.current = {};
    responseSegmentCacheRef.current.clear();
    setSectionExpansion({});
  }, []);

  function preserveCurrentExpansionDefaults() {
    defaultExpansionRef.current = preserveConversationExpansionDefaults({
      currentDefaults: defaultExpansionRef.current,
      sectionExpansion,
      messages: activeTimelineMessages,
      renderStatesByMessageId: agentRenderStatesByMessageId,
      timelineItemsByMessageId: agentTimelineItemsByMessageId,
      operationGroupsByMessageId: agentOperationGroupsByMessageId,
      defaultExpandedResponseIds,
    });
  }

  function getCachedResponseSegments(content: string) {
    return getCachedResponseSegmentsFromCache(
      responseSegmentCacheRef.current,
      content,
      RESPONSE_PARSE_CACHE_LIMIT,
    );
  }

  function getExpansionState(messageId: string, section: string, defaultExpanded: boolean) {
    const explicit = sectionExpansion[messageId]?.[section];
    if (explicit !== undefined) {
      return explicit;
    }
    const messageDefaults = defaultExpansionRef.current[messageId] ?? {};
    if (messageDefaults[section] === undefined) {
      defaultExpansionRef.current = {
        ...defaultExpansionRef.current,
        [messageId]: {
          ...messageDefaults,
          [section]: defaultExpanded,
        },
      };
      return defaultExpanded;
    }
    if (shouldRefreshConversationExpansionDefault(section, messageDefaults[section], defaultExpanded)) {
      defaultExpansionRef.current = {
        ...defaultExpansionRef.current,
        [messageId]: {
          ...messageDefaults,
          [section]: defaultExpanded,
        },
      };
      return defaultExpanded;
    }
    return messageDefaults[section];
  }

  function resolveExpansionState(
    expansion: ConversationSectionExpansion,
    messageId: string,
    section: string,
    defaultExpanded: boolean,
  ) {
    const explicit = expansion[messageId]?.[section];
    if (explicit !== undefined) {
      return explicit;
    }
    const messageDefaults = defaultExpansionRef.current[messageId] ?? {};
    if (messageDefaults[section] !== undefined) {
      return messageDefaults[section];
    }
    return defaultExpanded;
  }

  function toggleSection(messageId: string, section: string, defaultExpanded: boolean) {
    setSectionExpansion((current) => {
      const currentlyExpanded = resolveExpansionState(current, messageId, section, defaultExpanded);
      return {
        ...current,
        [messageId]: {
          ...(current[messageId] ?? {}),
          [section]: !currentlyExpanded,
        },
      };
    });
  }

  // Carry explicit toggles across the live→durable row identity change. The
  // migration is idempotent: once a record moves, re-reported aliases for the
  // same overlay id find no source record and bail out of the state update.
  useEffect(() => {
    if (!retiredOverlayAliases || retiredOverlayAliases.length === 0) {
      return;
    }
    setSectionExpansion((current) => migrateSectionExpansionRecords(current, retiredOverlayAliases));
  }, [retiredOverlayAliases]);

  useEffect(() => {
    const prewarmMessages = timelineMessages
      .filter(
        (message) => {
          const agentRenderState = agentRenderStatesByMessageId.get(message.id);
          return message.role === "assistant"
            && !assistantTurnIsStreaming(message)
            && Boolean(agentRenderState?.sectionState.hasResponseBlock);
        },
      )
      .slice(-RESPONSE_PREWARM_MESSAGE_LIMIT);
    if (!prewarmMessages.length) {
      return undefined;
    }
    let cancelled = false;
    let timeoutId: number | undefined;
    let index = 0;
    const prewarmNext = () => {
      if (cancelled) {
        return;
      }
      const message = prewarmMessages[index];
      if (message) {
        getCachedResponseSegments(assistantFinalAnswerText(message));
      }
      index += 1;
      if (index < prewarmMessages.length) {
        timeoutId = window.setTimeout(prewarmNext, 24);
      }
    };
    timeoutId = window.setTimeout(prewarmNext, 48);
    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [agentRenderStatesByMessageId, sessionId, timelineMessages]);

  return {
    sectionExpansion,
    defaultExpandedResponseIds,
    preserveCurrentExpansionDefaults,
    resetSessionExpansion,
    getCachedResponseSegments,
    getExpansionState,
    toggleSection,
  };
}
