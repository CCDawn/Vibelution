import { StrictMode, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Apple,
  ArrowUpRight,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  FileText,
  HeartHandshake,
  ImagePlus,
  MessageCircleHeart,
  MessageSquare,
  Plus,
  RotateCcw,
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Trash2,
  UsersRound,
  X,
} from "lucide-react";

import {
  VButton,
  VConfirmDialog,
  VDialog,
  VNativeInput,
  VNativeTextarea,
  VPopover,
  VuiProvider,
} from "../components/vui";
import "./base.css";
import "./tokens.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";
import "./chat-composer-plus-menu-preview.css";
import { chatComposerPlusMenuPreviewStyles as styles } from "./chat-composer-plus-menu-preview.styles";

type Scene = "direct" | "group";
type TurnKind = "user" | "assistant";

type Turn = {
  id: string;
  kind: TurnKind;
  author: string;
  text: string;
  streaming?: boolean;
};

type PlusMenuItem = {
  id: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  toggle?: boolean;
  active?: boolean;
  onSelect?: () => void;
};

type PlusMenuCluster = {
  id: string;
  label: string;
  icon: ReactNode;
  items: PlusMenuItem[];
};

type SlashTokenContext = {
  query: string;
  start: number;
  end: number;
};

function parseSlashToken(value: string): SlashTokenContext | null {
  const match = value.match(/(?:^|\s)(\/[^\s]*)$/);
  if (!match?.[1]) {
    return null;
  }
  const token = match[1];
  const start = value.length - token.length;
  return { query: token.slice(1), start, end: value.length };
}

type ReferenceKind = "session" | "file";

type ReferenceItem = {
  id: string;
  kind: ReferenceKind;
  title: string;
};

type ReferenceOption = {
  id: string;
  title: string;
  meta: string;
};

const SESSION_REFERENCES: ReferenceOption[] = [
  { id: "session-review", title: "代码审查 · 今天", meta: "直接会话 · 4 条消息" },
  { id: "session-refactor", title: "重构讨论 · 昨天", meta: "直接会话 · 9 条消息" },
  { id: "session-extract", title: "资料提炼 · 08/08", meta: "直接会话 · 12 条消息" },
];

const FILE_REFERENCES: ReferenceOption[] = [
  { id: "file-login", title: "src/login/LoginPage.tsx", meta: "登录页源码" },
  { id: "file-tokens", title: "src/design/tokens.css", meta: "设计令牌" },
  { id: "file-composer", title: "src/components/conversation/ConversationView.tsx", meta: "会话视图" },
];

const SLASH_COMMANDS = [
  { command: "/review", label: "代码审查", description: "审查最近改动" },
  { command: "/test", label: "补充测试", description: "为改动补齐测试" },
  { command: "/summarize", label: "总结会话", description: "生成会话摘要" },
  { command: "/patch", label: "生成补丁", description: "生成代码补丁" },
  { command: "/focus", label: "聚焦上下文", description: "压缩当前上下文" },
];

const DIRECT_TRANSCRIPT: Turn[] = [
  { id: "d-u1", kind: "user", author: "我", text: "把登录页改成暗色，并补上失败提示。" },
  { id: "d-a1", kind: "assistant", author: "gpt", text: "已开始处理：正在调整 LoginPage 的背景、错误提示与按钮对比度。" },
  { id: "d-a2", kind: "assistant", author: "gpt", text: "当前轮进行中：模型输出预算与进度已注入上下文。", streaming: true },
];

const GROUP_TRANSCRIPT: Turn[] = [
  { id: "g-u1", kind: "user", author: "我", text: "这周集中讨论缓存命中与上下文占用。" },
  { id: "g-a1", kind: "assistant", author: "gpt", text: "评审安排：先看缓存命中分布，再核对上下文占用与压缩阈值。" },
  { id: "g-a2", kind: "assistant", author: "terra", text: "补充：缓存明细已就绪，建议本轮结束后统一调整预设。" },
];

const DIRECT_SESSION = {
  title: "代码审查 · 今天",
  modelLabel: "Relay GPT-5.6 Luna",
  permissionLabel: "标准读写",
  usagePercent: 42,
  hitPercent: 67,
  cacheLabel: "5.2k tokens 命中",
};

const GROUP_SESSION = {
  title: "产品周会 · 团队讨论",
  modelLabel: "Relay GPT-5.6 Luna",
  permissionLabel: "标准读写",
  usagePercent: 38,
  hitPercent: 71,
  cacheLabel: "6.1k tokens 命中",
};

const GROUP_META = {
  name: "产品周会",
  modeLabel: "round_robin · 轮询",
  purposeLabel: "discussion · 讨论",
  members: ["gpt", "terra", "DeepSeek flash"],
};

const COMPANION = {
  name: "泡泡",
  level: 12,
  preset: "灵猫",
  line: "今天陪你处理了 3 个会话。",
};

function readPreviewScene(): Scene {
  const params = new URLSearchParams(window.location.search);
  return params.get("scene") === "group" ? "group" : "direct";
}

export function ChatComposerPlusMenuPreviewApp() {
  const [scene, setScene] = useState<Scene>(readPreviewScene);
  const [sessionBusy, setSessionBusy] = useState(scene === "direct");
  const [mentalEnabled, setMentalEnabled] = useState(scene === "direct");
  const [runtimeEnabled, setRuntimeEnabled] = useState(true);
  const [draft, setDraft] = useState("");
  const [plusOpen, setPlusOpen] = useState(false);
  const [plusActiveCluster, setPlusActiveCluster] = useState<string | null>(null);
  const [plusHoverCluster, setPlusHoverCluster] = useState<string | null>(null);
  const [statusRailOpen, setStatusRailOpen] = useState(false);
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [referencePicker, setReferencePicker] = useState<ReferenceKind | null>(null);
  const [referenceQuery, setReferenceQuery] = useState("");
  const [references, setReferences] = useState<ReferenceItem[]>([]);
  const [slashDismissed, setSlashDismissed] = useState(false);
  const [groupNameDraft, setGroupNameDraft] = useState(GROUP_META.name);
  const [feedback, setFeedback] = useState("");

  const plusCloseTimerRef = useRef<number | null>(null);

  const session = scene === "direct" ? DIRECT_SESSION : GROUP_SESSION;
  const transcript = scene === "direct" ? DIRECT_TRANSCRIPT : GROUP_TRANSCRIPT;
  const stateLabel = sessionBusy ? "进行中" : "空闲";
  const contextRingLabel = `上下文占用 ${session.usagePercent}%，命中 ${session.hitPercent}%`;
  const slashToken = useMemo(() => parseSlashToken(draft), [draft]);
  const slashPaletteOpen = slashToken !== null && !slashDismissed;
  const filteredSlashCommands = useMemo(() => {
    if (!slashToken) {
      return [];
    }
    const query = slashToken.query.trim().toLowerCase();
    return SLASH_COMMANDS.filter((command) => {
      const commandBody = command.command.slice(1).toLowerCase();
      const haystack = `${commandBody} ${command.label} ${command.description}`.toLowerCase();
      return query.length === 0 || commandBody.startsWith(query) || haystack.includes(query);
    });
  }, [slashToken]);

  useEffect(() => {
    setSlashDismissed(false);
  }, [slashToken?.query, slashToken?.start]);

  function clearPlusCloseTimer() {
    if (plusCloseTimerRef.current !== null) {
      window.clearTimeout(plusCloseTimerRef.current);
      plusCloseTimerRef.current = null;
    }
  }

  function schedulePlusHoverClose() {
    clearPlusCloseTimer();
    plusCloseTimerRef.current = window.setTimeout(() => {
      setPlusHoverCluster(null);
    }, 180);
  }

  function openPlusCluster(clusterId: string) {
    clearPlusCloseTimer();
    setPlusHoverCluster(clusterId);
  }

  function applyScene(next: Scene) {
    setScene(next);
    setPlusOpen(false);
    setPlusActiveCluster(null);
    setPlusHoverCluster(null);
    setGroupDialogOpen(false);
    setConfirmResetOpen(false);
    setConfirmDeleteOpen(false);
    setReferencePicker(null);
    setReferenceQuery("");
    setReferences([]);
    setSlashDismissed(false);
    setFeedback("");
    setDraft("");
    setGroupNameDraft(GROUP_META.name);
    if (next === "direct") {
      setSessionBusy(true);
      setMentalEnabled(true);
      setRuntimeEnabled(true);
    } else {
      setSessionBusy(false);
      setMentalEnabled(false);
      setRuntimeEnabled(true);
    }
  }

  function sendMockMessage() {
    const text = draft.trim() || "（空消息）";
    setDraft("");
    setSlashDismissed(false);
    setFeedback(`已模拟发送：${text}`);
    if (!sessionBusy) {
      setSessionBusy(true);
    }
  }

  function stopMockTurn() {
    setSessionBusy(false);
    setFeedback("已模拟停止当前轮；队列内容保持不变");
  }

  function toggleMental() {
    setMentalEnabled((current) => !current);
  }

  function toggleRuntime() {
    setRuntimeEnabled((current) => !current);
  }

  function runSimulated(label: string) {
    setPlusOpen(false);
    setPlusActiveCluster(null);
    setPlusHoverCluster(null);
    setFeedback(label);
  }

  function openGroupManage() {
    setGroupDialogOpen(true);
    setPlusOpen(false);
    setPlusActiveCluster(null);
    setPlusHoverCluster(null);
  }

  function openReferencePicker(kind: ReferenceKind) {
    setReferenceQuery("");
    setReferencePicker(kind);
    setPlusOpen(false);
    setPlusActiveCluster(null);
    setPlusHoverCluster(null);
  }

  function chooseReference(kind: ReferenceKind, option: ReferenceOption) {
    const id = `${kind}-${option.id}`;
    const alreadyAdded = references.some((item) => item.id === id);
    setReferenceQuery("");
    setReferencePicker(null);
    const kindLabel = kind === "session" ? "会话" : "工作区文件";
    if (alreadyAdded) {
      setFeedback(`「${option.title}」已在引用中，未重复添加（模拟）`);
      return;
    }
    setReferences((current) => [...current, { id, kind, title: option.title }]);
    setFeedback(`已引用${kindLabel}：${option.title}（模拟）`);
  }

  function removeReference(id: string) {
    setReferences((current) => current.filter((item) => item.id !== id));
  }

  function chooseSlashCommand(command: string) {
    if (!slashToken) {
      return;
    }
    const replacement = `${command} `;
    setDraft(`${draft.slice(0, slashToken.start)}${replacement}${draft.slice(slashToken.end)}`);
    setSlashDismissed(true);
    setFeedback(`已插入斜杠指令：${command}（模拟）`);
  }

  function handleDraftChange(value: string) {
    setDraft(value);
  }

  function handleDraftKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Escape" && slashPaletteOpen) {
      event.preventDefault();
      setSlashDismissed(true);
    }
  }

  const referenceOptions = referencePicker === "session" ? SESSION_REFERENCES : FILE_REFERENCES;
  const filteredReferenceOptions = referenceOptions.filter((option) =>
    `${option.title} ${option.meta}`.toLowerCase().includes(referenceQuery.trim().toLowerCase()),
  );

  function confirmDestructive(action: "reset" | "delete") {
    const msg = action === "reset" ? "已重置群聊消息（模拟完成）" : "已删除群聊（模拟完成）";
    setConfirmResetOpen(false);
    setConfirmDeleteOpen(false);
    setFeedback(msg);
  }

  const plusClusters: PlusMenuCluster[] = [
    {
      id: "add-reference",
      label: "添加与引用",
      icon: <ImagePlus size={16} />,
      items: [
        {
          id: "attach-image",
          label: "图片附件",
          hint: "粘贴或选择图片",
          icon: <ImagePlus size={15} />,
          onSelect: () => runSimulated("已模拟选择图片附件"),
        },
        {
          id: "reference-session",
          label: "引用会话",
          hint: "选择历史会话加入引用",
          icon: <MessageSquare size={15} />,
          onSelect: () => openReferencePicker("session"),
        },
        {
          id: "reference-file",
          label: "引用工作区文件",
          hint: "选择工作区文件加入引用",
          icon: <FileText size={15} />,
          onSelect: () => openReferencePicker("file"),
        },
      ],
    },
    {
      id: "conversation-capabilities",
      label: "对话能力",
      icon: <BrainCircuit size={16} />,
      items: [
        {
          id: "mental-model",
          label: "心智模型",
          hint: "下轮生效",
          icon: <BrainCircuit size={15} />,
          toggle: true,
          active: mentalEnabled,
          onSelect: toggleMental,
        },
        {
          id: "runtime-injection",
          label: "运行状态注入",
          hint: "把预算/进度注入上下文",
          icon: <Activity size={15} />,
          toggle: true,
          active: runtimeEnabled,
          onSelect: toggleRuntime,
        },
      ],
    },
    {
      id: "session-companion",
      label: "会话与陪伴",
      icon: <MessageCircleHeart size={16} />,
      items: [
        {
          id: "open-direct-session",
          label: "打开直接会话",
          hint: DIRECT_SESSION.title,
          icon: <ArrowUpRight size={15} />,
          onSelect: () => runSimulated(`已跳转到直接会话：${DIRECT_SESSION.title}（模拟）`),
        },
        {
          id: "companion-feed",
          label: "陪伴投喂",
          hint: `${COMPANION.name} 喂食`,
          icon: <Apple size={15} />,
          onSelect: () => runSimulated(`陪伴·投喂：${COMPANION.name} 觉得很开心（模拟）`),
        },
        {
          id: "companion-talk",
          label: "陪伴聊天",
          hint: `${COMPANION.name} 聊聊近况`,
          icon: <MessageCircleHeart size={15} />,
          onSelect: () => runSimulated(`陪伴·聊天：${COMPANION.name} 回复了一条心情（模拟）`),
        },
        {
          id: "companion-care",
          label: "陪伴关怀",
          hint: `${COMPANION.name} 健康关怀`,
          icon: <HeartHandshake size={15} />,
          onSelect: () => runSimulated(`陪伴·关怀：${COMPANION.name} 状态良好（模拟）`),
        },
      ],
    },
    ...(scene === "group"
      ? [
          {
            id: "group-team",
            label: "群聊与团队",
            icon: <UsersRound size={16} />,
            items: [
              {
                id: "group-manage",
                label: "管理群聊",
                hint: GROUP_META.name,
                icon: <Settings2 size={15} />,
                onSelect: openGroupManage,
              },
              {
                id: "open-team",
                label: "打开团队",
                hint: "team-research",
                icon: <UsersRound size={15} />,
                onSelect: () => runSimulated("已打开团队：team-research（模拟）"),
              },
            ],
          },
        ]
      : []),
  ];

  const visiblePlusCluster = plusClusters.find(
    (cluster) => cluster.id === (plusHoverCluster ?? plusActiveCluster),
  ) ?? null;

  function renderPlusClusterItem(item: PlusMenuItem) {
    if (item.toggle) {
      const active = item.active ?? false;
      return (
        <VButton
          key={item.id}
          role="menuitemcheckbox"
          aria-checked={active}
          aria-label={`${item.label}：${active ? "开启" : "关闭"}`}
          className={styles.menuToggleRow}
          contentLayout="plain"
          variant="ghost"
          icon={item.icon}
          onPress={item.onSelect}
        >
          <span className={styles.menuItemCopy}>
            <strong>{item.label}</strong>
            {item.hint ? <small className={styles.menuItemHint}>{item.hint}</small> : null}
          </span>
          <span className={`${styles.menuToggleValue} ${active ? styles.menuToggleValueOn : ""}`}>
            {active ? "开启" : "关闭"}
          </span>
        </VButton>
      );
    }

    return (
      <VButton
        key={item.id}
        role="menuitem"
        aria-label={item.label}
        className={styles.menuItem}
        contentLayout="plain"
        variant="ghost"
        icon={item.icon}
        onPress={item.onSelect}
      >
        <span className={styles.menuItemCopy}>
          <strong>{item.label}</strong>
          {item.hint ? <small className={styles.menuItemHint}>{item.hint}</small> : null}
        </span>
      </VButton>
    );
  }

  return (
    <main
      className={styles.page}
      data-composer-plus-preview="true"
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>CHAT · 隔离审批预览</p>
          <h1>Composer 加号菜单</h1>
          <p className={styles.subtitle}>
            将原右侧状态栏动作收敛到输入框左下角的「+」菜单；模型、权限、上下文与发送/停止保留在菜单外。
            状态栏保持只读并在桌面端默认折叠为细条，可经顶栏展开查看快照。
          </p>
        </div>
        <div className={styles.headerActions}>
          <VButton variant="secondary" density="compact" className={styles.chip} onPress={() => applyScene("direct")}>
            直接会话
          </VButton>
          <VButton variant="secondary" density="compact" className={styles.chip} onPress={() => applyScene("group")}>
            群聊会话
          </VButton>
          <VButton
            variant="secondary"
            density="compact"
            className={styles.chip}
            aria-pressed={statusRailOpen}
            onPress={() => setStatusRailOpen((open) => !open)}
          >
            状态栏
          </VButton>
        </div>
      </header>

      {feedback ? (
        <div className={styles.feedback} role="status">
          {feedback}
        </div>
      ) : null}

      <div className={styles.workspace} data-rail-open={statusRailOpen ? "true" : "false"}>
        <section className={styles.conversation}>
          <div className={styles.chatTopbar}>
            <span className={styles.chatTopbarTitle}>{session.title}</span>
            <span
              className={`${styles.chatStatePill} ${sessionBusy ? styles.chatStatePillRunning : styles.chatStatePillReady}`}
              role="status"
            >
              {stateLabel}
            </span>
            <span className={styles.railAffordance} aria-hidden="true">
              {scene === "direct" ? "直接会话 · 只读状态" : "群聊会话 · 只读状态"}
            </span>
          </div>

          <div className={styles.transcript} aria-label="模拟对话">
            {transcript.map((turn) => (
              <article
                key={turn.id}
                className={`${styles.turn} ${turn.kind === "user" ? styles.turnUser : styles.turnAssistant}`}
              >
                {turn.kind === "assistant" ? <span className={styles.avatar}>{turn.author.slice(0, 1).toUpperCase()}</span> : null}
                <div className={styles.bubble}>
                  <div>{turn.text}</div>
                  {turn.streaming ? <div className={styles.streaming}>当前轮进行中</div> : null}
                </div>
                {turn.kind === "user" ? <span className={styles.avatar}>我</span> : null}
              </article>
            ))}
          </div>

          <div className={styles.composer}>
            {references.length ? (
              <div className={styles.referenceRow} aria-label="待发送引用">
                {references.map((ref) => (
                  <span key={ref.id} className={styles.referenceChip}>
                    <span className={styles.referenceChipKind}>
                      {ref.kind === "session" ? "会话" : "文件"}
                    </span>
                    <span className={styles.referenceChipLabel}>{ref.title}</span>
                    <VButton
                      isIconOnly
                      variant="ghost"
                      density="compact"
                      className={styles.referenceChipRemove}
                      aria-label={`移除引用：${ref.kind === "session" ? "会话" : "文件"} · ${ref.title}`}
                      icon={<X size={12} />}
                      onPress={() => removeReference(ref.id)}
                    />
                  </span>
                ))}
              </div>
            ) : null}
            <div className={styles.composerFieldWrap}>
              {slashPaletteOpen ? (
                <div
                  className={styles.slashPalette}
                  role="listbox"
                  aria-label="斜杠指令"
                  onMouseDown={(event) => event.preventDefault()}
                >
                  {filteredSlashCommands.length ? (
                    filteredSlashCommands.map((command) => (
                      <VButton
                        key={command.command}
                        role="option"
                        aria-selected={false}
                        aria-label={command.command}
                        contentLayout="plain"
                        variant="ghost"
                        className={styles.slashPaletteItem}
                        onPress={() => chooseSlashCommand(command.command)}
                      >
                        <span className={styles.slashPaletteMark} aria-hidden="true">/</span>
                        <span className={styles.slashPaletteCopy}>
                          <strong>{command.command.slice(1)}</strong>
                          <small>{command.label} · {command.description}</small>
                        </span>
                      </VButton>
                    ))
                  ) : (
                    <p className={styles.slashPaletteEmpty}>没有匹配的指令。</p>
                  )}
                </div>
              ) : null}
              <div className={styles.composerField}>
                <VNativeTextarea
                  className={styles.composerInput}
                  value={draft}
                  placeholder="描述下一步要做什么..."
                  aria-label="发送消息"
                  onChange={(event) => handleDraftChange(event.target.value)}
                  onKeyDown={handleDraftKeyDown}
                />
              </div>
            </div>
            <div className={styles.composerToolbar}>
              <div className={styles.composerToolbarStart}>
                <div className={styles.plusRow}>
                  <VPopover
                    open={plusOpen}
                    onOpenChange={(open) => {
                      setPlusOpen(open);
                      if (!open) {
                        setPlusActiveCluster(null);
                        setPlusHoverCluster(null);
                        clearPlusCloseTimer();
                      }
                    }}
                    side="top"
                    align="start"
                    sideOffset={10}
                    aria-label="更多操作"
                    contentClassName={styles.plusMenu}
                    trigger={(
                      <VButton
                        className={styles.plusTrigger}
                        isIconOnly
                        variant="secondary"
                        aria-label="更多操作"
                        icon={<Plus size={16} />}
                      />
                    )}
                  >
                    <div
                      className={styles.plusMenuShell}
                      role="menu"
                      aria-label="更多操作菜单"
                      onMouseLeave={schedulePlusHoverClose}
                    >
                      <div className={styles.plusMenuPrimary}>
                        {plusClusters.map((cluster) => {
                          const expanded = visiblePlusCluster?.id === cluster.id;
                          return (
                            <VButton
                              key={cluster.id}
                              role="menuitem"
                              aria-haspopup="menu"
                              aria-expanded={expanded}
                              aria-label={cluster.label}
                              className={`${styles.menuClusterRow} ${expanded ? styles.menuClusterRowActive : ""}`}
                              contentLayout="plain"
                              variant="ghost"
                              onPress={() => {
                                setPlusActiveCluster((current) => (current === cluster.id ? null : cluster.id));
                                openPlusCluster(cluster.id);
                              }}
                              onMouseEnter={() => {
                                openPlusCluster(cluster.id);
                              }}
                            >
                              <span data-slot="cluster-icon" aria-hidden="true">
                                {cluster.icon}
                              </span>
                              <span className={styles.menuItemCopy}>
                                <strong>{cluster.label}</strong>
                              </span>
                              <ChevronRight className={styles.menuClusterChevron} size={15} aria-hidden="true" />
                            </VButton>
                          );
                        })}
                      </div>
                      {visiblePlusCluster ? (
                        <div
                          className={styles.menuSubmenuFlyout}
                          role="group"
                          aria-label={visiblePlusCluster.label}
                          onMouseEnter={() => {
                            clearPlusCloseTimer();
                            setPlusHoverCluster(visiblePlusCluster.id);
                          }}
                          onMouseLeave={schedulePlusHoverClose}
                        >
                          {visiblePlusCluster.items.map((item) => renderPlusClusterItem(item))}
                        </div>
                      ) : null}
                    </div>
                  </VPopover>
                </div>
              </div>
              <div className={styles.composerToolbarEnd}>
                <VButton
                  variant="ghost"
                  density="compact"
                  className={styles.toolbarControl}
                  aria-label={`模型：${session.modelLabel}`}
                  onPress={() => setFeedback("模型选择器（模拟）：打开模型列表")}
                >
                  模型 · {session.modelLabel}
                </VButton>
                <VButton
                  variant="ghost"
                  density="compact"
                  className={styles.toolbarControl}
                  icon={<ShieldCheck size={14} />}
                  aria-label={`权限预设：${session.permissionLabel}`}
                  onPress={() => setFeedback("权限预设（模拟）：标准读写")}
                >
                  {session.permissionLabel}
                </VButton>
                <VButton
                  variant="ghost"
                  density="compact"
                  className={styles.toolbarControl}
                  aria-label={contextRingLabel}
                  onPress={() => setFeedback(`上下文明细（模拟）：${contextRingLabel}`)}
                >
                  上下文 {session.usagePercent}%
                </VButton>
                {sessionBusy ? (
                  <VButton
                    variant="danger"
                    density="compact"
                    className={styles.stopAction}
                    icon={<Square size={13} />}
                    onPress={stopMockTurn}
                  >
                    停止
                  </VButton>
                ) : (
                  <VButton
                    variant="primary"
                    density="compact"
                    className={styles.primaryAction}
                    icon={<Send size={13} />}
                    onPress={sendMockMessage}
                  >
                    发送
                  </VButton>
                )}
              </div>
            </div>
          </div>
        </section>

        <aside
          className={styles.statusRail}
          data-open={statusRailOpen ? "true" : "false"}
          aria-label="状态栏（只读）"
        >
          {statusRailOpen ? (
            <div className={styles.railContent}>
              <div className={styles.railHeader}>
                <strong>状态栏 · 只读</strong>
                <VButton
                  isIconOnly
                  variant="ghost"
                  density="compact"
                  aria-label="收起状态栏"
                  icon={<X size={14} />}
                  onPress={() => setStatusRailOpen(false)}
                />
              </div>

              {scene === "group" ? (
                <section className={styles.railSection} aria-label="群聊资料（只读）">
                  <div className={styles.railSectionTitle}>群聊资料</div>
                  <div className={styles.railRow}>
                    <span className={styles.railRowLabel}>群名</span>
                    <span className={styles.railRowValue}>{GROUP_META.name}</span>
                  </div>
                  <div className={styles.railRow}>
                    <span className={styles.railRowLabel}>调度模式</span>
                    <span className={styles.railRowValue}>{GROUP_META.modeLabel}</span>
                  </div>
                  <div className={styles.railRow}>
                    <span className={styles.railRowLabel}>对话目的</span>
                    <span className={styles.railRowValue}>{GROUP_META.purposeLabel}</span>
                  </div>
                  <div className={styles.railRow}>
                    <span className={styles.railRowLabel}>成员</span>
                    <span className={styles.railRowValue}>{GROUP_META.members.length} 位 · 团队引用</span>
                  </div>
                </section>
              ) : (
                <section className={styles.railSection} aria-label="当前会话（只读）">
                  <div className={styles.railSectionTitle}>当前会话</div>
                  <div className={styles.railRow}>
                    <span className={styles.railRowLabel}>状态</span>
                    <span className={styles.railRowValue}>{stateLabel}</span>
                  </div>
                  <div className={styles.railRow}>
                    <span className={styles.railRowLabel}>模型</span>
                    <span className={styles.railRowValue}>{session.modelLabel}</span>
                  </div>
                </section>
              )}

              <section className={styles.railSection} aria-label="陪伴（只读）">
                <div className={styles.railSectionTitle}>陪伴</div>
                <div className={styles.railRow}>
                  <span className={styles.railRowLabel}>名字</span>
                  <span className={styles.railRowValue}>{COMPANION.name} · Lv.{COMPANION.level}</span>
                </div>
                <p className={styles.railNote}>{COMPANION.line}</p>
              </section>

              <p className={styles.railNote}>
                只读快照，不写入正式会话；控制动作已收敛到输入框左下角的「+」菜单。
              </p>
            </div>
          ) : (
            <div className={styles.railCollapsedStrip}>
              <VButton
                isIconOnly
                variant="ghost"
                density="compact"
                className={styles.railExpandButton}
                aria-label="展开状态栏"
                icon={<ChevronLeft size={14} />}
                onPress={() => setStatusRailOpen(true)}
              />
              <span aria-hidden="true">状态只读</span>
            </div>
          )}
        </aside>
      </div>

      <VDialog
        open={groupDialogOpen}
        onOpenChange={setGroupDialogOpen}
        title="群聊管理"
        description="编辑群聊资料；成员与同步关系由团队页维护。"
        size="md"
        footer={
          <>
            <VButton
              variant="secondary"
              density="compact"
              onPress={() => {
                setGroupDialogOpen(false);
                setFeedback("已关闭群聊管理");
              }}
            >
              关闭
            </VButton>
            <VButton
              variant="primary"
              density="compact"
              onPress={() => {
                setFeedback("已模拟应用群聊变更");
              }}
            >
              应用变更
            </VButton>
          </>
        }
      >
        <div className={styles.groupDialog}>
          <div className={styles.groupFieldRow}>
            <span className={styles.groupFieldLabel}>群名</span>
            <VNativeInput
              className={styles.groupNameField}
              value={groupNameDraft}
              aria-label="群名"
              onChange={(event) => setGroupNameDraft(event.target.value)}
            />
          </div>
          <div className={styles.groupFieldRow}>
            <span className={styles.groupFieldLabel}>调度模式</span>
            <span className={styles.groupFieldValue}>{GROUP_META.modeLabel}</span>
          </div>
          <div className={styles.groupFieldRow}>
            <span className={styles.groupFieldLabel}>对话目的</span>
            <span className={styles.groupFieldValue}>{GROUP_META.purposeLabel}</span>
          </div>
          <div className={styles.groupFieldRow}>
            <span className={styles.groupFieldLabel}>成员</span>
            <div className={styles.memberChipRow}>
              {GROUP_META.members.map((member) => (
                <span key={member} className={styles.memberChip}>{member}</span>
              ))}
            </div>
          </div>
          <p className={styles.railNote}>本轮空闲，可修改资料；成员与团队同步关系请前往团队页维护。</p>
          <div className={styles.groupActions}>
            <VButton
              variant="danger"
              density="compact"
              className={styles.groupActionDanger}
              icon={<RotateCcw size={13} />}
              onPress={() => {
                setGroupDialogOpen(false);
                setConfirmResetOpen(true);
              }}
            >
              重置消息
            </VButton>
            <VButton
              variant="danger"
              density="compact"
              className={styles.groupActionDanger}
              icon={<Trash2 size={13} />}
              onPress={() => {
                setGroupDialogOpen(false);
                setConfirmDeleteOpen(true);
              }}
            >
              删除群聊
            </VButton>
          </div>
        </div>
      </VDialog>

      <VConfirmDialog
        open={confirmResetOpen}
        onOpenChange={setConfirmResetOpen}
        tone="danger"
        title="重置群聊消息？"
        description="将清空「产品周会」的消息记录。此操作不可撤销（模拟）。"
        confirmLabel="确认重置"
        cancelLabel="取消"
        onConfirm={() => confirmDestructive("reset")}
      />

      <VConfirmDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
        tone="danger"
        title="删除群聊？"
        description="将删除「产品周会」群聊及成员关系（模拟）。此操作不可撤销。"
        confirmLabel="确认删除"
        cancelLabel="取消"
        onConfirm={() => confirmDestructive("delete")}
      />

      <VDialog
        open={referencePicker !== null}
        onOpenChange={(open) => {
          if (!open) {
            setReferencePicker(null);
            setReferenceQuery("");
          }
        }}
        title={referencePicker === "session" ? "引用会话" : "引用工作区文件"}
        description="搜索并选择一项加入输入框引用（模拟数据，不调用真实 API）。"
        size="md"
      >
        <div className={styles.pickerSearchRow}>
          <VNativeInput
            className={styles.pickerSearch}
            value={referenceQuery}
            aria-label={referencePicker === "session" ? "搜索会话" : "搜索工作区文件"}
            placeholder={referencePicker === "session" ? "搜索会话标题或来源…" : "搜索文件路径或说明…"}
            onChange={(event) => setReferenceQuery(event.target.value)}
          />
        </div>
        <div
          className={styles.pickerList}
          role="listbox"
          aria-label={referencePicker === "session" ? "可选会话" : "可选工作区文件"}
        >
          {filteredReferenceOptions.map((option) => (
            <VButton
              key={option.id}
              role="option"
              aria-selected={false}
              aria-label={option.title}
              contentLayout="plain"
              variant="ghost"
              className={styles.pickerOption}
              onPress={() => chooseReference(referencePicker ?? "session", option)}
            >
              <span className={styles.pickerOptionMark} aria-hidden="true">
                {referencePicker === "session" ? <MessageSquare size={15} /> : <FileText size={15} />}
              </span>
              <span className={styles.pickerOptionCopy}>
                <strong>{option.title}</strong>
                <small>{option.meta}</small>
              </span>
            </VButton>
          ))}
          {filteredReferenceOptions.length === 0 ? (
            <p className={styles.pickerEmpty}>没有匹配的{referencePicker === "session" ? "会话" : "文件"}。</p>
          ) : null}
        </div>
      </VDialog>

      <p className={styles.previewNote}>
        隔离 mock 预览：不调用真实 API、不写入正式会话或数据；仅演示加号菜单收敛方向与只读状态栏折叠行为。
      </p>
    </main>
  );
}

const previewRoot = document.getElementById("root");
if (previewRoot) {
  createRoot(previewRoot).render(
    <StrictMode>
      <VuiProvider>
        <ChatComposerPlusMenuPreviewApp />
      </VuiProvider>
    </StrictMode>,
  );
}
