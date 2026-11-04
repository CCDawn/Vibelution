import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

/** Launcher presentation only. These entries never own task or conversation state. */
export type LauncherNoticeAction = {
  id: string;
  label: string;
  run: () => unknown | Promise<unknown>;
  pending?: boolean;
  disabled?: boolean;
};
export type LauncherNotice = {
  id: string;
  kind: "connection" | "appearance" | "history" | "theme" | "delivery";
  tone: "warning" | "info";
  title: string;
  description: string;
  labels?: string[];
  details?: string;
  actions?: LauncherNoticeAction[];
};

type Publish = (owner: string, notices: LauncherNotice[]) => void;
const PublishContext = createContext<Publish | null>(null);
const NoticesContext = createContext<LauncherNotice[]>([]);

export function LauncherNotificationProvider({ children }: { children: ReactNode }) {
  const [sources, setSources] = useState<Record<string, LauncherNotice[]>>({});
  const publish = useCallback<Publish>((owner, notices) => {
    setSources(previous => {
      if (!notices.length) {
        if (!(owner in previous)) return previous;
        const next = { ...previous };
        delete next[owner];
        return next;
      }
      return { ...previous, [owner]: notices };
    });
  }, []);
  const notices = useMemo(() => Object.values(sources).flat(), [sources]);
  return <PublishContext.Provider value={publish}><NoticesContext.Provider value={notices}>
    {children}
  </NoticesContext.Provider></PublishContext.Provider>;
}

export function useLauncherNotices() {
  return useContext(NoticesContext);
}

/** A producer publishes semantic changes only; retry callbacks always read its
 * latest render so neither polling nor a session switch leaves stale actions. */
export function usePublishLauncherNotices(notices: LauncherNotice[]): boolean {
  const publish = useContext(PublishContext);
  const owner = useId();
  const current = useRef(notices);
  current.current = notices;
  const signature = JSON.stringify(notices.map(notice => ({
    ...notice, actions: notice.actions?.map(({ run: _run, ...action }) => action),
  })));
  useEffect(() => {
    if (!publish) return;
    const snapshot = current.current.map(notice => ({
      ...notice,
      id: `${owner}:${notice.id}`,
      actions: notice.actions?.map(action => ({
        ...action,
        run: () => current.current.find(candidate => candidate.id === notice.id)
          ?.actions?.find(candidate => candidate.id === action.id)?.run(),
      })),
    }));
    publish(owner, snapshot);
    return () => publish(owner, []);
  }, [owner, publish, signature]);
  return publish !== null;
}
