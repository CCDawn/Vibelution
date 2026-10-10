import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Clock3,
  FileText,
  Plus,
  RotateCw,
} from "lucide-react";
import { VButton, VDialog, VInput, VTextarea } from "../../components/vui";
import { members, taskRows, type PreviewScene } from "./fixtures";
import { Avatar, PageHeading, styles, usePreviewDialogFocus } from "./PreviewUi";

type TaskStatus = "已完成" | "评审中" | "失败" | "待开始" | "进行中";

type TeamTask = {
  id: string;
  title: string;
  owner: string;
  status: TaskStatus;
  note: string;
  acceptance?: string;
  custom?: boolean;
};

type PreviewDialog =
  | { kind: "create" }
  | { kind: "task"; taskId: string }
  | { kind: "artifact"; name: string }
  | null;

const artifactRows = [
  { name: "LoginButton.tsx", summary: "加载状态与重复提交保护", time: "10:31" },
  { name: "LoginForm.tsx", summary: "行内错误提示与重新提交", time: "10:38" },
] as const;

function makeTasks(scene: PreviewScene): TeamTask[] {
  if (scene === "empty") return [];

  return taskRows.map((row) => {
    if (scene === "completed") return { ...row, status: "已完成" };
    if (scene === "error" && row.id === "review") {
      return { ...row, status: "失败", note: "检查未能完成，保留已完成的实现" };
    }
    return { ...row, status: row.status };
  });
}

function ownerName(owner: string) {
  return owner === "user" ? "你" : members.find((member) => member.id === owner)?.name ?? "团队成员";
}

function TaskProgress({ scene, initial = false }: { scene: PreviewScene; initial?: boolean }) {
  const activeIndex = initial ? 0 : scene === "completed" ? 3 : scene === "empty" ? 0 : 2;
  const steps = ["方案", "实现", "评审"];

  return (
    <ol aria-label="任务进度" className="mt-5 grid grid-cols-3 gap-3 max-[600px]:gap-2">
      {steps.map((step, index) => {
        const done = index < activeIndex || scene === "completed";
        const failed = scene === "error" && index === activeIndex;
        const current = !done && !failed && index === activeIndex;
        return (
          <li key={step} aria-current={current ? "step" : undefined} className="min-w-0">
            <div className={`h-1 rounded-full ${done ? "bg-emerald-500" : failed ? "bg-amber-500" : current ? "bg-blue-500" : "bg-slate-200"}`} />
            <div className="mt-2 flex min-w-0 items-center gap-1.5 text-sm">
              {done ? <Check size={14} className="shrink-0 text-emerald-700" aria-hidden="true" />
                : failed ? <CircleAlert size={14} className="shrink-0 text-amber-700" aria-hidden="true" />
                  : current ? <Clock3 size={14} className="shrink-0 text-blue-700" aria-hidden="true" />
                    : <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-slate-300" aria-hidden="true" />}
              <span className={`truncate ${done ? "text-[var(--fg-secondary)]" : current ? "font-medium text-[var(--fg-primary)]" : failed ? "font-medium text-amber-800" : "text-[var(--fg-tertiary)]"}`}>
                {step}{failed ? "失败" : current ? "中" : ""}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function TaskStatusText({ task }: { task: TeamTask }) {
  if (task.status === "失败") {
    return <span className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-800"><CircleAlert size={14} aria-hidden="true" />失败</span>;
  }
  if (task.status === "评审中" || task.status === "进行中") {
    return <span className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-700"><Clock3 size={14} aria-hidden="true" />{task.status}</span>;
  }
  if (task.status === "待开始") {
    return <span className="text-sm text-[var(--fg-tertiary)]">待开始</span>;
  }
  return <span className="inline-flex items-center gap-1.5 text-sm text-emerald-700"><Check size={14} aria-hidden="true" />已完成</span>;
}

function ActivityList({ scene, createdTasks }: { scene: PreviewScene; createdTasks: TeamTask[] }) {
  const updates = scene === "error"
    ? [
      { owner: "reviewer", time: "10:41", text: "检查未能完成：快速双击场景需要重新运行" },
      { owner: "developer-b", time: "10:38", text: "完成失败提示与重试" },
      { owner: "developer-a", time: "10:31", text: "完成加载反馈与重复提交保护" },
    ]
    : scene === "completed"
      ? [
        { owner: "reviewer", time: "10:41", text: "评审通过，快速双击与键盘提交行为一致" },
        { owner: "developer-b", time: "10:38", text: "完成失败提示与重试" },
        { owner: "developer-a", time: "10:31", text: "完成加载反馈与重复提交保护" },
      ]
      : [
        { owner: "reviewer", time: "10:41", text: "正在核对快速双击与回车同时触发的情况" },
        { owner: "developer-b", time: "10:38", text: "完成失败提示与重试" },
        { owner: "developer-a", time: "10:31", text: "完成加载反馈与重复提交保护" },
      ];

  return (
    <ol className="mt-3 divide-y divide-[var(--vui-border-subtle)]">
      {createdTasks.map((task) => (
        <li key={`activity-${task.id}`} className="flex items-start gap-3 py-3">
          <Avatar id="user" small />
          <p className="min-w-0 flex-1 text-sm leading-6"><span className="font-medium">你</span> 创建了“{task.title}”<span className="ml-2 whitespace-nowrap text-xs text-[var(--fg-tertiary)]">刚刚</span></p>
        </li>
      ))}
      {(scene === "empty" ? [] : updates).map((update) => (
        <li key={`${update.owner}-${update.time}`} className="flex items-start gap-3 py-3">
          <Avatar id={update.owner} small />
          <p className="min-w-0 flex-1 text-sm leading-6"><span className="font-medium">{ownerName(update.owner)}</span> {update.text}<span className="ml-2 whitespace-nowrap text-xs text-[var(--fg-tertiary)]">{update.time}</span></p>
        </li>
      ))}
    </ol>
  );
}

export function TeamPreview({ scene, onChat, onMembers }: { scene: PreviewScene; onChat: () => void; onMembers: () => void }) {
  const [localScene, setLocalScene] = useState(scene);
  const [createdTasks, setCreatedTasks] = useState<TeamTask[]>([]);
  const [dialog, setDialog] = useState<PreviewDialog>(null);
  const dialogFocus = usePreviewDialogFocus();
  const openDialog = (next: PreviewDialog) => { dialogFocus.remember(); setDialog(next); };
  const [draftTitle, setDraftTitle] = useState("");
  const [draftAcceptance, setDraftAcceptance] = useState("");

  useEffect(() => {
    setLocalScene(scene);
    setCreatedTasks([]);
    setDialog(null);
    setDraftTitle("");
    setDraftAcceptance("");
  }, [scene]);

  const baseTasks = useMemo(() => makeTasks(scene === "empty" ? "empty" : localScene), [scene, localScene]);
  const tasks = [...baseTasks, ...createdTasks];
  const empty = scene === "empty" && createdTasks.length === 0;
  const activeTask = scene === "empty" && createdTasks[0]
    ? createdTasks[0]
    : { title: "优化登录流程的反馈与恢复", acceptance: "加载时阻止重复提交；失败后保留输入并支持重试。" };
  const selectedTask = dialog?.kind === "task" ? tasks.find((task) => task.id === dialog.taskId) : undefined;
  const selectedArtifact = dialog?.kind === "artifact" ? artifactRows.find((row) => row.name === dialog.name) : undefined;
  const canCreate = draftTitle.trim().length >= 2 && draftAcceptance.trim().length >= 4;

  const openCreateDialog = () => {
    setDraftTitle("");
    setDraftAcceptance("");
    openDialog({ kind: "create" });
  };

  const createTask = (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!canCreate) return;
    const title = draftTitle.trim();
    const acceptance = draftAcceptance.trim();
    const newTask: TeamTask = {
      id: `preview-task-${createdTasks.length + 1}`,
      title,
      owner: "planner",
      status: scene === "empty" ? "进行中" : "待开始",
      note: acceptance,
      acceptance,
      custom: true,
    };
    setCreatedTasks((current) => [...current, newTask]);
    if (scene === "empty") setLocalScene("running");
    setDialog(null);
    setDraftTitle("");
    setDraftAcceptance("");
  };

  const retryReview = () => {
    setLocalScene("running");
  };

  const dialogTitle = dialog?.kind === "create"
    ? "新建任务"
    : selectedTask?.title ?? selectedArtifact?.name ?? "任务详情";
  const dialogDescription = dialog?.kind === "artifact"
    ? selectedArtifact?.summary
    : dialog?.kind === "task"
      ? `${ownerName(selectedTask?.owner ?? "planner")} · ${selectedTask?.note ?? ""}`
      : undefined;

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--vui-surface-canvas)] text-[var(--fg-primary)]">
      <PageHeading
        title="开发团队"
        subtitle="团队工作台"
        scene={localScene}
        onMembers={onMembers}
        status={scene === "empty" && createdTasks.length > 0 ? <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-800">进行中</span> : undefined}
        actions={<VButton className={`${styles.touch} !min-h-11`} variant="primary" icon={<ArrowUpRight size={16} />} onPress={onChat}>查看讨论</VButton>}
      />

      <main className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-7 py-6 max-[900px]:px-5 max-[600px]:px-4 max-[600px]:py-4">
        {empty ? (
          <section className={`${styles.panel} mx-auto flex min-h-[280px] max-w-5xl items-center px-8 py-10 max-[600px]:min-h-[240px] max-[600px]:px-5`}>
            <div className="max-w-xl">
              <p className="text-sm text-[var(--fg-tertiary)]">开发团队</p>
              <h2 className="mt-2 text-lg font-semibold">还没有团队任务</h2>
              <p className="mt-2 text-base leading-7 text-[var(--fg-secondary)]">创建一个目标，团队就可以开始协作。</p>
              <VButton className={`mt-5 ${styles.touch} !min-h-11`} icon={<Plus size={16} />} onPress={openCreateDialog}>新建任务</VButton>
            </div>
          </section>
        ) : (
          <div className="mx-auto max-w-[1360px]">
            <div className={`grid grid-cols-[minmax(0,1fr)_280px] overflow-hidden ${styles.panel} max-[900px]:grid-cols-1`}>
              <section className="min-w-0 p-6 max-[600px]:p-4">
                <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-[var(--fg-tertiary)]">当前任务</p>
                    <h2 className="mt-1 break-words text-xl font-semibold leading-7 tracking-normal max-[600px]:text-lg">{activeTask.title}</h2>
                    {activeTask.acceptance && <p className="mt-2 max-w-3xl text-base leading-7 text-[var(--fg-secondary)]">{activeTask.acceptance}</p>}
                  </div>
                </div>

                <TaskProgress scene={localScene} initial={scene === "empty"} />

                <section className="mt-8 border-t border-[var(--vui-border-subtle)] pt-5" aria-labelledby="team-task-list-title">
                  <div className="flex items-center justify-between gap-3">
                    <h3 id="team-task-list-title" className="text-base font-semibold">任务进展</h3>
                    {createdTasks.length > 0 && <span className="text-sm text-[var(--fg-tertiary)]">{createdTasks.length} 项新建任务</span>}
                  </div>
                  <ul className="mt-2 divide-y divide-[var(--vui-border-subtle)]">
                    {tasks.map((task) => (
                      <li key={task.id} className="grid min-w-0 grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 py-3.5 max-[600px]:grid-cols-[28px_minmax(0,1fr)] max-[600px]:items-start">
                        <Avatar id={task.owner} small />
                        <div className="min-w-0">
                          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                            <p className="min-w-0 flex-1 break-words text-base font-medium leading-6 max-[600px]:basis-full">{task.title}</p>
                            <span className="max-[600px]:hidden"><TaskStatusText task={task} /></span>
                          </div>
                          <p className="mt-1 break-words text-sm leading-5 text-[var(--fg-tertiary)]">{ownerName(task.owner)} · {task.note}</p>
                        </div>
                        <div className="flex items-center justify-between gap-3 max-[600px]:col-start-2">
                        <span className="hidden max-[600px]:inline-flex"><TaskStatusText task={task} /></span>
                        {task.status === "失败" ? (
                          <VButton className={`${styles.touch} !min-h-11 shrink-0`} variant="secondary" icon={<RotateCw size={15} />} onPress={retryReview}>重新运行</VButton>
                        ) : (
                          <VButton className={`${styles.touch} !min-h-11 shrink-0 max-[600px]:px-2`} variant="ghost" icon={<ArrowUpRight size={15} />} aria-label={`查看任务：${task.title}`} onPress={() => openDialog({ kind: "task", taskId: task.id })}>详情</VButton>
                        )}</div>
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="mt-7 border-t border-[var(--vui-border-subtle)] pt-5" aria-labelledby="team-activity-title">
                  <h3 id="team-activity-title" className="text-base font-semibold">最近动态</h3>
                  <ActivityList scene={scene === "empty" ? "empty" : localScene} createdTasks={createdTasks} />
                </section>
              </section>

              <aside className="min-w-0 border-l border-[var(--vui-border-subtle)] bg-slate-50/60 p-5 max-[900px]:border-l-0 max-[900px]:border-t max-[600px]:p-4" aria-labelledby="team-artifacts-title">
                <h3 id="team-artifacts-title" className="text-base font-semibold">产出文件</h3>
                {scene === "empty" ? <p className="mt-3 text-sm text-[var(--fg-tertiary)]">暂无文件</p> : (
                  <ul className="mt-3 divide-y divide-[var(--vui-border-subtle)]">
                    {artifactRows.map((artifact) => (
                      <li key={artifact.name} className="py-3 first:pt-0">
                        <VButton className={`w-full justify-start !min-h-11 ${styles.touch} ${styles.quietButton}`} contentLayout="plain" icon={<FileText size={16} className="shrink-0 text-[var(--fg-tertiary)]" />} onPress={() => openDialog({ kind: "artifact", name: artifact.name })}>
                          <span className="min-w-0 flex-1 text-left">
                            <span className="block truncate text-sm font-medium text-[var(--fg-primary)]">{artifact.name}</span>
                            <span className="mt-0.5 block truncate text-xs text-[var(--fg-tertiary)]">{artifact.summary} · {artifact.time}</span>
                          </span>
                        </VButton>
                      </li>
                    ))}
                  </ul>
                )}
                {localScene === "error" && (
                  <div className="mt-5 border-t border-[var(--vui-border-subtle)] pt-4">
                    <p className="text-sm font-medium text-amber-800">评审未完成</p>
                    <p className="mt-1 text-sm leading-6 text-[var(--fg-secondary)]">前两项成果已保留，可从任务列表重新运行评审。</p>
                  </div>
                )}
              </aside>
            </div>
          </div>
        )}
      </main>

      <VDialog
        onCloseAutoFocus={dialogFocus.onCloseAutoFocus}
        open={dialog !== null}
        onOpenChange={(open) => { if (!open) setDialog(null); }}
        title={dialogTitle}
        description={dialogDescription}
        size="md"
        footer={dialog?.kind === "create" ? (
          <>
            <VButton className={styles.touch} variant="secondary" onPress={() => setDialog(null)}>取消</VButton>
            <VButton className={styles.touch} type="submit" form="team-preview-create-task" isDisabled={!canCreate}>创建任务</VButton>
          </>
        ) : <VButton className={styles.touch} onPress={() => setDialog(null)}>关闭</VButton>}
      >
        {dialog?.kind === "create" ? (
          <form id="team-preview-create-task" className="grid gap-4" onSubmit={createTask}>
            <label className="grid gap-1.5 text-sm font-medium" htmlFor="team-preview-task-title">
              任务主题
              <VInput id="team-preview-task-title" autoFocus required minLength={2} maxLength={100} value={draftTitle} placeholder="例如：优化登录流程的反馈与恢复" onChange={(event) => setDraftTitle(event.currentTarget.value)} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium" htmlFor="team-preview-task-acceptance">
              验收标准
              <VTextarea id="team-preview-task-acceptance" required minLength={4} maxLength={300} minRows={3} value={draftAcceptance} placeholder="例如：失败时保留输入，并支持再次提交" onChange={(event) => setDraftAcceptance(event.currentTarget.value)} />
            </label>
          </form>
        ) : dialog?.kind === "task" && selectedTask ? (
          <div className="space-y-4">
            <TaskStatusText task={selectedTask} />
            <div>
              <p className={`text-sm ${styles.muted}`}>负责人</p>
              <div className="mt-2 flex items-center gap-2"><Avatar id={selectedTask.owner} small /><span className="text-sm font-medium">{ownerName(selectedTask.owner)}</span></div>
            </div>
            <div>
              <p className={`text-sm ${styles.muted}`}>验收说明</p>
              <p className="mt-1 text-base leading-7">{selectedTask.acceptance ?? selectedTask.note}</p>
            </div>
          </div>
        ) : selectedArtifact ? (
          <div className="space-y-3">
            <p className="text-sm text-[var(--fg-secondary)]">{selectedArtifact.summary}</p>
            <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm leading-6 text-[var(--fg-secondary)]">
              {selectedArtifact.name === "LoginButton.tsx"
                ? <><p>提交中显示“正在登录”</p><p>按钮与回车共用提交入口</p><p>提交期间阻止重复操作</p></>
                : <><p>错误提示显示在输入框附近</p><p>请求失败后保留已填内容</p><p>请求结束后可再次提交</p></>}
            </div>
          </div>
        ) : null}
      </VDialog>
    </div>
  );
}
