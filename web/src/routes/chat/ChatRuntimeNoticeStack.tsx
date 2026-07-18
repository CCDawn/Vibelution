import { CircleDot } from "lucide-react";

import type { SessionRuntimeNotice } from "../../api/types";
import { VErrorSummary, summarizeErrorText } from "../../components/vui";
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

function runtimeNoticeSummaryTone(
  level: string | undefined,
): "error" | "warning" | "info" {
  const normalized = String(level || "info").toLowerCase();
  if (["danger", "error", "failed"].includes(normalized)) {
    return "error";
  }
  if (["blocked", "warn", "warning"].includes(normalized)) {
    return "warning";
  }
  return "info";
}

export function ChatRuntimeNoticeStack({ lang, notices }: ChatRuntimeNoticeStackProps) {
  if (!notices.length) {
    return null;
  }

  return (
    <div className={styles.stack} role="status" aria-live="polite">
      <div className={styles.list} role="list">
        {notices.map((notice) => {
          const label = `${lang === "zh" ? "运行状态" : "Runtime"}${notice.source ? ` · ${notice.source}` : ""}`;
          const isAlert = runtimeNoticeIsAlert(notice.level);
          const message = String(notice.message || "").trim();
          const { summary, details } = summarizeErrorText(message, isAlert ? 88 : 120);
          const key = notice.id || `${notice.kind}-${notice.timestamp}-${notice.message}`;

          if (isAlert || details) {
            return (
              <div key={key} className={styles.summaryItem} role="listitem">
                <VErrorSummary
                  tone={runtimeNoticeSummaryTone(notice.level)}
                  label={label}
                  summary={summary || (lang === "zh" ? "运行异常" : "Runtime issue")}
                  details={details ?? undefined}
                  openLabel={lang === "zh" ? "详情" : "Details"}
                  closeLabel={lang === "zh" ? "收起" : "Hide"}
                />
              </div>
            );
          }

          return (
            <div
              key={key}
              className={[styles.notice, runtimeNoticeToneClassName(notice.level)].join(" ")}
              role="listitem"
            >
              <CircleDot size={13} aria-hidden="true" />
              <div className={styles.body}>
                <span className={styles.label}>{label}</span>
                <span className={styles.message}>{message}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
