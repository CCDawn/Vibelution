import { CircleDot } from "lucide-react";

import type { SessionRuntimeNotice } from "../../api/types";
import styles from "./ChatRuntimeNoticeStack.styles";

type ChatRuntimeNoticeStackProps = {
  lang: "zh" | "en";
  notices: SessionRuntimeNotice[];
};

export function runtimeNoticeToneClassName(level: string | undefined) {
  const normalized = String(level || "info").toLowerCase();
  if (["danger", "error", "failed"].includes(normalized)) {
    return styles.toneError;
  }
  if (["blocked", "warn", "warning"].includes(normalized)) {
    return styles.toneWarning;
  }
  if (["ok", "ready", "running", "success"].includes(normalized)) {
    return styles.toneSuccess;
  }
  if (["idle", "muted"].includes(normalized)) {
    return styles.toneMuted;
  }
  if (["tool"].includes(normalized)) {
    return styles.toneTool;
  }
  return styles.toneInfo;
}

export function runtimeNoticeIsAlert(level: string | undefined) {
  return ["blocked", "danger", "error", "failed"].includes(String(level || "").toLowerCase());
}

export function ChatRuntimeNoticeStack({ lang, notices }: ChatRuntimeNoticeStackProps) {
  if (!notices.length) {
    return null;
  }

  return (
    <div className={styles.stack} role="status" aria-live="polite">
      <div className={styles.list} role="list">
        {notices.map((notice) => (
          <div
            key={notice.id || `${notice.kind}-${notice.timestamp}-${notice.message}`}
            className={[styles.notice, runtimeNoticeToneClassName(notice.level)].join(" ")}
            role={runtimeNoticeIsAlert(notice.level) ? "alert" : "listitem"}
          >
            <CircleDot size={13} aria-hidden="true" />
            <div className={styles.body}>
              <span className={styles.label}>
                {lang === "zh" ? "运行状态" : "Runtime"}
                {notice.source ? ` · ${notice.source}` : ""}
              </span>
              <span className={styles.message}>{notice.message}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
