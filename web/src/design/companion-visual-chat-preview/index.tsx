/**
 * Isolated desktop-only companion chat preview.
 * Open: /companion-visual-chat-preview.html
 *
 * It uses deterministic mock content and never calls the Session or companion APIs.
 */
import { StrictMode, useMemo, useState, type KeyboardEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowLeft,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  CloudRain,
  Coffee,
  Headphones,
  Heart,
  Image,
  Images,
  MapPin,
  MoreHorizontal,
  Music2,
  Plus,
  Send,
  Settings,
  Smile,
  Sparkles,
  SunMedium,
} from "lucide-react";

import {
  VButton,
  VIconButton,
  VNativeTextarea,
  VStatusChip,
  VTabs,
  VuiProvider,
} from "../../components/vui";
import "../base.css";
import "../tokens.css";
import "../tailwind.css";
import "../vui-provider-theme.css";
import "../vui-native-controls.css";
import "./preview.css";
import { companionVisualChatPreviewStyles as styles } from "./index.styles";

const PORTRAIT_URL = "http://127.0.0.1:8000/api/agents/avatar-image/agent-avatar-1787891682-6f3618cf-luo-tianyi-companion.png?v=18cfde034322182c-23bb68";

type PreviewMode = "conversation" | "typing";
type LifeTab = "now" | "today" | "memory";

type PreviewMessage = {
  id: string;
  role: "companion" | "user";
  text: string;
  time: string;
  visual?: "rain";
};

const INITIAL_MESSAGES: PreviewMessage[] = [
  {
    id: "hello",
    role: "companion",
    text: "刚把今天要练的歌过了一遍。你来得正好。",
    time: "16:28",
  },
  {
    id: "user-rain",
    role: "user",
    text: "外面是不是下雨了？",
    time: "16:29",
  },
  {
    id: "rain",
    role: "companion",
    text: "嗯，刚开始下。窗边的声音很好听，我拍给你看。",
    time: "16:29",
    visual: "rain",
  },
];

function Avatar({ className, decorative = false }: { className: string; decorative?: boolean }) {
  return (
    <img
      className={className}
      src={PORTRAIT_URL}
      alt={decorative ? "" : "洛天依"}
      aria-hidden={decorative || undefined}
    />
  );
}

function ScenePostcard() {
  return (
    <div className={styles.scenePostcard} aria-label="窗边小雨场景">
      <div className={styles.sceneArt} aria-hidden="true">
        <CloudRain size={30} />
        <span />
      </div>
      <div className={styles.sceneCopy}>
        <strong>窗边的小雨</strong>
        <span>16:29 · 家</span>
      </div>
    </div>
  );
}

function ChatMessage({ message }: { message: PreviewMessage }) {
  const mine = message.role === "user";
  return (
    <article className={mine ? styles.messageRowMine : styles.messageRow} data-message-role={message.role}>
      {!mine ? <Avatar className={styles.messageAvatar} /> : null}
      <div className={styles.messageStack}>
        <div className={mine ? styles.messageBubbleMine : styles.messageBubble}>
          <p>{message.text}</p>
          {message.visual === "rain" ? <ScenePostcard /> : null}
        </div>
        <time className={styles.messageMeta}>{message.time}</time>
      </div>
    </article>
  );
}

function TypingMessage() {
  return (
    <article className={styles.messageRow} data-testid="companion-typing-row">
      <Avatar className={styles.messageAvatar} />
      <div className={styles.messageStack}>
        <div className={styles.typingBubble} aria-label="洛天依正在输入">
          <span>正在输入…</span>
          <span className={styles.typingDots} aria-hidden="true"><i /><i /><i /></span>
        </div>
      </div>
    </article>
  );
}

function PersonRail() {
  return (
    <aside className={styles.portraitRail} aria-label="洛天依人物栏">
      <div className={styles.portraitBackdrop} aria-hidden="true" />
      <div className={styles.portraitGlow} aria-hidden="true" />
      <div className={styles.portraitTopbar}>
        <VIconButton label="返回人物大厅" icon={<ArrowLeft size={16} />} variant="ghost" />
        <VIconButton label="人物设置" icon={<Settings size={16} />} variant="ghost" />
      </div>
      <Avatar className={styles.portraitImage} decorative />
      <div className={styles.portraitSummary}>
        <div className={styles.presenceLine}>
          <VStatusChip tone="success">在线</VStatusChip>
          <span>16:31</span>
        </div>
        <div className={styles.personName}>
          <h1>洛天依</h1>
          <span aria-label="心情很好">☺</span>
        </div>
        <p className={styles.personStatus}>在窗边听雨，刚练完今天的歌</p>
        <div className={styles.miniFacts}>
          <span className={styles.miniFact}><MapPin size={14} /><strong>家</strong></span>
          <span className={styles.miniFact}><Headphones size={14} /><strong>听雨</strong></span>
          <span className={styles.miniFact}><Heart size={14} /><strong>亲近</strong></span>
        </div>
      </div>
    </aside>
  );
}

function NowPanel() {
  return (
    <div className={styles.lifeTabContent} data-testid="life-panel-now">
      <article className={styles.sceneCard}>
        <div className={styles.sceneCardArt} aria-hidden="true">
          <CloudRain size={38} />
          <span />
        </div>
        <div className={styles.sceneCardCopy}>
          <span>此刻</span>
          <strong>窗边听雨</strong>
          <small><MapPin size={12} /> 家 · 小客厅</small>
        </div>
      </article>

      <div className={styles.vitalGrid} aria-label="人物状态摘要">
        <article className={styles.moodVisual}>
          <span aria-hidden="true">☺</span>
          <div><small>心情</small><strong>轻快</strong></div>
        </article>
        <article className={styles.energyVisual}>
          <div><small>体力</small><strong>72%</strong></div>
          <div className={styles.meter} role="meter" aria-label="体力 72%" aria-valuemin={0} aria-valuemax={100} aria-valuenow={72}>
            <span className={styles.meterFillEnergy} style={{ width: "72%" }} />
          </div>
          <div><small>想聊天</small><strong>86%</strong></div>
          <div className={styles.meter} role="meter" aria-label="社交意愿 86%" aria-valuemin={0} aria-valuemax={100} aria-valuenow={86}>
            <span className={styles.meterFillSocial} style={{ width: "86%" }} />
          </div>
        </article>
      </div>

      <article className={styles.nextCard}>
        <time className={styles.nextTime}>17:10</time>
        <div className={styles.nextCopy}>
          <small>接下来</small>
          <strong>泡杯热茶，整理新歌笔记</strong>
        </div>
        <Coffee size={20} aria-hidden="true" />
      </article>
    </div>
  );
}

const TODAY_ITEMS = [
  { time: "09:00", title: "晨间练声", icon: Music2, done: true },
  { time: "13:30", title: "去书店找新谱子", icon: Image, done: true },
  { time: "16:00", title: "在家练歌", icon: Headphones, done: false },
  { time: "19:40", title: "看一部老电影", icon: Sparkles, done: false },
] as const;

function TodayPanel() {
  return (
    <div className={styles.lifeTabContent} data-testid="life-panel-today">
      <div className={styles.timelineList} aria-label="今天的安排">
        {TODAY_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <article key={item.time} className={styles.timelineItem} data-complete={item.done || undefined}>
              <time>{item.time}</time>
              <span aria-hidden="true"><Icon size={15} /></span>
              <div><strong>{item.title}</strong><small>{item.done ? "已经做过" : "稍后"}</small></div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

const MEMORIES = [
  { id: "bookstore", title: "一起挑中的旧唱片", date: "8月27日", icon: Music2 },
  { id: "rain", title: "第一次聊到下雨", date: "8月24日", icon: CloudRain },
  { id: "morning", title: "你记得我的早起计划", date: "8月21日", icon: SunMedium },
] as const;

function MemoryPanel() {
  return (
    <div className={styles.lifeTabContent} data-testid="life-panel-memory">
      <div className={styles.memoryGrid} aria-label="共同回忆">
        {MEMORIES.map((memory, index) => {
          const Icon = memory.icon;
          return (
            <article key={memory.id} className={styles.memoryCard} data-memory-tone={index + 1}>
              <div className={styles.memoryArt} aria-hidden="true"><Icon size={24} /><span /></div>
              <div className={styles.memoryCopy}><strong>{memory.title}</strong><time>{memory.date}</time></div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function LifeRail({ collapsed, tab, onTabChange, onCollapsedChange }: {
  collapsed: boolean;
  tab: LifeTab;
  onTabChange: (tab: LifeTab) => void;
  onCollapsedChange: (collapsed: boolean) => void;
}) {
  if (collapsed) {
    return (
      <aside className={styles.lifeRailCollapsed} aria-label="生活快照已收起">
        <div className={styles.collapsedRail}>
          <VIconButton label="展开生活快照" icon={<ChevronLeft size={16} />} variant="ghost" onPress={() => onCollapsedChange(false)} />
          <Avatar className={styles.collapsedAvatar} />
          <VIconButton label="查看现在" icon={<Heart size={16} />} variant="ghost" onPress={() => { onTabChange("now"); onCollapsedChange(false); }} />
          <VIconButton label="查看今天" icon={<CalendarDays size={16} />} variant="ghost" onPress={() => { onTabChange("today"); onCollapsedChange(false); }} />
          <VIconButton label="查看记忆" icon={<Images size={16} />} variant="ghost" onPress={() => { onTabChange("memory"); onCollapsedChange(false); }} />
        </div>
      </aside>
    );
  }

  return (
    <aside className={styles.lifeRail} aria-label="洛天依的生活快照">
      <header className={styles.lifeHeader}>
        <div className={styles.lifeTitle}><span>生活快照</span><strong>她的今天</strong></div>
        <VIconButton label="收起生活快照" icon={<ChevronRight size={16} />} variant="ghost" onPress={() => onCollapsedChange(true)} />
      </header>
      <VTabs
        className={styles.lifeTabs}
        listClassName={styles.lifeTabList}
        triggerClassName={styles.lifeTabTrigger}
        contentClassName={styles.lifeTabContent}
        aria-label="生活快照分类"
        value={tab}
        onValueChange={(value) => onTabChange(value as LifeTab)}
        items={[
          { id: "now", label: "现在", content: <NowPanel /> },
          { id: "today", label: "今天", content: <TodayPanel /> },
          { id: "memory", label: "记忆", content: <MemoryPanel /> },
        ]}
      />
    </aside>
  );
}

export function CompanionVisualChatPreviewApp() {
  const [mode, setMode] = useState<PreviewMode>("conversation");
  const [lifeTab, setLifeTab] = useState<LifeTab>("now");
  const [lifeCollapsed, setLifeCollapsed] = useState(false);
  const [draft, setDraft] = useState("");
  const [sentMessages, setSentMessages] = useState<PreviewMessage[]>([]);
  const messages = useMemo(() => [...INITIAL_MESSAGES, ...sentMessages], [sentMessages]);

  function sendDraft() {
    const text = draft.trim();
    if (!text) return;
    setSentMessages((current) => [
      ...current,
      { id: `sent-${current.length}`, role: "user", text, time: "现在" },
    ]);
    setDraft("");
    setMode("typing");
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    sendDraft();
  }

  return (
    <main className={styles.page}>
      <header className={styles.previewHeader}>
        <div className={styles.previewTitle}>
          <p className={styles.previewKicker}>隔离桌面预览 · 不连接真实会话</p>
          <h1>让人物成为画面主体，让状态一眼看懂</h1>
          <p className={styles.previewSubtitle}>删掉身份说明、模型信息和诊断字段；保留聊天、人物、此刻与回忆。</p>
        </div>
        <div className={styles.previewControls} aria-label="预览状态">
          <VButton variant={mode === "conversation" ? "primary" : "ghost"} onPress={() => setMode("conversation")}>正常聊天</VButton>
          <VButton variant={mode === "typing" ? "primary" : "ghost"} onPress={() => setMode("typing")}>正在输入</VButton>
          <VButton variant="secondary" onPress={() => setLifeCollapsed((current) => !current)}>{lifeCollapsed ? "展开生活栏" : "收起生活栏"}</VButton>
        </div>
      </header>

      <section className={lifeCollapsed ? styles.frameCompact : styles.frame} aria-label="虚拟人聊天桌面预览">
        <PersonRail />

        <section className={styles.chat} aria-label="与洛天依的聊天">
          <header className={styles.chatHeader}>
            <div className={styles.chatIdentity}>
              <Avatar className={styles.smallAvatar} />
              <div className={styles.headerCopy}><strong>洛天依</strong><span>在线 · 刚刚还在窗边</span></div>
            </div>
            <div className={styles.headerActions}>
              <VIconButton label={lifeCollapsed ? "展开生活快照" : "收起生活快照"} icon={lifeCollapsed ? <ChevronLeft size={17} /> : <ChevronRight size={17} />} variant="ghost" onPress={() => setLifeCollapsed((current) => !current)} />
              <VIconButton label="更多" icon={<MoreHorizontal size={18} />} variant="ghost" />
            </div>
          </header>

          <div className={styles.timeline} aria-live="polite">
            <div className={styles.dayDivider}><span>今天</span></div>
            {messages.map((message) => <ChatMessage key={message.id} message={message} />)}
            {mode === "typing" ? <TypingMessage /> : null}
          </div>

          <div className={styles.composer}>
            <div className={styles.composerActions}>
              <VIconButton label="添加内容" icon={<Plus size={18} />} variant="ghost" />
            </div>
            <VNativeTextarea
              className={styles.composerInput}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="和她说点什么…"
              aria-label="发送消息"
              rows={1}
            />
            <div className={styles.composerActions}>
              <VIconButton label="表情" icon={<Smile size={18} />} variant="ghost" />
              <VIconButton label="发送" icon={<Send size={17} />} variant="primary" onPress={sendDraft} isDisabled={!draft.trim()} />
            </div>
          </div>
        </section>

        <LifeRail
          collapsed={lifeCollapsed}
          tab={lifeTab}
          onTabChange={setLifeTab}
          onCollapsedChange={setLifeCollapsed}
        />
      </section>

      <p className={styles.note}>预览边界：仅桌面端；立绘取自当前人物资产，其余内容为安全 mock。正式 `/companions`、Session、Journal、SSE 和普通 Agent 对话均未修改。</p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <CompanionVisualChatPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
