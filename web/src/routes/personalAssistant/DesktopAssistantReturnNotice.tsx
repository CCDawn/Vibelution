import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchPersonalAssistant } from "../../api/personalAssistant";
import { VButton, VDialog } from "../../components/vui";
import { browserDesktopNotificationBridge, subscribeDesktopAssistantOpened } from "../chatDesktopNotifications";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import { personalAssistantReturnTarget } from "./personalAssistantModel";
import { useShellI18n } from "../../i18n/useShellI18n";

const COPY = {
  zh: {
    openFailed: "打开会话失败",
    close: "关闭",
    retry: "重试",
    identityUnavailable: "无法确认会话归属，请稍后重试。",
  },
  en: {
    openFailed: "Could not open the session",
    close: "Close",
    retry: "Retry",
    identityUnavailable: "Could not confirm the session owner. Please try again later.",
  },
} as const;

/** Main workbench subscriber. The native source is fixed; backend identity decides which existing surface owns the Session. */
export function DesktopAssistantReturnNotice() {
  const location = useLocation(), navigate = useNavigate(), route = useChatRouteSelection();
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const latest = useRef({ navigate, route, locationKey: location.key });
  latest.current = { navigate, route, locationKey: location.key };
  const epoch = useRef(0), controller = useRef<AbortController | null>(null), alive = useRef(false);
  const [failure, setFailure] = useState<{ sessionId: string; message: string } | null>(null);
  const [pending, setPending] = useState(false);
  const open = useCallback(async (sessionId: string) => {
    const requestEpoch = ++epoch.current;
    const locationKey = latest.current.locationKey;
    controller.current?.abort();
    const request = new AbortController(); controller.current = request;
    setPending(true); setFailure(null);
    const current = () => alive.current && epoch.current === requestEpoch && latest.current.locationKey === locationKey && !request.signal.aborted;
    try {
      const { assistant } = await fetchPersonalAssistant({ signal: request.signal });
      if (!current()) return;
      if (assistant?.directSessionId === sessionId) latest.current.navigate(personalAssistantReturnTarget(sessionId));
      else latest.current.route.openSession(sessionId, { surface: "chat", replace: false, telemetrySource: "desktop_assistant_overview" });
    } catch (error) {
      if (current()) setFailure({ sessionId, message: error instanceof Error ? error.message : COPY[lang].identityUnavailable });
    } finally { if (alive.current && epoch.current === requestEpoch) setPending(false); }
  }, [lang]);
  useEffect(() => {
    alive.current = true;
    const unsubscribe = subscribeDesktopAssistantOpened(browserDesktopNotificationBridge(), sessionId => { void open(sessionId); });
    return () => { alive.current = false; ++epoch.current; controller.current?.abort(); unsubscribe(); };
  }, [open]);
  useEffect(() => {
    // A user navigation supersedes pending notification results.
    ++epoch.current; controller.current?.abort(); setPending(false); setFailure(null);
  }, [location.key]);
  return <VDialog open={Boolean(failure)} title={copy.openFailed} description={failure?.message}
    onOpenChange={isOpen => { if (!isOpen) setFailure(null); }}
    footer={<><VButton variant="secondary" onClick={() => setFailure(null)}>{copy.close}</VButton>
      <VButton isPending={pending} onClick={() => { if (failure) void open(failure.sessionId); }}>{copy.retry}</VButton></>} />;
}
