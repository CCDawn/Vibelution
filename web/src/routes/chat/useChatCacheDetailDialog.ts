import { useCallback, useEffect, useState } from "react";

export type UseChatCacheDetailDialogOptions = {
  cacheDetailAvailable: boolean;
  activeSessionId: string | null | undefined;
};

export type UseChatCacheDetailDialogResult = {
  cacheDetailOpen: boolean;
  openCacheDetail: () => void;
  closeCacheDetail: () => void;
};

/**
 * Cache detail dialog open/close and Escape handling.
 */
export function useChatCacheDetailDialog({
  cacheDetailAvailable,
  activeSessionId,
}: UseChatCacheDetailDialogOptions): UseChatCacheDetailDialogResult {
  const [cacheDetailOpen, setCacheDetailOpen] = useState(false);
  const closeCacheDetail = useCallback(() => setCacheDetailOpen(false), []);
  const openCacheDetail = useCallback(() => {
    if (cacheDetailAvailable) {
      setCacheDetailOpen(true);
    }
  }, [cacheDetailAvailable]);

  useEffect(() => {
    if (!cacheDetailOpen) {
      return undefined;
    }
    function handleCacheDetailKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeCacheDetail();
      }
    }
    window.addEventListener("keydown", handleCacheDetailKeyDown);
    return () => window.removeEventListener("keydown", handleCacheDetailKeyDown);
  }, [cacheDetailOpen, closeCacheDetail]);

  useEffect(() => {
    setCacheDetailOpen(false);
  }, [activeSessionId]);

  return {
    cacheDetailOpen,
    openCacheDetail,
    closeCacheDetail,
  };
}
