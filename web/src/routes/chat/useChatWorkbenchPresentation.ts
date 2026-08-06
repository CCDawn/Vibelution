/**
 * Presentation helpers for Chat workbench: return navigation + locale formatters.
 * Keeps pure formatting in chatWorkbenchFormat; this hook only wires React locale deps.
 */
import { useCallback, useMemo } from "react";

import { safeAgentCenterReturnToPath } from "../agentCenterRoutes";
import { formatChatClockTime, formatChatConversationIndexTime } from "./chatWorkbenchFormat";

export function useChatReturnNavigation(locationSearch: string, lang: "zh" | "en") {
  const chatReturnTarget = useMemo(() => {
    return safeAgentCenterReturnToPath(new URLSearchParams(locationSearch).get("returnTo"));
  }, [locationSearch]);

  const chatReturnLabel = useMemo(() => {
    const raw = String(new URLSearchParams(locationSearch).get("returnLabel") || "").trim();
    if (!raw || raw.length > 80) {
      return lang === "zh" ? "返回来源" : "Back";
    }
    return raw;
  }, [lang, locationSearch]);

  return { chatReturnTarget, chatReturnLabel };
}

export function useChatLocaleFormatters(lang: "zh" | "en") {
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }),
    [locale],
  );
  const numberFormatter = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const compactNumberFormatter = useMemo(
    () => new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }),
    [locale],
  );
  const formatTime = useCallback(
    (value: string) => formatChatClockTime(value, timeFormatter),
    [timeFormatter],
  );
  const formatConversationIndexTime = useCallback(
    (value: string) => formatChatConversationIndexTime(value, timeFormatter),
    [timeFormatter],
  );
  return {
    locale,
    timeFormatter,
    numberFormatter,
    compactNumberFormatter,
    formatTime,
    formatConversationIndexTime,
  };
}
