import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Sparkles } from "lucide-react";

import { listVirtualHumanCompanions } from "../api/agentPlugins";
import { queryKeys } from "../api/queryKeys";
import { VButton, VNativeButton, VPage, VRouteLinkButton, VStateSurface } from "../components/vui";
import { usePageVisibility } from "../app/pollingPolicy";
import { useShellI18n } from "../i18n/useShellI18n";
import { useChatRouteSelection } from "./chat/useChatRouteSelection";
import { CompanionPortrait } from "./companions/CompanionPortrait";
import {
  companionAbout,
  companionIdentity,
  currentLifeActivity,
  lifeMoodLabel,
} from "./companions/companionPresentation";
import styles from "./companions/companions.styles";

const COPY = {
  zh: {
    kicker: "Virtual humans",
    title: "人物大厅",
    subtitle: "每个人都有自己的生活、心情与记忆。进入后，你面对的是一个持续生活的人，而不是一张联系人列表。",
    count: "位已启用人物",
    living: "正在生活",
    paused: "生活已暂停",
    enter: "进入主会话",
    loading: "正在载入人物大厅",
    loadFailed: "人物大厅暂时不可用",
    retry: "重新载入",
    empty: "还没有启用虚拟人的 Agent",
    emptyHint: "在 Agent 管理中选择一个 Agent，并在“能力绑定”里启用虚拟人生活插件。",
    manage: "前往 Agent 管理",
    footerLeft: "人物卡片只存在于大厅；聊天页只展示当前人物。",
    footerRight: "对话、历史和实时流式回复继续由原生 Session 链路负责。",
  },
  en: {
    kicker: "Virtual humans",
    title: "Companion lobby",
    subtitle: "Each person has a life, moods, and memories of their own. Entering opens one continuing person, not a contact list.",
    count: "enabled people",
    living: "Living now",
    paused: "Life paused",
    enter: "Open main conversation",
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
            return (
              <VNativeButton
                key={companion.agentId}
                type="button"
                className={styles.card}
                aria-label={`${copy.enter} · ${companion.displayName}`}
                data-companion-id={companion.agentId}
                onClick={() => openCompanionSession(
                  companion.directSessionId,
                  companion.agentId,
                  {
                    returnLabel: lang === "zh" ? "人物大厅" : "Companion lobby",
                    telemetrySource: "virtual_human_companion_lobby",
                  },
                )}
              >
                <CompanionPortrait companion={companion} />
                <span className={styles.cardCopy}>
                  <span className={styles.cardNameLine}>
                    <strong>{companion.displayName}</strong>
                    <span>{paused ? copy.paused : copy.living}</span>
                  </span>
                  <span className={styles.identity}>{companionIdentity(companion)}</span>
                  <span className={styles.presence}>
                    {activity?.title || copy.living} · {lifeMoodLabel(companion.snapshot, lang)}
                  </span>
                  <span className={styles.about}>{companionAbout(companion)}</span>
                  <span className={styles.enter}>
                    <span>{copy.enter}</span>
                    <ArrowRight size={16} aria-hidden="true" />
                  </span>
                </span>
              </VNativeButton>
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
