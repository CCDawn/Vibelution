import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { GripVertical, Pencil, Square, X } from "lucide-react";

import { VButton, VNativeTextarea, VSurface, VuiProvider } from "../components/vui";
import { shouldSubmitComposerOnKeydown } from "../components/conversation/composerShortcuts";
import {
  appendComposerQueueItem,
  appendImmediateSteerTurns,
  moveComposerQueueItem,
  removeComposerQueueItem,
  resolveComposerQueueEnter,
  resolveComposerQueuePrimaryKind,
  updateComposerQueueItem,
  type ComposerQueueItem,
} from "../components/conversation/composerFollowupQueueModel";
import "./base.css";
import "./tokens.css";
import "./vui-native-controls.css";
import "./vui-provider-theme.css";
import "./composer-followup-queue-preview.css";
import { composerFollowupQueuePreviewStyles as styles } from "./composer-followup-queue-preview.styles";

type TranscriptKind = "user" | "assistant";

type TranscriptItem = {
  id: string;
  kind: TranscriptKind;
  text: string;
  streaming?: boolean;
  steer?: boolean;
};

const initialTranscript: TranscriptItem[] = [
  { id: "u1", kind: "user", text: "把登录页改成暗色，并补上失败提示。" },
  { id: "a1", kind: "assistant", text: "正在改 LoginPage 的背景和错误态…", streaming: true },
];

function appendImmediateSteer(transcript: TranscriptItem[], texts: string[]): TranscriptItem[] {
  return appendImmediateSteerTurns(transcript, texts, (text) => ({
    id: nextId("steer"),
    kind: "user",
    text,
    steer: true,
  }));
}

function nextId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
}

function readPreviewSearch() {
  const params = new URLSearchParams(window.location.search);
  const scene = params.get("scene");
  return scene === "one" || scene === "two" || scene === "steered" || scene === "flushed" || scene === "empty"
    ? scene
    : "empty";
}

function App() {
  const initialScene = readPreviewSearch();
  const [sessionBusy, setSessionBusy] = useState(true);
  const [draft, setDraft] = useState("");
  const [queue, setQueue] = useState<ComposerQueueItem[]>([]);
  const [transcript, setTranscript] = useState<TranscriptItem[]>(initialTranscript);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [log, setLog] = useState<string[]>(["预览已就绪：当前轮正在运行，输入框为空。"]);
  const bootstrapped = useRef(false);
  const dragFrom = useRef<number | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const primaryKind = resolveComposerQueuePrimaryKind({
    sessionBusy,
    draft,
    queueCount: queue.length,
  });
  const primaryLabel = primaryKind === "immediate"
    ? "立刻引导"
    : primaryKind === "queue"
      ? "排队"
      : "发送";
  const placeholder = !sessionBusy
    ? "描述下一步要做什么..."
    : queue.length
      ? "再输入则追加；空输入再 Enter 立刻引导"
      : "输入后排队，空输入再 Enter 立刻引导";

  function pushLog(line: string) {
    setLog((current) => [line, ...current].slice(0, 8));
  }

  function submitComposer() {
    const action = resolveComposerQueueEnter({ sessionBusy, draft, queue });
    if (action.type === "enqueue") {
      setQueue((current) => appendComposerQueueItem(current, action.text));
      setDraft("");
      pushLog(`已排队：${action.text}`);
      return;
    }
    if (action.type === "immediate") {
      setTranscript((current) => appendImmediateSteer(current, action.items.map((item) => item.text)));
      setQueue([]);
      setDraft("");
      setEditingId(null);
      pushLog(`立刻引导，已新增独立消息：${action.items.map((item) => item.text).join(" / ")}`);
      return;
    }
    if (action.type === "send") {
      setTranscript((current) => [
        ...current,
        { id: nextId("user"), kind: "user", text: action.text },
        { id: nextId("assistant"), kind: "assistant", text: "已收到，开始处理…", streaming: true },
      ]);
      setDraft("");
      setSessionBusy(true);
      pushLog(`普通发送：${action.text}`);
    }
  }

  function finishTurn() {
    if (!sessionBusy) {
      return;
    }
    const flushed = [...queue];
    setTranscript((current) => [
      ...current.map((item) => (item.streaming ? { ...item, text: `${item.text} 已完成这一轮。`, streaming: false } : item)),
      ...flushed.map((item) => ({ id: nextId("user"), kind: "user" as const, text: item.text })),
    ]);
    setQueue([]);
    setSessionBusy(false);
    setEditingId(null);
    pushLog(flushed.length
      ? `当前轮结束，自动发出 ${flushed.length} 条普通用户消息`
      : "当前轮结束，队列为空");
  }

  function applyScenario(name: "empty" | "one" | "two" | "steered" | "flushed") {
    setEditingId(null);
    setEditDraft("");
    setDraft("");
    if (name === "empty") {
      setSessionBusy(true);
      setQueue([]);
      setTranscript(initialTranscript);
      pushLog("场景：运行中，空队列");
      return;
    }
    if (name === "one") {
      setSessionBusy(true);
      setQueue([{ id: "q-1", text: "先不要改测试，只汇报改了哪些文件。" }]);
      setTranscript(initialTranscript);
      pushLog("场景：已排队 1 条");
      return;
    }
    if (name === "two") {
      setSessionBusy(true);
      setQueue([
        { id: "q-1", text: "先不要改测试，只汇报改了哪些文件。" },
        { id: "q-2", text: "登录失败时用中文提示，不要弹英文。" },
      ]);
      setTranscript(initialTranscript);
      pushLog("场景：已排队 2 条，可撤回、修改、调序");
      return;
    }
    if (name === "steered") {
      setSessionBusy(true);
      setQueue([]);
      setTranscript([
        { id: "u1", kind: "user", text: "把登录页改成暗色，并补上失败提示。" },
        { id: "a1", kind: "assistant", text: "正在改 LoginPage 的背景和错误态…", streaming: true },
        { id: "s1", kind: "user", text: "先不要改测试，只汇报改了哪些文件。", steer: true },
      ]);
      pushLog("场景：空输入再 Enter 后，引导作为独立用户侧消息出现");
      return;
    }
    setSessionBusy(false);
    setQueue([]);
    setTranscript([
      { id: "u1", kind: "user", text: "把登录页改成暗色，并补上失败提示。" },
      { id: "a1", kind: "assistant", text: "暗色登录页和失败提示已经改完。" },
      { id: "u2", kind: "user", text: "先不要改测试，只汇报改了哪些文件。" },
    ]);
    pushLog("场景：当前轮结束后，排队内容已作为普通用户消息发出");
  }

  useEffect(() => {
    if (bootstrapped.current) {
      return;
    }
    bootstrapped.current = true;
    if (initialScene !== "empty") {
      applyScenario(initialScene);
    }
  });

  const keymap = useMemo(() => ([
    ["Enter + 有字", sessionBusy ? "追加到队列" : "普通发送"],
    ["Enter + 空框", queue.length ? "立刻引导，新增一条独立消息" : "无操作"],
    ["横条 · 改 / 撤回", "修改或丢掉未发出的条目"],
    ["结束当前轮", "队列按顺序自动当普通消息发出"],
  ]), [queue.length, sessionBusy]);

  return (
    <main className={styles.page} data-composer-queue-preview="true">
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>CHAT · 隔离预览</p>
          <h1>运行中跟进队列</h1>
          <p className={styles.subtitle}>
            第一次 Enter 只入队。队列已在且输入框为空时，再按 Enter 立刻引导，并在时间线末尾新增一条带「引导」标记的独立消息。
            当前轮结束后，未发出的条目会按顺序变成普通用户消息。正式对话页尚未改动。
          </p>
        </div>
        <div className={styles.headerActions}>
          <VButton variant="secondary" density="compact" className={styles.chip} onPress={() => applyScenario("empty")}>运行中空队列</VButton>
          <VButton variant="secondary" density="compact" className={styles.chip} onPress={() => applyScenario("one")}>已排队 1 条</VButton>
          <VButton variant="secondary" density="compact" className={styles.chip} onPress={() => applyScenario("two")}>已排队 2 条</VButton>
          <VButton variant="secondary" density="compact" className={styles.chip} onPress={() => applyScenario("steered")}>立刻引导后</VButton>
          <VButton variant="secondary" density="compact" className={styles.chip} onPress={() => applyScenario("flushed")}>结束后自动发出</VButton>
        </div>
      </header>

      <div className={styles.layout}>
        <section className={styles.stage}>
          <div className={styles.chat} data-preview-chat="true">
            <div className={styles.transcript} aria-label="模拟对话">
              {transcript.map((item) => (
                <article
                  key={item.id}
                  className={[
                    styles.turn,
                    item.kind === "user" ? styles.turnUser : styles.turnAssistant,
                  ].join(" ")}
                >
                  {item.kind === "assistant" ? <span className={styles.avatar}>A</span> : null}
                  <div className={styles.bubble}>
                    {item.steer ? <span className={styles.badge}>引导</span> : null}
                    <div>{item.text}</div>
                    {item.streaming ? <div className={styles.streaming}>当前轮进行中</div> : null}
                  </div>
                  {item.kind === "user" ? <span className={styles.avatar}>我</span> : null}
                </article>
              ))}
            </div>

            {queue.length ? (
              <div className={styles.queueStack} aria-label="待发送队列">
                {queue.map((item, index) => {
                  const editing = editingId === item.id;
                  return (
                    <div
                      key={item.id}
                      className={editing ? `${styles.queueBar} ${styles.queueBarEditing}` : styles.queueBar}
                      draggable={!editing}
                      onDragStart={() => {
                        dragFrom.current = index;
                      }}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => {
                        if (dragFrom.current == null) {
                          return;
                        }
                        setQueue((current) => moveComposerQueueItem(current, dragFrom.current ?? index, index));
                        dragFrom.current = null;
                        pushLog("已调整排队顺序");
                      }}
                    >
                      <span className={styles.queueHandle} aria-hidden="true">
                        <GripVertical size={14} />
                      </span>
                      <div className={styles.queueCopy}>
                        <span className={styles.queueLabel}>排队 {index + 1}</span>
                        {editing ? (
                          <VNativeTextarea
                            className={styles.queueEditor}
                            value={editDraft}
                            minRows={2}
                            aria-label={`修改排队 ${index + 1}`}
                            onChange={(event) => setEditDraft(event.target.value)}
                          />
                        ) : (
                          <span className={styles.queueText} title={item.text}>{item.text}</span>
                        )}
                      </div>
                      <div className={styles.queueActions}>
                        {editing ? (
                          <>
                            <VButton
                              density="compact"
                              variant="secondary"
                              onPress={() => {
                                setQueue((current) => updateComposerQueueItem(current, item.id, editDraft));
                                setEditingId(null);
                                pushLog(`已修改排队：${editDraft.trim() || item.text}`);
                              }}
                            >
                              保存
                            </VButton>
                            <VButton density="compact" variant="ghost" onPress={() => setEditingId(null)}>取消</VButton>
                          </>
                        ) : (
                          <>
                            <VButton
                              density="compact"
                              variant="ghost"
                              isIconOnly
                              aria-label="修改这条排队"
                              icon={<Pencil size={13} />}
                              onPress={() => {
                                setEditingId(item.id);
                                setEditDraft(item.text);
                              }}
                            />
                            <VButton
                              density="compact"
                              variant="ghost"
                              isIconOnly
                              aria-label="撤回这条排队"
                              icon={<X size={13} />}
                              onPress={() => {
                                setQueue((current) => removeComposerQueueItem(current, item.id));
                                pushLog(`已撤回：${item.text}`);
                              }}
                            />
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}

            <div className={styles.composer}>
              {sessionBusy ? (
                <div className={styles.composerHint} role="status">
                  {queue.length
                    ? "已排队，等待当前轮结束自动发出。空输入再按 Enter 会立刻并入本轮。"
                    : "当前轮进行中。输入后 Enter 只入队，不会马上打断。"}
                </div>
              ) : null}
              <div className={styles.composerField}>
                <VNativeTextarea
                  ref={inputRef}
                  className={styles.composerInput}
                  value={draft}
                  placeholder={placeholder}
                  aria-label="发送消息"
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (!shouldSubmitComposerOnKeydown({
                      key: event.key,
                      shiftKey: event.shiftKey,
                      ctrlKey: event.ctrlKey,
                      metaKey: event.metaKey,
                      altKey: event.altKey,
                      isComposing: event.nativeEvent.isComposing,
                    })) {
                      return;
                    }
                    event.preventDefault();
                    submitComposer();
                  }}
                />
              </div>
              <div className={styles.composerToolbar}>
                <VButton density="compact" variant="ghost" onPress={finishTurn} isDisabled={!sessionBusy}>
                  结束当前轮
                </VButton>
                <div className={styles.queueActions}>
                  {sessionBusy ? (
                    <VButton
                      className={styles.stopAction}
                      density="compact"
                      variant="secondary"
                      isIconOnly
                      aria-label="终止"
                      icon={<Square size={12} />}
                      onPress={() => {
                        setSessionBusy(false);
                        setTranscript((current) => current.map((item) => (
                          item.streaming ? { ...item, text: `${item.text} 已停止。`, streaming: false } : item
                        )));
                        pushLog("已终止当前轮；队列仍保留，可继续改或立刻引导");
                      }}
                    />
                  ) : null}
                  {primaryKind !== "stop-only" ? (
                    <VButton
                      className={styles.primaryAction}
                      density="compact"
                      variant="primary"
                      onPress={submitComposer}
                    >
                      {primaryLabel}
                    </VButton>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        </section>

        <aside className={styles.side}>
          <VSurface className={styles.sideCard} tone="card" elevation="panel" padding="normal">
            <h2>键位</h2>
            <div className={styles.keymap}>
              {keymap.map(([key, value]) => (
                <span key={key}><strong>{key}</strong> · {value}</span>
              ))}
            </div>
          </VSurface>
          <VSurface className={styles.sideCard} tone="card" elevation="panel" padding="normal">
            <h2>预览说明</h2>
            <p>这是隔离 mock，不写正式会话，也不调用 `/guidance`。批准后才会改 ConversationView。</p>
            <div className={styles.log} aria-label="最近操作">
              {log.map((item) => (
                <div key={item} className={styles.logItem}>{item}</div>
              ))}
            </div>
          </VSurface>
        </aside>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VuiProvider>
      <App />
    </VuiProvider>
  </StrictMode>,
);
