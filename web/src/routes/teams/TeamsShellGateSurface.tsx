/**
 * Teams shell terminal gate surfaces: no teams / detail unavailable.
 * Keeps TeamsRoute early-return chrome out of the main workbench path.
 */
import { RefreshCw } from "lucide-react";

import {
  VButton,
  VDenseOpsPage,
  VRouteLinkButton,
  VStateSurface,
} from "../../components/vui";

export type TeamsShellGateSurfaceProps = {
  lang: "zh" | "en";
  styles: Record<string, string>;
  ariaLabel: string;
  meta: string;
  mode: "unavailable" | "detail-unavailable";
  // list unavailable
  unavailableTitle?: string;
  unavailableMessage?: string;
  unavailableDetail?: string;
  listUnavailable?: boolean;
  summaryUnavailableText?: string;
  activeTeamCount?: number | string;
  memberCount?: number | string;
  teamsFetching?: boolean;
  onRefreshTeams?: () => void;
  // detail unavailable
  detailTitle?: string;
  detailMessage?: string;
  detailDetail?: string;
  teamName?: string;
  teamId?: string;
  detailLoadMode?: string;
  detailFetching?: boolean;
  onRefreshDetail?: () => void;
};

export function TeamsShellGateSurface(props: TeamsShellGateSurfaceProps) {
  const {
    lang,
    styles,
    ariaLabel,
    meta,
    mode,
  } = props;

  return (
    <VDenseOpsPage
      className={styles.route}
      headerClassName={styles.challengeWorkspaceContextHidden}
      bodyClassName={styles.teamShellPageBody}
      data-vui-domain-recipe="teams-organization-workbench"
      data-composer="teams-shell-gate"
      ariaLabel={ariaLabel}
      eyebrow={lang === "zh" ? "团队" : "Teams"}
      title={lang === "zh" ? "团队工作台" : "Team workbench"}
      meta={meta}
      actions={null}
    >
      {mode === "unavailable" ? (
        <main className={styles.teamUnavailableSurface} aria-label={props.unavailableTitle}>
          <VStateSurface
            className={styles.teamUnavailableCard}
            title={props.unavailableTitle}
            tone={props.listUnavailable ? "error" : "empty"}
            facts={[
              {
                key: "teams",
                label: lang === "zh" ? "团队" : "Teams",
                value: props.listUnavailable ? props.summaryUnavailableText : props.activeTeamCount,
              },
              {
                key: "members",
                label: lang === "zh" ? "成员" : "Members",
                value: props.listUnavailable ? props.summaryUnavailableText : props.memberCount,
              },
              { key: "source", label: lang === "zh" ? "来源" : "Source", value: "Agent Center" },
            ]}
            actions={(
              <>
                <VButton
                  type="button"
                  variant="secondary"
                  onPress={props.onRefreshTeams}
                  isDisabled={props.teamsFetching}
                  icon={<RefreshCw size={14} />}
                >
                  {props.teamsFetching
                    ? (lang === "zh" ? "刷新中" : "Refreshing")
                    : (lang === "zh" ? "刷新" : "Refresh")}
                </VButton>
                <VRouteLinkButton to="/agents" variant="primary">
                  {lang === "zh" ? "前往 Agent Center 创建团队" : "Create a team in Agent Center"}
                </VRouteLinkButton>
              </>
            )}
          >
            {props.unavailableDetail || props.unavailableMessage}
            {!props.listUnavailable ? (
              <span>
                {lang === "zh"
                  ? "团队由 Agent Center 统一创建与管理，创建后此处会自动列出。"
                  : "Teams are created and managed in Agent Center; they appear here once created."}
              </span>
            ) : null}
          </VStateSurface>
        </main>
      ) : (
        <main className={styles.teamUnavailableSurface} aria-label={props.detailTitle}>
          <VStateSurface
            className={styles.teamUnavailableCard}
            title={props.detailTitle}
            tone="unavailable"
            facts={[
              { key: "team", label: lang === "zh" ? "团队" : "Team", value: props.teamName ?? props.teamId },
              { key: "detail", label: lang === "zh" ? "详情" : "Details", value: props.detailLoadMode },
              { key: "status", label: lang === "zh" ? "状态" : "Status", value: lang === "zh" ? "失败" : "failed" },
            ]}
            actions={(
              <VButton
                type="button"
                variant="secondary"
                onPress={props.onRefreshDetail}
                isDisabled={props.detailFetching}
                icon={<RefreshCw size={14} />}
              >
                {props.detailFetching
                  ? (lang === "zh" ? "刷新中" : "Refreshing")
                  : (lang === "zh" ? "刷新详情" : "Refresh details")}
              </VButton>
            )}
          >
            {props.detailDetail || props.detailMessage}
          </VStateSurface>
        </main>
      )}
    </VDenseOpsPage>
  );
}
