import { useQuery } from "@tanstack/react-query";
import { Activity, ExternalLink, GitBranch, ScrollText } from "lucide-react";
import { useLocation } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { GitStatusSummary } from "../api/types";
import {
  VRouteLinkButton,
  VStatusChip,
  VTooltip,
  type VStatusTone,
} from "../components/vui";
import type { Language, ShellTranslationKey } from "../i18n/shellDictionary";
import { resolvePollingInterval } from "./pollingPolicy";
import type { SystemStatusTone } from "./systemStatus";
import styles from "./AppShellUtilityMenu.styles";

function gitToneToStatus(tone: SystemStatusTone): VStatusTone {
  if (tone === "running") return "success";
  if (tone === "caution") return "warning";
  if (tone === "failed") return "danger";
  return "neutral";
}

export type AppShellUtilityMenuProps = {
  lang: Language;
  t: (key: ShellTranslationKey) => string;
  frontendVisible: boolean;
  onClose: () => void;
};

function utilityNavClass(pathname: string, to: string) {
  const active = pathname === to || pathname.startsWith(`${to}/`);
  return active ? `${styles.utilityButton} ${styles.utilityButtonActive}` : styles.utilityButton;
}

export function AppShellUtilityMenu({ lang, t, frontendVisible, onClose }: AppShellUtilityMenuProps) {
  const location = useLocation();
  const gitRefetchInterval = resolvePollingInterval(frontendVisible, 6_000, { backgroundMs: 60_000 });
  const gitStatusQuery = useQuery({
    queryKey: queryKeys.gitStatusSummary(),
    queryFn: ({ signal }) => fetchJson<GitStatusSummary>("/api/git/status", { signal }),
    refetchInterval: gitRefetchInterval,
    refetchIntervalInBackground: false,
  });

  const gitStatus = gitStatusQuery.data;
  const gitAvailable = Boolean(gitStatus?.available);
  const gitDirty = Boolean(gitStatus?.dirty);
  const gitAttention = Boolean(gitStatus?.requiresAttention ?? gitDirty);
  const gitTone: SystemStatusTone = gitAvailable ? (gitAttention ? "caution" : "running") : "idle";
  const gitBranch = gitStatus?.branch || gitStatus?.headRevShort || "-";
  const gitAhead = gitStatus?.upstream?.ahead ?? 0;
  const gitLocalCommits = gitStatus?.localCommits?.total ?? gitAhead;
  const gitWorktreeCommits = gitStatus?.worktrees?.withCommits ?? 0;
  const gitDirtyCount = gitStatus?.counts.total ?? 0;
  const gitStatusLevel = gitStatus?.statusLevel ?? (gitDirty ? "dirty" : "clean");
  const gitHeroLabel = !gitAvailable
    ? gitStatusQuery.isPending
      ? t("gitChecking")
      : t("gitUnavailable")
    : gitStatusLevel === "diverged"
      ? t("gitStateDiverged")
      : gitStatusLevel === "behind"
        ? t("gitStateBehind")
        : gitLocalCommits > 0
          ? t("gitStateLocalCommits")
          : gitWorktreeCommits > 0
            ? t("gitStateWorktreeCommits")
            : gitDirtyCount > 0
              ? t("gitStateDirty")
              : t("gitStateClean");
  const gitTitle = gitAvailable
    ? `${t("gitStatus")}: ${gitStatus?.summary ?? ""}`
    : gitStatus?.error || t("gitUnavailable");
  // The chip text already carries the state; only surface an extra hint when
  // Git is unavailable or the working tree needs attention.
  const gitTooltip = !gitAvailable
    ? gitStatus?.error || t("gitUnavailable")
    : gitAttention
      ? gitStatus?.summary || ""
      : "";
  const gitRow = (
    <VRouteLinkButton
      to="/git"
      className={styles.gitSummaryRow}
      onClick={onClose}
      aria-label={gitTitle}
    >
      <GitBranch size={12} aria-hidden="true" />
      <VStatusChip tone={gitToneToStatus(gitTone)}>{gitHeroLabel}</VStatusChip>
      <span className={styles.gitSummaryBranch}>{gitBranch}</span>
    </VRouteLinkButton>
  );

  return (
    <div
      className={styles.utilityPanel}
      role="region"
      aria-label={t("topUtilityMenu")}
    >
      <VTooltip content={t("topUtilityMenuHint")} width="wide">
        <div
          className={styles.utilityPanelHeader}
          tabIndex={0}
          aria-label={`${t("topUtilityMenu")}: ${t("topUtilityMenuHint")}`}
        >
          <strong>{t("topUtilityMenu")}</strong>
        </div>
      </VTooltip>
      <div className={styles.utilityButtonGrid}>
        {/* External control surface: native anchor (not SPA Link) per VRouteLinkButton design boundary. */}
        <a href="/launcher" target="_blank" rel="noreferrer" className={styles.utilityButton} onClick={onClose}>
          <ExternalLink size={16} />
          <span>{lang === "zh" ? "启动器" : "Launcher"}</span>
        </a>
        <VTooltip content={t("usageUtilityTitle")}>
          <VRouteLinkButton
            to="/usage"
            className={utilityNavClass(location.pathname, "/usage")}
            onClick={onClose}
            icon={<Activity size={16} aria-hidden="true" />}
          >
            {t("navUsage")}
          </VRouteLinkButton>
        </VTooltip>
        <VRouteLinkButton
          to="/logs"
          className={utilityNavClass(location.pathname, "/logs")}
          onClick={onClose}
          icon={<ScrollText size={16} aria-hidden="true" />}
        >
          {t("navLogs")}
        </VRouteLinkButton>
        <VRouteLinkButton
          to="/git"
          className={utilityNavClass(location.pathname, "/git")}
          onClick={onClose}
          icon={<GitBranch size={16} aria-hidden="true" />}
        >
          {t("navGit")}
        </VRouteLinkButton>
      </div>
      {gitTooltip ? (
        <VTooltip content={gitTooltip} width="wide">
          {gitRow}
        </VTooltip>
      ) : (
        gitRow
      )}
    </div>
  );
}
