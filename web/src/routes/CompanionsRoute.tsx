import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Clock3, Sparkles } from "lucide-react";

import { listVirtualHumanCompanions } from "../api/agentPlugins";
import { queryKeys } from "../api/queryKeys";
import { VButton, VPage, VRouteLinkButton, VStateSurface, VStatusChip } from "../components/vui";
import { usePageVisibility } from "../app/pollingPolicy";
import { useShellI18n } from "../i18n/useShellI18n";
import { useChatRouteSelection } from "./chat/useChatRouteSelection";
import { agentCenterConfigRoute } from "./agentCenterRoutes";
import { CompanionPortrait } from "./companions/CompanionPortrait";
import {
  companionAbout,
  companionIdentity,
  currentLifeActivity,
  formatCompanionLocalTime,
  formatLifeTime,
  lifeMoodLabel,
} from "./companions/companionPresentation";
import styles from "./companions/companions.styles";

const COPY = {
  zh: {
    kicker: "Virtual humans",
    title: "人物大厅",
    subtitle: "去见一个正在生活的人。她有自己的今天，也会记得你们共同经历过的事。",
    count: "位已启用人物",
    living: "正在生活",
    paused: "生活已暂停",
    enter: "进入她的房间",
    profile: "查看人物档案",
    localTime: "她那里",
    codeRole: "PERSONAL COMPANION",
    now: "此刻正在",
    mood: "今天的心情",
    relationship: "与你的关系",
    tomorrow: "明日安排",
    relationshipEmpty: "还在慢慢熟悉",
    tomorrowEmpty: "等待今晚规划",
    loading: "正在载入人物大厅",
    loadFailed: "人物大厅暂时不可用",
    retry: "重新载入",
    empty: "还没有启用虚拟人的 Agent",
    emptyHint: "在 Agent 管理中选择一个 Agent，并在“能力绑定”里启用虚拟人生活插件。",
    manage: "前往 Agent 管理",
    footerLeft: "人物会根据自己的计划继续生活。",
    footerRight: "主动消息、历史和实时对话共用同一条原生 Session 记录。",
  },
  en: {
    kicker: "Virtual humans",
    title: "Companion lobby",
    subtitle: "Each person has a life, moods, and memories of their own. Entering opens one continuing person, not a contact list.",
    count: "enabled people",
    living: "Living now",
    paused: "Life paused",
    enter: "Enter her room",
    profile: "View profile",
    localTime: "Local time",
    codeRole: "PERSONAL COMPANION",
    now: "Living now",
    mood: "Today's mood",
    relationship: "Your relationship",
    tomorrow: "Tomorrow",
    relationshipEmpty: "Still getting acquainted",
    tomorrowEmpty: "Planning tonight",
    loading: "Loading companion lobby",
    loadFailed: "Companion lobby is unavailable",
    retry: "Retry",
    empty: "No Agent has the virtual-human plugin enabled",
    emptyHint: "Choose an Agent in Agent Management and enable Virtual Human Life under Capabilities.",
    manage: "Open Agent Management",
    footerLeft: "Person cards live only in the lobby; chat shows the current person only.",
    footerRight: "Conversation history and live streaming keep using the native Session path.",
  },
} as const;

export function CompanionsRoute() {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const { openCompanionSession } = useChatRouteSelection();
  const pageVisible = usePageVisibility();
  const companionsQuery = useQuery({
    queryKey: queryKeys.virtualHumanCompanions(),
    queryFn: listVirtualHumanCompanions,
    refetchInterval: pageVisible ? 30_000 : false,
  });
  const companions = companionsQuery.data ?? [];

  return (
    <VPage
      ariaLabel={copy.title}
      className={styles.route}
      data-vui-domain-recipe="virtual-human-companion-lobby"
    >
      <header className={styles.hero}>
        <div className={styles.heroCopy}>
          <p className={styles.kicker}>{copy.kicker}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        {!companionsQuery.isPending && !companionsQuery.isError ? (
          <div className={styles.count} aria-label={`${companions.length} ${copy.count}`}>
            <strong>{companions.length}</strong>
            <span>{copy.count}</span>
          </div>
        ) : null}
      </header>

      {companionsQuery.isPending ? (
        <div className={styles.stateHost}>
          <VStateSurface title={copy.loading} tone="loading" busy skeletonLines={3} />
        </div>
      ) : companionsQuery.isError ? (
        <div className={styles.stateHost}>
          <VStateSurface
            title={copy.loadFailed}
            tone="error"
            actions={(
              <VButton type="button" isPending={companionsQuery.isFetching} onPress={() => companionsQuery.refetch()}>
                {copy.retry}
              </VButton>
            )}
          >
            {companionsQuery.error instanceof Error ? companionsQuery.error.message : copy.loadFailed}
          </VStateSurface>
        </div>
      ) : companions.length === 0 ? (
        <div className={styles.stateHost}>
          <VStateSurface
            title={copy.empty}
            tone="empty"
            icon={<Sparkles size={15} />}
            actions={<VRouteLinkButton to="/agents">{copy.manage}</VRouteLinkButton>}
          >
            {copy.emptyHint}
          </VStateSurface>
        </div>
      ) : (
        <section className={styles.grid} aria-label={copy.title}>
          {companions.map((companion) => {
            const activity = currentLifeActivity(companion.snapshot);
            const paused = Boolean(companion.snapshot.state?.lifePaused);
            const relationship = String(companion.snapshot.state?.relationshipSummary || "").trim();
            const tomorrowCount = companion.snapshot.tomorrowSchedule?.activities.length ?? 0;
            return (
              <article
                key={companion.agentId}
                className={styles.card}
                data-companion-id={companion.agentId}
              >
                <span className={styles.cardGridLines} aria-hidden="true" />
                <div className={styles.cardCopy}>
                  <div className={styles.presenceRow}>
                    <VStatusChip tone={paused ? "warning" : "success"}>
                      {paused ? copy.paused : copy.living}
                    </VStatusChip>
                    <span className={styles.localTime}>
                      {copy.localTime} · {formatCompanionLocalTime(companion.snapshot, lang)}
                    </span>
                  </div>

                  <div className={styles.identityBlock}>
                    <p className={styles.identityCode}>{companion.agentCode} · {copy.codeRole}</p>
                    <h2>{companion.displayName}</h2>
                    <p className={styles.identity}>{companionIdentity(companion)}</p>
                    <p className={styles.about}>{companionAbout(companion)}</p>
                  </div>

                  <section className={styles.nowCard} aria-label={copy.now}>
                    <span className={styles.nowIcon} aria-hidden="true"><Clock3 size={18} /></span>
                    <span className={styles.nowCopy}>
                      <span>{copy.now}</span>
                      <strong>{activity?.title || copy.living}</strong>
                    </span>
                    <time className={styles.nowTime}>
                      {activity ? `${formatLifeTime(activity.startAt, lang)}–${formatLifeTime(activity.endAt, lang)}` : ""}
                    </time>
                  </section>

                  <div className={styles.relationshipStrip}>
                    <span><small>{copy.mood}</small><strong>{lifeMoodLabel(companion.snapshot, lang)}</strong></span>
                    <span><small>{copy.relationship}</small><strong>{relationship || copy.relationshipEmpty}</strong></span>
                    <span><small>{copy.tomorrow}</small><strong>{tomorrowCount ? `${tomorrowCount}` : copy.tomorrowEmpty}</strong></span>
                  </div>

                  <div className={styles.cardActions}>
                    <VButton
                      type="button"
                      className={styles.primaryAction}
                      onPress={() => openCompanionSession(
                        companion.directSessionId,
                        companion.agentId,
                        {
                          returnLabel: lang === "zh" ? "人物大厅" : "Companion lobby",
                          telemetrySource: "virtual_human_companion_lobby",
                        },
                      )}
                    >
                      {copy.enter}
                      <ArrowRight size={16} aria-hidden="true" />
                    </VButton>
                    <VRouteLinkButton
                      variant="secondary"
                      className={styles.secondaryAction}
                      to={agentCenterConfigRoute({
                        agentId: companion.agentId,
                        pane: "config",
                        returnTo: "/companions",
                        returnLabel: "companions",
                      })}
                    >
                      {copy.profile}
                    </VRouteLinkButton>
                  </div>
                </div>

                <CompanionPortrait companion={companion} className={styles.cardPortrait} />
              </article>
            );
          })}
        </section>
      )}

      <footer className={styles.footer}>
        <span>{copy.footerLeft}</span>
        <span>{copy.footerRight}</span>
      </footer>
    </VPage>
  );
}
