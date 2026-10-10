import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUp, Check, ChevronDown, ChevronRight, CircleAlert, FileCode2, FileText, LoaderCircle, MessageSquare, Paperclip, Square, RotateCcw } from "lucide-react";
import { VButton, VConfirmDialog, VDialog, VIconButton, VSurface, VTextarea } from "../../../src/components/vui";
import { Avatar, PageHeading, styles, usePreviewDialogFocus } from "./PreviewUi";
import { getMember, messages, type PreviewMessage, type PreviewScene } from "./fixtures";

function ProcessDetails({ id, settled }: { id: string; settled: boolean }) {
  const [open, setOpen] = useState(false);
  const rows = id === "m3" ? ["核对按钮与键盘提交入口", "加入请求中的禁用状态", "检查重复提交"]
    : id === "m4" ? ["整理请求失败的行内提示", "保留表单输入", "检查重试路径"]
    : ["检查加载与失败重试", "检查390px窄屏", "核对快速双击与键盘提交"];
  return <div className="mt-2">
    <VButton variant="ghost" className={`${styles.quietButton} ${styles.touch} !h-auto !justify-start !px-0 !text-xs !font-normal !text-[var(--fg-tertiary)]`} aria-expanded={open} icon={open ? <ChevronDown size={13} /> : <ChevronRight size={13} />} onClick={() => setOpen((value) => !value)}>{settled ? "查看过程 · 3 步" : "正在核对 · 3 步"}</VButton>
    {open ? <ol className="mb-3 ml-1 mt-1 grid gap-2 border-l border-[var(--vui-border-subtle)] pl-4 text-xs text-[var(--fg-secondary)]">{rows.map((row, index) => <li className="flex items-center gap-2" key={row}>{!settled && index === rows.length - 1 ? <LoaderCircle size={12} /> : <Check size={12} />}<span>{row}</span></li>)}</ol> : null}
  </div>;
}

function MessageRow({ message, sameAuthor, scene, onFile }: { message: PreviewMessage; sameAuthor: boolean; scene: PreviewScene; onFile: (file: string) => void }) {
  const [full, setFull] = useState(false);
  const long = message.body.length > 220;
  return <article data-message-id={message.id} className={`grid min-w-0 grid-cols-[36px_minmax(0,1fr)] gap-x-3 ${sameAuthor ? "pt-1" : "pt-5"}`}>
    <div>{sameAuthor ? null : <Avatar id={message.author} />}</div>
    <div className="min-w-0">
      {!sameAuthor ? <div className="mb-1 flex flex-wrap items-baseline gap-2"><strong className="text-[14px] font-semibold">{message.author === "user" ? "你" : getMember(message.author).name}</strong><time className="text-[11px] text-[var(--fg-tertiary)]">{message.time}</time></div> : null}
      <p className={`whitespace-pre-wrap break-words text-[15px] leading-[1.8] text-[var(--fg-secondary)] max-[600px]:text-base ${long && !full ? "line-clamp-5" : ""}`}>{message.body}</p>
      {long ? <VButton variant="ghost" className={`${styles.quietButton} ${styles.touch} !px-0 !text-xs`} aria-expanded={full} onClick={() => setFull((value) => !value)}>{full ? "收起全文" : "展开全文"}</VButton> : null}
      {message.file ? <VButton variant="ghost" icon={<FileCode2 size={13} />} className={`mt-2 !h-8 !min-h-8 !rounded-md !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-rail)] !text-xs !font-normal !shadow-none max-[600px]:!min-h-11`} onClick={() => onFile(message.file!)}>{message.file}</VButton> : null}
      {message.process ? <ProcessDetails id={message.id} settled={message.id !== "m7" || scene !== "running"} /> : null}
    </div>
  </article>;
}

export function GroupPreview({ scene, onMembers, onTeam }: { scene: PreviewScene; onMembers: () => void; onTeam: () => void }) {
  const [draft, setDraft] = useState("");
  const [appended, setAppended] = useState<PreviewMessage[]>([]);
  const [artifact, setArtifact] = useState<string | null>(null);
  const artifactFocus = usePreviewDialogFocus();
  const stopFocus = usePreviewDialogFocus();
  const openArtifact = (name: string) => { artifactFocus.remember(); setArtifact(name); };
  const [confirmStop, setConfirmStop] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [retried, setRetried] = useState(false);
  const [localRoundRunning, setLocalRoundRunning] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const running = (scene === "running" || localRoundRunning) && !stopped;
  const failed = scene === "error" && !retried;
  const visibleMessages = scene === "empty" ? [] : messages.filter((message) => message.id !== "m7" || scene === "running");
  const resolved: PreviewMessage[] = scene === "completed" ? [{ id: "m8", author: "reviewer", time: "10:42", round: 2, body: "通过。快速双击与回车同时提交也只发出一次请求，加载、重试和窄屏均符合这轮要求。", process: true }] : [];
  const allMessages = [...visibleMessages, ...resolved, ...appended];

  useEffect(() => {
    const host = scrollRef.current;
    if (host) host.scrollTop = host.scrollHeight;
  }, [scene, appended.length, retried]);

  const submit = () => {
    const topic = draft.trim();
    if (!topic || running) return;
    const round = appended.length ? 4 : 3;
    setAppended((current) => [...current, { id: `local-${current.length}`, author: "user", time: "现在", round, body: topic }, { id: `local-${current.length + 1}`, author: "planner", time: "现在", round, body: "收到。先核对这轮的目标和验收条件，再分派负责人。" }]);
    setDraft("");
    setStopped(false);
    setLocalRoundRunning(true);
  };

  return <>
    <PageHeading title="开发讨论" subtitle="开发团队 / 登录流程优化" scene={localRoundRunning ? "running" : scene} status={stopped ? <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">已停止</span> : undefined} onMembers={onMembers} actions={<VIconButton label="返回团队工作台" icon={<ArrowLeft size={17} />} variant="ghost" className="!h-11 !w-11" onClick={onTeam} />} />
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-7 max-[600px]:px-4" data-testid="chat-timeline" role="log" aria-label="团队发言" aria-live="polite" aria-relevant="additions text">
      <div className="mx-auto w-full max-w-[860px] pb-6 pt-2">
        {allMessages.length === 0 ? <div className="flex min-h-[360px] flex-col items-center justify-center text-center"><span className="mb-4 rounded-2xl bg-[var(--vui-surface-rail)] p-4 text-[var(--fg-tertiary)]"><MessageSquare size={28} /></span><h2 className="text-base font-semibold">开始一轮讨论</h2><p className="mt-2 max-w-[260px] text-sm leading-relaxed text-[var(--fg-tertiary)]">写下议题，或选择一个最近任务。</p><VButton variant="secondary" className={`mt-5 ${styles.touch}`} onClick={() => setDraft("检查登录按钮的加载反馈、失败重试和窄屏显示。")}>讨论登录流程</VButton></div> : allMessages.map((message, index) => {
          const previous = allMessages[index - 1];
          const newRound = previous?.round !== message.round;
          return <div key={message.id}>
            {newRound ? <div className="mb-1 mt-4 flex items-center gap-4 text-[11px] text-[var(--fg-tertiary)]"><span className="h-px flex-1 bg-[var(--vui-border-subtle)]" /><span className="shrink-0">第 {message.round} 轮 · {message.round === 1 ? "任务分派" : message.round === 2 ? "补充与评审" : "新的议题"}</span><span className="h-px flex-1 bg-[var(--vui-border-subtle)]" /></div> : null}
            <MessageRow message={message} sameAuthor={previous?.author === message.author && !newRound} scene={scene} onFile={openArtifact} />
          </div>;
        })}
        {failed ? <div className="ml-12 mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3.5 text-sm" role="alert"><div className="flex items-center gap-2 font-semibold text-amber-900"><CircleAlert size={16} />评审员未完成核对</div><p className="mt-1.5 leading-relaxed text-amber-800">请求中断。两位开发者的发言与产出已保留。</p><VButton variant="secondary" className={`mt-3 ${styles.touch}`} icon={<RotateCcw size={14} />} onClick={() => { setRetried(true); setLocalRoundRunning(true); setAppended((current) => [...current, { id: "retry", author: "reviewer", time: "现在", round: 2, body: "已恢复核对。先检查保留的产出，再继续这轮评审。" }]); }}>重试评审</VButton></div> : null}
        {scene === "completed" && appended.length === 0 ? <VSurface as="article" padding="none" className="ml-12 mt-5 !rounded-xl !border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-rail)] p-4"><div className="flex items-center gap-2 text-sm font-semibold"><Check size={15} className="text-emerald-600" />本轮结论</div><ul className="mt-2 list-inside list-disc space-y-1 text-sm leading-relaxed text-[var(--fg-secondary)]"><li>加载时显示“正在登录”，阻止重复提交。</li><li>失败时保留输入，提示就地显示，可直接重试。</li></ul><VButton variant="ghost" className={`${styles.quietButton} ${styles.touch} mt-3 !justify-start !px-0 !text-xs`} icon={<FileText size={14} />} onClick={() => openArtifact("评审记录")}>查看评审记录</VButton></VSurface> : null}
        {running ? <div className="ml-12 mt-5 flex items-center gap-2 text-xs text-[var(--fg-tertiary)]" role="status"><span className="flex gap-1" aria-hidden="true"><span className="h-1 w-1 rounded-full bg-blue-500" /><span className="h-1 w-1 rounded-full bg-blue-400" /><span className="h-1 w-1 rounded-full bg-blue-300" /></span>{localRoundRunning ? "规划师正在整理议题" : "评审员正在核对提交入口"}</div> : null}
        {stopped ? <p className="ml-12 mt-5 text-xs text-[var(--fg-tertiary)]" role="status">本轮已停止，已有发言已保留。</p> : null}
      </div>
    </div>
    <div className="shrink-0 border-t border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-7 pb-4 pt-4 max-[600px]:px-3 max-[600px]:pb-3">
      <div className="mx-auto w-full max-w-[860px]">
        <div className="relative rounded-xl border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] focus-within:ring-2 focus-within:ring-blue-100">
          <VTextarea value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="下一轮议题" placeholder={scene === "empty" ? "写下要讨论的议题…" : "下一轮，想讨论什么？"} rows={2} className="!min-h-[72px] !resize-none !rounded-xl !border-0 !bg-transparent !px-4 !py-3 !text-[15px] !shadow-none focus:!shadow-none max-[600px]:!text-base" onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); } }} />
          <div className="flex min-w-0 items-center justify-between gap-2 px-2 pb-2"><VButton variant="ghost" className={`${styles.quietButton} ${styles.touch} !text-xs !font-normal !text-[var(--fg-tertiary)]`} icon={<Paperclip size={14} />} onClick={() => openArtifact("附加参考")}>添加参考</VButton>{running ? <VButton variant="secondary" className={styles.touch} icon={<Square size={12} />} onClick={() => { stopFocus.remember(); setConfirmStop(true); }}>停止本轮</VButton> : <VButton variant="primary" className={styles.touch} icon={<ArrowUp size={15} />} isDisabled={!draft.trim()} onClick={submit}>启动一轮</VButton>}</div>
        </div>
        <div className="mt-2 flex justify-between gap-3 text-[11px] text-[var(--fg-tertiary)]"><span>发送给开发团队</span><span className="max-[600px]:hidden">Ctrl + Enter 启动一轮</span></div>
      </div>
    </div>
    <VDialog onCloseAutoFocus={artifactFocus.onCloseAutoFocus} open={artifact !== null} title={artifact ?? "产出"} onOpenChange={(open) => { if (!open) setArtifact(null); }} size="md" contentClassName="!w-[min(calc(100%_-_32px),480px)]" footer={<VButton className={styles.touch} onClick={() => setArtifact(null)}>返回讨论</VButton>}>
      {artifact === "附加参考" ? <div className="py-3"><p className="text-sm">这轮讨论可以附上文件或验收要求。</p><VButton variant="secondary" className={`mt-4 ${styles.touch}`} icon={<FileText size={14} />} onClick={() => { setDraft((value) => `${value}${value ? "\n" : ""}参考：登录流程验收要求.md`); setArtifact(null); }}>附上验收要求</VButton></div> : <div className="space-y-3 py-3 text-sm leading-relaxed"><p className="font-semibold">登录流程反馈与恢复</p><p>加载时显示“正在登录”；快速双击与键盘提交共用同一个入口。</p><p>失败提示留在表单中，保留用户输入，恢复重试按钮。</p><p className="text-[var(--fg-tertiary)]">验收项：加载、重复提交、失败重试、390px窄屏。</p></div>}
    </VDialog>
    <VConfirmDialog onCloseAutoFocus={stopFocus.onCloseAutoFocus} open={confirmStop} onOpenChange={setConfirmStop} title="停止本轮讨论？" description="已有发言与产出会保留。" confirmLabel="停止本轮" cancelLabel="继续讨论" onConfirm={() => { setStopped(true); setLocalRoundRunning(false); setConfirmStop(false); }} />
  </>;
}
