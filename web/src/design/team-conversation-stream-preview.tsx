/**
 * Isolated group-chat timeline preview.
 * Open: /team-conversation-stream-preview.html
 */
import { StrictMode, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import type { ChatRoomMessage } from "../api/types";
import { VButton, VuiProvider } from "../components/vui";
import groupMessageStyles from "../routes/chat/ChatGroupMessagePresentation.styles";
import groupSurfaceStyles from "../routes/chat/ChatGroupCenterSurface.styles";
import {
  shouldCollapseGroupMessage,
  shouldDefaultCollapseGroupMessage,
} from "../routes/chat/chatRoutePresentation";
import "./base.css";
import "./tokens.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";
import "./team-conversation-stream-preview.css";
import { teamConversationStreamPreviewStyles as styles } from "./team-conversation-stream-preview.styles";
import {
  groupConsecutiveSpeakers,
  PREVIEW_SCENE_ORDER,
  PREVIEW_SCENES,
  shouldClampStreamBody,
  type PreviewMessage,
  type PreviewRound,
  type PreviewSceneId,
} from "./teamConversationStreamModel";

function readPreviewSearch(): PreviewSceneId {
  const scene = new URLSearchParams(window.location.search).get("scene");
  return scene === "consecutive" || scene === "summary" || scene === "discuss" ? scene : "discuss";
}

function asRoomMessage(message: PreviewMessage): ChatRoomMessage {
  return {
    messageId: message.id,
    audience: message.audience,
    visibility: message.visibility,
    content: message.body,
  } as ChatRoomMessage;
}

function CurrentMessageBody({
  message,
  expanded,
  onToggle,
}: {
  message: PreviewMessage;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (message.pending) {
    return <p className={groupMessageStyles.groupBubbleBody}>正在输入</p>;
  }
  const roomMessage = asRoomMessage(message);
  const defaultCollapsed = shouldDefaultCollapseGroupMessage(roomMessage);
  const collapsible = defaultCollapsed || shouldCollapseGroupMessage(message.body);
  const collapsed = collapsible && !expanded;
  const collapseLabel = defaultCollapsed ? "展开讨论" : "展开全文";
  return (
    <>
      <p className={collapsed ? `${groupMessageStyles.groupBubbleBody} ${groupMessageStyles.groupBubbleBodyCollapsed}` : groupMessageStyles.groupBubbleBody}>
        {message.body}
      </p>
      {collapsible ? (
        <VButton type="button" className={groupMessageStyles.groupBubbleToggle} onPress={onToggle}>
          {expanded ? "收起" : collapseLabel}
        </VButton>
      ) : null}
    </>
  );
}

function CurrentTimeline({
  round,
  expandedIds,
  onToggle,
}: {
  round: PreviewRound;
  expandedIds: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <div className={styles.timeline} data-testid="current-timeline">
      <div className={groupSurfaceStyles.groupRoundDivider}>
        {round.title} · {round.mode} · {round.status}
      </div>
      <div className={styles.topic}>
        <span className={styles.topicAuthor}>{round.topicAuthor}</span>
        <p>{round.topic}</p>
      </div>
      <div className={groupSurfaceStyles.groupMessageList}>
        {round.messages.map((message) => (
          <article
            key={message.id}
            className={message.pending ? `${groupSurfaceStyles.groupBubbleRow} ${groupSurfaceStyles.groupBubbleRowPending}` : groupSurfaceStyles.groupBubbleRow}
            data-testid={`current-message-${message.id}`}
          >
            <span className={groupSurfaceStyles.groupBubbleAvatar} aria-hidden="true">{message.initials}</span>
            <div className={groupSurfaceStyles.groupBubble}>
              <div className={groupSurfaceStyles.groupBubbleHeader}>
                <strong>{message.speakerName} · {message.speakerRole}</strong>
                {message.pending ? <span>正在输入</span> : null}
              </div>
              <CurrentMessageBody
                message={message}
                expanded={expandedIds.includes(message.id)}
                onToggle={() => onToggle(message.id)}
              />
              <time className={groupSurfaceStyles.groupBubbleMeta}>{message.time}</time>
            </div>
          </article>
        ))}
      </div>
      {round.digest ? (
        <article className={groupSurfaceStyles.groupRoundSummary}>
          <strong>{round.digest.title}</strong>
          <ul>
            {round.digest.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </article>
      ) : null}
    </div>
  );
}

function ProposedMessageBody({
  message,
  expanded,
  onToggle,
}: {
  message: PreviewMessage;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (message.pending) {
    return <p className={styles.pendingLine}>正在输入…</p>;
  }
  const clampable = shouldClampStreamBody(message.body);
  const clamped = clampable && !expanded;
  return (
    <>
      <p
        className={clamped ? styles.streamBodyClamp : styles.streamBody}
        data-testid={clamped ? `stream-body-clamped-${message.id}` : `stream-body-${message.id}`}
      >
        {message.body}
      </p>
      {clampable ? (
        <VButton type="button" variant="ghost" className={styles.streamToggle} onPress={onToggle}>
          {expanded ? "收起" : "展开全文"}
        </VButton>
      ) : null}
      {message.process ? (
        <details className={styles.processDisclosure} open={!message.process.settled}>
          <summary>{message.process.summary}</summary>
          <p className={styles.processDetail}>{message.process.detail}</p>
        </details>
      ) : null}
    </>
  );
}

function ProposedTimeline({
  round,
  expandedIds,
  onToggle,
}: {
  round: PreviewRound;
  expandedIds: string[];
  onToggle: (id: string) => void;
}) {
  const clusters = useMemo(() => groupConsecutiveSpeakers(round.messages), [round.messages]);
  return (
    <div className={styles.timeline} data-testid="proposed-timeline">
      <div className={styles.roundHairline} data-testid="proposed-round-hairline">
        {round.title} · {round.mode} · {round.status}
      </div>
      <div className={styles.topic}>
        <span className={styles.topicAuthor}>{round.topicAuthor}</span>
        <p>{round.topic}</p>
      </div>
      <div className={styles.streamList}>
        {clusters.map((cluster) => (
          <div key={cluster[0].id} className={styles.streamCluster} data-testid={`stream-cluster-${cluster[0].speakerId}`}>
            {cluster.map((message, index) => {
              const showIdentity = index === 0;
              return (
                <article
                  key={message.id}
                  className={styles.streamRow}
                  data-testid={`proposed-message-${message.id}`}
                >
                  {showIdentity ? (
                    <span className={styles.streamAvatar} aria-hidden="true">{message.initials}</span>
                  ) : (
                    <span className={styles.streamAvatarSpacer} aria-hidden="true" />
                  )}
                  <div className={styles.streamCopy}>
                    {showIdentity ? (
                      <div className={styles.streamHeader} data-testid="stream-speaker-header">
                        <span className={styles.streamName}>{message.speakerName}</span>
                        <span className={styles.streamRole}>{message.speakerRole}</span>
                        <time className={styles.streamTime}>{message.time}</time>
                      </div>
                    ) : (
                      <time className={styles.streamTime}>{message.time}</time>
                    )}
                    <ProposedMessageBody
                      message={message}
                      expanded={expandedIds.includes(message.id)}
                      onToggle={() => onToggle(message.id)}
                    />
                  </div>
                </article>
              );
            })}
          </div>
        ))}
      </div>
      {round.digest ? (
        <article className={styles.digest} data-testid="proposed-digest">
          <h3 className={styles.digestTitle}>{round.digest.title}</h3>
          <ul className={styles.digestList}>
            {round.digest.points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </article>
      ) : null}
    </div>
  );
}

export function TeamConversationStreamPreviewApp() {
  const [scene, setScene] = useState<PreviewSceneId>(readPreviewSearch);
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const round = PREVIEW_SCENES[scene];

  function toggleExpanded(id: string) {
    setExpandedIds((current) => (
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    ));
  }

  function selectScene(next: PreviewSceneId) {
    setScene(next);
    setExpandedIds([]);
    const url = new URL(window.location.href);
    url.searchParams.set("scene", next);
    window.history.replaceState(null, "", url);
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>隔离预览 · 群聊时间线</p>
        <h1>团队对话流：折叠卡片 vs 消息流</h1>
        <p className={styles.subtitle}>
          左边是现在的群聊房间：每条发言都是描边卡片，内部讨论默认整段藏掉。
          右边是建议：连续消息流，长文只截断前几行，过程收成一行，纪要才用卡片。
        </p>
        <div className={styles.scenes}>
          {PREVIEW_SCENE_ORDER.map((item) => (
            <VButton
              key={item.id}
              type="button"
              variant={scene === item.id ? "primary" : "ghost"}
              aria-pressed={scene === item.id}
              onPress={() => selectScene(item.id)}
            >
              {item.label}
            </VButton>
          ))}
        </div>
      </header>
      <div className={styles.layout}>
        <section className={styles.column}>
          <div className={styles.columnLabel}>现在</div>
          <div className={styles.frame}>
            <header className={styles.frameHeader}>
              <h2 className={styles.frameTitle}>{round.title}</h2>
              <p className={styles.frameMeta}>{round.mode} · {round.status} · 折叠卡片</p>
            </header>
            <CurrentTimeline round={round} expandedIds={expandedIds} onToggle={toggleExpanded} />
          </div>
        </section>
        <section className={styles.column}>
          <div className={styles.columnLabel}>建议</div>
          <div className={styles.frame}>
            <header className={styles.frameHeader}>
              <h2 className={styles.frameTitle}>{round.title}</h2>
              <p className={styles.frameMeta}>{round.mode} · {round.status} · 消息流</p>
            </header>
            <ProposedTimeline round={round} expandedIds={expandedIds} onToggle={toggleExpanded} />
          </div>
        </section>
      </div>
      <p className={styles.note}>
        隔离 mock：不调用房间 API，不改正式 Chat 路由。批准后再把建议列落到 ChatGroupCenterSurface。
      </p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <TeamConversationStreamPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
