import { useCallback, useEffect, useRef, useState } from "react";

type MaybePromise<T> = T | Promise<T>;

type ChatAgentArchiveQueueOptions<TContext, TResult> = {
  onOptimisticArchive: (agentId: string) => TContext;
  executeArchive: (agentId: string) => Promise<TResult>;
  onArchiveSuccess: (agentId: string, result: TResult, context: TContext) => MaybePromise<void>;
  onArchiveFailure: (agentId: string, error: unknown, context: TContext) => MaybePromise<void>;
  onQueueDrained: () => MaybePromise<void>;
  onPendingAgentIdsChanged: (agentIds: ReadonlySet<string>) => void;
};

type ChatAgentArchiveQueueItem<TContext> = {
  agentId: string;
  context: TContext;
};

export type ChatAgentArchiveQueue<TContext> = {
  enqueue: (agentId: string) => boolean;
  pendingAgentIds: () => ReadonlySet<string>;
  whenIdle: () => Promise<void>;
};

/**
 * Accept consecutive archive intents immediately while keeping destructive
 * requests strictly FIFO. Backend lifecycle writes already serialize globally;
 * this queue prevents the browser from creating overlapping snapshot rollbacks.
 */
export function createChatAgentArchiveQueue<TContext, TResult>(
  options: ChatAgentArchiveQueueOptions<TContext, TResult>,
): ChatAgentArchiveQueue<TContext> {
  const queue: ChatAgentArchiveQueueItem<TContext>[] = [];
  const pendingAgentIds = new Set<string>();
  let draining = false;
  let idleWaiters: Array<() => void> = [];

  const notifyPendingChanged = () => {
    options.onPendingAgentIdsChanged(new Set(pendingAgentIds));
  };

  const resolveIdleWaiters = () => {
    if (draining || queue.length) {
      return;
    }
    const currentWaiters = idleWaiters;
    idleWaiters = [];
    currentWaiters.forEach((resolve) => resolve());
  };

  const drain = async () => {
    if (draining) {
      return;
    }
    draining = true;
    try {
      do {
        while (queue.length) {
          const item = queue.shift();
          if (!item) {
            break;
          }
          try {
            const result = await options.executeArchive(item.agentId);
            await options.onArchiveSuccess(item.agentId, result, item.context);
          } catch (error) {
            await options.onArchiveFailure(item.agentId, error, item.context);
          } finally {
            pendingAgentIds.delete(item.agentId);
            notifyPendingChanged();
          }
        }
        // One authoritative reconciliation for the batch. If another click is
        // queued while reconciliation is running, the same drain keeps owning it.
        await options.onQueueDrained();
      } while (queue.length);
    } finally {
      draining = false;
      if (queue.length) {
        void drain();
      } else {
        resolveIdleWaiters();
      }
    }
  };

  return {
    enqueue(rawAgentId) {
      const agentId = String(rawAgentId || "").trim();
      if (!agentId || pendingAgentIds.has(agentId)) {
        return false;
      }
      const context = options.onOptimisticArchive(agentId);
      pendingAgentIds.add(agentId);
      notifyPendingChanged();
      queue.push({ agentId, context });
      void drain();
      return true;
    },
    pendingAgentIds() {
      return new Set(pendingAgentIds);
    },
    whenIdle() {
      if (!draining && !queue.length) {
        return Promise.resolve();
      }
      return new Promise<void>((resolve) => {
        idleWaiters.push(resolve);
      });
    },
  };
}

type UseChatAgentArchiveQueueOptions<TContext, TResult> = Omit<
  ChatAgentArchiveQueueOptions<TContext, TResult>,
  "onPendingAgentIdsChanged"
>;

export function useChatAgentArchiveQueue<TContext, TResult>(
  options: UseChatAgentArchiveQueueOptions<TContext, TResult>,
) {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const mountedRef = useRef(true);
  const [pendingAgentIds, setPendingAgentIds] = useState<ReadonlySet<string>>(() => new Set());
  const queueRef = useRef<ChatAgentArchiveQueue<TContext> | null>(null);

  if (!queueRef.current) {
    queueRef.current = createChatAgentArchiveQueue<TContext, TResult>({
      onOptimisticArchive: (agentId) => optionsRef.current.onOptimisticArchive(agentId),
      executeArchive: (agentId) => optionsRef.current.executeArchive(agentId),
      onArchiveSuccess: (agentId, result, context) => (
        optionsRef.current.onArchiveSuccess(agentId, result, context)
      ),
      onArchiveFailure: (agentId, error, context) => (
        optionsRef.current.onArchiveFailure(agentId, error, context)
      ),
      onQueueDrained: () => optionsRef.current.onQueueDrained(),
      onPendingAgentIdsChanged: (agentIds) => {
        if (mountedRef.current) {
          setPendingAgentIds(new Set(agentIds));
        }
      },
    });
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const enqueueArchive = useCallback((agentId: string) => (
    queueRef.current?.enqueue(agentId) ?? false
  ), []);
  const isAgentArchivePending = useCallback((agentId: string) => (
    pendingAgentIds.has(String(agentId || "").trim())
  ), [pendingAgentIds]);

  return {
    enqueueArchive,
    isAgentArchivePending,
    pendingAgentIds,
  };
}
