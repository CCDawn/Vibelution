import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  createDevTeamTask,
  listDevTeamTaskChanges,
  listDevTeamTasks,
  mutateDevTeamTask,
  type DevTeamTask,
  type DevTeamTaskChanges,
  type DevTeamTaskList,
} from "../../api/devTeamTasks";
import type { TeamMember } from "../../api/types";
import {
  VButton,
  VNativeButton,
  VNativeInput,
  VStringSelect,
  VNativeTextarea,
  VSection,
  VStateSurface,
  VChip,
} from "../../components/vui";
import { taskBoardStyles as styles } from "./DevTeamTaskBoard.styles";
import { TaskDependencyPicker } from "./TaskDependencyPicker";

const STATUS_LABELS: Record<string, { zh: string; en: string }> = {
  pending: { zh: "待办", en: "Pending" },
  in_progress: { zh: "进行中", en: "In progress" },
  rework: { zh: "退回", en: "Rework" },
  completed: { zh: "完成", en: "Done" },
};

const CHANGE_LABELS: Record<string, { zh: string; en: string }> = {
  added: { zh: "新增", en: "Added" },
  modified: { zh: "修改", en: "Modified" },
  deleted: { zh: "删除", en: "Deleted" },
  untracked: { zh: "未跟踪", en: "Untracked" },
};

type DevTeamTaskBoardProps = {
  lang: "zh" | "en";
  teamId: string;
  members: TeamMember[];
  speakingMemberId?: string;
  selectionRevision?: number | string;
  onSelectTask?: () => void;
  renderWorkspace?: (surfaces: { display: ReactNode; operations: ReactNode }) => ReactNode;
};

const LIVE_ROUND_STATUSES = new Set(["queued", "running", "stopping"]);

export type SpeakingParticipant = {
  participantId?: string;
  agentId?: string;
  teamRole?: string;
};

export type SpeakingProgress = {
  participantId?: string;
  state?: string;
  status?: string;
  updatedAt?: string;
};

export type SpeakingMessage = {
  participantId?: string;
  timestamp?: string;
};

export type SpeakingRound = {
  roundId?: string;
  status?: string;
  speakerProgress?: SpeakingProgress[];
  messages?: SpeakingMessage[];
};

const SPOKEN_STATUSES = new Set(["completed", "partial", "failed", "blocked"]);

function memberIdForParticipant(
  members: TeamMember[],
  participants: SpeakingParticipant[],
  participantId: string,
) {
  if (!participantId) {
    return "";
  }
  const participant = participants.find((item) => String(item.participantId || "").trim() === participantId);
  if (!participant) {
    return "";
  }
  const agentId = String(participant.agentId || "").trim();
  const byAgent = agentId ? members.find((member) => member.agentId === agentId) : undefined;
  if (byAgent) {
    return byAgent.memberId;
  }
  const role = String(participant.teamRole || "").trim();
  if (!role) {
    return "";
  }
  return members.find((member) => member.role === role)?.memberId || "";
}

function latestProgressParticipantId(
  round: SpeakingRound | null | undefined,
  include: (item: SpeakingProgress) => boolean,
) {
  const matches = (round?.speakerProgress ?? [])
    .filter((item) => include(item) && String(item.participantId || "").trim())
    .slice()
    .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")));
  return String(matches[0]?.participantId || "").trim();
}

function lastMessageMemberId(
  members: TeamMember[],
  participants: SpeakingParticipant[],
  round: SpeakingRound | null | undefined,
) {
  const messages = round?.messages ?? [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const participantId = String(messages[index]?.participantId || "").trim();
    const memberId = memberIdForParticipant(members, participants, participantId);
    if (memberId) {
      return memberId;
    }
  }
  return "";
}

export function speakingTeamMemberId(
  members: TeamMember[],
  participants: SpeakingParticipant[],
  round: SpeakingRound | null | undefined,
) {
  const status = String(round?.status || "").trim().toLowerCase();
  if (LIVE_ROUND_STATUSES.has(status)) {
    const runningId = latestProgressParticipantId(
      round,
      (item) => String(item.state || "").trim() === "running",
    );
    const runningMember = memberIdForParticipant(members, participants, runningId);
    if (runningMember) {
      return runningMember;
    }
  }
  const messageMember = lastMessageMemberId(members, participants, round);
  if (messageMember) {
    return messageMember;
  }
  const settledId = latestProgressParticipantId(round, (item) => {
    const state = String(item.state || "").trim();
    const progressStatus = String(item.status || "").trim();
    return state === "settled" && SPOKEN_STATUSES.has(progressStatus);
  });
  return memberIdForParticipant(members, participants, settledId);
}

export function speakingTeamMemberIdFromRoom(
  members: TeamMember[],
  room: {
    participants?: SpeakingParticipant[];
    rounds?: SpeakingRound[];
    activeRoundId?: string;
  } | null | undefined,
) {
  if (!room) {
    return "";
  }
  const rounds = room.rounds ?? [];
  const activeId = String(room.activeRoundId || "").trim();
  const round = (activeId ? rounds.find((item) => item.roundId === activeId) : undefined) ?? rounds[rounds.length - 1];
  return speakingTeamMemberId(members, room.participants ?? [], round);
}

function initialActorId(members: TeamMember[], speakingMemberId: string | undefined) {
  const speakingId = speakingMemberId?.trim() || "";
  if (speakingId && members.some((member) => member.memberId === speakingId)) {
    return speakingId;
  }
  return members.find((member) => member.role === "规划师")?.memberId || members[0]?.memberId || "";
}

function taskKey(teamId: string) {
  return ["teams", teamId, "dev-tasks"] as const;
}

function splitList(value: string) {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function roleOf(members: TeamMember[], memberId: string) {
  return members.find((member) => member.memberId === memberId)?.role || "";
}

type TaskActionBody = {
  taskId: string;
  action: "assign" | "claim" | "complete" | "rework" | "delete" | "update";
  expectedRevision: number;
  ownerMemberId?: string;
  reviewNote?: string;
  subject?: string;
  description?: string;
  writeScopes?: string[];
  blockedBy?: string[];
};

export function DevTeamTaskBoard({ lang, teamId, members, speakingMemberId = "", selectionRevision = 0, onSelectTask, renderWorkspace }: DevTeamTaskBoardProps) {
  const queryClient = useQueryClient();
  const [actorId, setActorId] = useState(() => initialActorId(members, speakingMemberId));
  useEffect(() => {
    const speakingId = speakingMemberId.trim();
    if (!speakingId || !members.some((member) => member.memberId === speakingId)) {
      return;
    }
    setActorId(speakingId);
  }, [members, speakingMemberId]);
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [scopes, setScopes] = useState("");
  const [blockers, setBlockers] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [creating, setCreating] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const selectedTaskIdRef = useRef(selectedTaskId);
  selectedTaskIdRef.current = selectedTaskId;
  useEffect(() => { setSelectedTaskId(null); setCreating(false); }, [teamId, selectionRevision]);
  const [statusFilter, setStatusFilter] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("");
  useEffect(() => { setStatusFilter(""); setOwnerFilter(""); }, [teamId]);
  const tasksQuery = useQuery({
    queryKey: taskKey(teamId),
    queryFn: ({ signal }) => listDevTeamTasks(teamId, { signal }),
    enabled: Boolean(teamId),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });
  const cancelTaskReads = () => queryClient.cancelQueries({ queryKey: taskKey(teamId), exact: true });
  const replaceTasks = async (data: DevTeamTaskList) => {
    // A poll may have started during the write. Discard it before publishing the POST's list.
    await cancelTaskReads();
    queryClient.setQueryData(taskKey(teamId), data);
  };
  const createTask = useMutation({
    onMutate: cancelTaskReads,
    mutationFn: () => createDevTeamTask(teamId, {
      actorMemberId: actorId,
      subject: subject.trim(),
      description: description.trim(),
      writeScopes: splitList(scopes),
      blockedBy: splitList(blockers),
      ownerMemberId: ownerId,
    }),
    onSuccess: async (data) => {
      await replaceTasks(data);
      setSubject("");
      setDescription("");
      setScopes("");
      setBlockers("");
      setOwnerId("");
      setCreating(false);
    },
  });
  const changeTask = useMutation({
    onMutate: cancelTaskReads,
    mutationFn: (body: TaskActionBody) =>
      mutateDevTeamTask(teamId, body.taskId, {
        actorMemberId: actorId,
        action: body.action,
        expectedRevision: body.expectedRevision,
        ownerMemberId: body.ownerMemberId,
        reviewNote: body.reviewNote,
        subject: body.subject,
        description: body.description,
        writeScopes: body.writeScopes,
        blockedBy: body.blockedBy,
      }),
    onSuccess: replaceTasks,
  });
  const actorRole = roleOf(members, actorId);
  const isPlanner = actorRole === "规划师";
  const tasks = tasksQuery.data?.tasks ?? [];
  const selectedTask = tasks.find(task => task.id === selectedTaskId);
  const [taskDraft, setTaskDraft] = useState<TaskOperationsDraft | null>(null);
  const draft = selectedTask ? taskDraft?.taskId === selectedTask.id ? taskDraft : taskOperationsDraft(selectedTask) : null;
  useEffect(() => {
    setTaskDraft(previous => {
      if (!selectedTask) return null;
      if (previous?.taskId === selectedTask.id && previous.editing) return previous;
      return {...taskOperationsDraft(selectedTask),note:previous?.taskId === selectedTask.id ? previous.note : ""};
    });
  }, [selectedTask, draft?.editing]);
  const patchDraft = (patch: Partial<TaskOperationsDraft>) => setTaskDraft(previous => selectedTask && selectedTaskIdRef.current === selectedTask.id
    ? {...(previous?.taskId === selectedTask.id ? previous : taskOperationsDraft(selectedTask)),...patch} : previous);
  const actor = members.find((member) => member.memberId === actorId);
  const visibleTasks = tasks.filter((task) => (!statusFilter || task.status === statusFilter)
    && (!ownerFilter || (ownerFilter === "__unassigned__" ? !task.ownerMemberId : task.ownerMemberId === ownerFilter)));
  const hasFilters = Boolean(statusFilter || ownerFilter);
  const clearFilters = () => { setStatusFilter(""); setOwnerFilter(""); };
  const errorMessage = createTask.error instanceof Error
    ? createTask.error.message
    : changeTask.error instanceof Error
      ? changeTask.error.message
      : tasksQuery.error instanceof Error
        ? tasksQuery.error.message
        : "";
  const text = (zh: string, en: string) => (lang === "zh" ? zh : en);

  const display = (
    <VSection
      aria-label={text("共享任务板", "Shared task board")}
      title={text("共享任务板", "Shared task board")}
      className={styles.root}
      meta={hasFilters
        ? text(`显示 ${visibleTasks.length} / ${tasks.length} 个任务`, `Showing ${visibleTasks.length} / ${tasks.length} tasks`)
        : text(`${tasks.length} 个任务`, `${tasks.length} tasks`)}
    >
      <div className={styles.toolbar}>
        <div className={styles.summary} aria-label={text("任务概览", "Task summary")}>
          <VNativeButton type="button" className={styles.filterChip} aria-pressed={!statusFilter} onClick={() => setStatusFilter("")}>
            {text("全部", "All")} <span>{tasks.length}</span>
          </VNativeButton>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <VNativeButton type="button" className={styles.filterChip} key={key} aria-pressed={statusFilter === key} onClick={() => setStatusFilter(key)}>
              {lang === "zh" ? label.zh : label.en} <span>{tasks.filter((task) => task.status === key).length}</span>
            </VNativeButton>
          ))}
        </div>
      </div>
      <div className={styles.filters} aria-label={text("任务筛选", "Task filters")}>
        <VStringSelect
          className={styles.ownerFilter}
          ariaLabel={text("筛选负责人", "Filter by owner")}
          value={ownerFilter}
          onValueChange={setOwnerFilter}
          options={[
            { value: "", label: text("全部负责人", "All owners") },
            { value: "__unassigned__", label: text("未指定负责人", "Unassigned") },
            ...members.map((member) => ({ value: member.memberId, label: [member.agentName || member.memberId, member.role].filter(Boolean).join(" · ") })),
            ...Array.from(new Set(tasks.map((task) => task.ownerMemberId).filter((id) => id && !members.some((member) => member.memberId === id)))).map((id) => {
              const task = tasks.find((item) => item.ownerMemberId === id);
              return { value: id, label: [task?.ownerName || id, task?.ownerRole].filter(Boolean).join(" · ") };
            }),
          ]}
        />
        {hasFilters ? <VNativeButton type="button" className={styles.button} onClick={clearFilters}>{text("清除筛选", "Clear filters")}</VNativeButton> : null}
        <span className={styles.filterResult} role="status">{text(`显示 ${visibleTasks.length} / ${tasks.length} 个任务`, `Showing ${visibleTasks.length} / ${tasks.length} tasks`)}</span>
      </div>
      {tasksQuery.error instanceof Error ? (
        <VStateSurface tone="error" density="compact" title={tasksQuery.error.message} role="alert" />
      ) : null}
      {tasksQuery.isLoading ? (
        <VStateSurface tone="loading" density="compact" title={text("正在读取任务板", "Loading tasks")} />
      ) : null}
      {!tasksQuery.isLoading && tasks.length === 0 ? (
        <VStateSurface tone="empty" density="compact" title={text("还没有任务", "No tasks yet")}>
          {text("规划师新建后，工程师认领，评审员收口或退回。", "The planner adds a task, an engineer claims it, and the reviewer closes or sends it back.")}
        </VStateSurface>
      ) : null}
      {!tasksQuery.isLoading && tasks.length > 0 && visibleTasks.length === 0 ? (
        <VStateSurface tone="empty" density="compact" title={text("没有符合筛选条件的任务", "No tasks match these filters")}>
          <p>{text("换一个状态或负责人，或清除筛选查看全部任务。", "Choose a different status or owner, or clear filters to view every task.")}</p>
          <VNativeButton type="button" className={styles.button} onClick={clearFilters}>{text("清除筛选", "Clear filters")}</VNativeButton>
        </VStateSurface>
      ) : null}
      <div className={styles.list}>
      {visibleTasks.map((task) => (
        <TaskCard
          key={task.id}
          lang={lang}
          teamId={teamId}
          task={task}
          members={members}
          tasks={tasks}
          selected={selectedTaskId === task.id}
          canReview={actorRole === "评审员"}
          onSelect={() => { setSelectedTaskId(task.id); setCreating(false); onSelectTask?.(); }}
        />
      ))}
      </div>
    </VSection>
  );
  const operations = <section className={styles.operations} aria-label={text("任务操作", "Task actions")}>
      <div className={styles.actor}>
        {text("当前身份", "Acting as")}
        <strong aria-label={text("当前身份", "Acting as")}>{actor ? [actor.agentName || actor.memberId, actor.role].filter(Boolean).join(" · ") : text("未指定", "Unassigned")}</strong>
      {isPlanner ? (
        <VNativeButton className={styles.primaryButton} aria-expanded={creating} onClick={() => { setCreating(!creating); setSelectedTaskId(null); onSelectTask?.(); }}>
          {creating ? text("收起新建", "Close new task") : text("新建任务", "Add task")}
        </VNativeButton>
      ) : null}
      </div>

    {errorMessage && !(tasksQuery.error instanceof Error) ? <VStateSurface role="alert" tone="error" density="compact" title={errorMessage} /> : null}
      {isPlanner && creating ? (
        <form
          className={styles.editor}
          onSubmit={(event) => {
            event.preventDefault();
            if (!subject.trim() || createTask.isPending) {
              return;
            }
            createTask.mutate();
          }}
        >
          <div className={styles.editorFields}>
          <label className={styles.field}>{text("任务主题", "Task subject")}
          <VNativeInput
            className={styles.input}
            aria-label={text("任务主题", "Task subject")}
            value={subject}
            placeholder={text("任务主题", "Task subject")}
            onChange={(event) => setSubject(event.target.value)}
          />
          </label>
          <label className={styles.field}>{text("说明与验收", "Description and acceptance")}
          <VNativeTextarea
            className={`${styles.input} ${styles.editorTextarea}`}
            aria-label={text("任务说明", "Task description")}
            value={description}
            placeholder={text("验收标准和边界", "Acceptance and boundary")}
            onChange={(event) => setDescription(event.target.value)}
          />
          </label>
          <div className={styles.formGrid}>
          <label className={styles.field}>{text("写范围", "Write scopes")}
          <VNativeInput
            className={styles.input}
            aria-label={text("写范围", "Write scopes")}
            value={scopes}
            placeholder={text("写范围，例如 web/src/routes/login", "Write scopes, for example web/src/routes/login")}
            onChange={(event) => setScopes(event.target.value)}
          />
          </label>
          <div className={styles.field}>
            <TaskDependencyPicker lang={lang} label={text("依赖任务", "Dependencies")} tasks={tasks} value={blockers} onChange={setBlockers} />
          </div>
          </div>
          <div className={styles.actions}>
          <VStringSelect
            ariaLabel={text("负责人", "Owner")}
            value={ownerId}
            onValueChange={setOwnerId}
            options={[
              { value: "", label: text("先不指定负责人", "No owner yet") },
              ...members.filter((member) => member.role !== "规划师").map((member) => ({
                value: member.memberId,
                label: [member.agentName || member.memberId, member.role].filter(Boolean).join(" · "),
              })),
            ]}
          />
          </div></div>
          <div className={styles.editorFooter}>
          <VButton variant="secondary" isDisabled={createTask.isPending} onClick={() => setCreating(false)}>{text("取消", "Cancel")}</VButton>
          <VNativeButton className={styles.primaryButton} type="submit" disabled={!subject.trim() || createTask.isPending}>
            {createTask.isPending ? text("正在创建", "Creating") : text("创建任务", "Create task")}
          </VNativeButton>
          </div>
        </form>
      ) : null}

    {!creating && selectedTask ? <TaskOperations key={selectedTask.id} lang={lang} teamId={teamId} task={selectedTask}
      members={members} tasks={tasks} actorRole={actorRole} actorId={actorId} pending={changeTask.isPending}
      draft={draft!} onDraftChange={patchDraft}
      onDeselect={() => setSelectedTaskId(null)}
      onAction={(body, onSuccess) => changeTask.mutate(body, { onSuccess })} /> : null}
    {!creating && !selectedTask ? <p className={styles.label}>{text("选择任务后，在这里进行操作。", "Select a task to act on it here.")}</p> : null}
  </section>;
  return renderWorkspace ? renderWorkspace({ display, operations }) : <>{display}{operations}</>;
}

function TaskCard({ lang, teamId, task, members, tasks, selected, onSelect, canReview }: {
  lang: "zh" | "en"; teamId: string; task: DevTeamTask; members: TeamMember[]; tasks: DevTeamTask[];
  selected: boolean; onSelect: () => void; canReview: boolean;
}) {
  const text = (zh: string, en: string) => lang === "zh" ? zh : en;
  const status = STATUS_LABELS[task.status] || { zh: task.status, en: task.status };
  const owner = task.ownerName || members.find(member => member.memberId === task.ownerMemberId)?.agentName;
  const dependencyLabels = task.blockedBy.map(id => {
    const dependency = tasks.find(item => item.id === id);
    return dependency ? `${id} · ${dependency.subject} (${STATUS_LABELS[dependency.status]?.[lang] || dependency.status})` : id;
  });
  return (
    <article className={styles.card} aria-label={task.subject} data-task-selected={selected}>
      <div className={styles.cardHeader}>
        <div className={styles.titleLine}>
          <strong className={styles.title} title={task.subject}>{task.subject}</strong>
          <span className={styles.inlineTaskId}>{task.id}</span>
        </div>
        <div className={styles.headerActions}>
          <VChip tone={task.status === "completed" ? "success" : task.status === "rework" ? "warning" : task.status === "in_progress" ? "info" : "neutral"}>
            {lang === "zh" ? status.zh : status.en}
          </VChip>
          <VNativeButton className={styles.button}
            aria-label={text(`选择任务 ${task.id}`, `Select task ${task.id}`)} aria-pressed={selected}
            onClick={onSelect}>
            {selected ? text("已选中", "Selected") : text("查看", "View")}
          </VNativeButton>
        </div>
      </div>
      {task.description ? <p className={styles.description}>{task.description}</p> : null}
      <dl className={selected ? styles.facts : styles.compactFacts}>
        <div className={styles.fact}>
          <dt className={styles.label}>{text("负责人", "Owner")}</dt>
          <dd className={styles.value}>{[owner, task.ownerRole].filter(Boolean).join(" · ") || text("未指定", "Unassigned")}</dd>
        </div>
        <div className={styles.fact}>
          <dt className={styles.label}>{text("依赖", "Dependencies")}</dt>
          <dd className={styles.value}>{dependencyLabels.join("\n") || text("无依赖", "No dependencies")}</dd>
        </div>
        <div className={styles.fact}>
          <dt className={styles.label}>{text("写范围", "Write scopes")}</dt>
          <dd className={styles.value}>{task.writeScopes.join("\n") || text("未指定", "Unspecified")}</dd>
        </div>
        <div className={styles.fact}>
          <dt className={styles.label}>{text("产出", "Output")}</dt>
          <dd className={styles.value}>{task.workspaceBranch ? `${text("工作区", "Workspace")} ${task.workspaceBranch}` : text("暂无任务工作区", "No task workspace yet")}</dd>
        </div>
      </dl>
      {task.reviewNote ? <p className={styles.description}>{text("退回说明：", "Rework note: ")}{task.reviewNote}</p> : null}
      {task.writeScopeWarnings.map((warning) => (
        <p className={styles.warning} key={warning} role="status">{warning}</p>
      ))}
      {canReview && (task.status === "in_progress" || task.status === "rework" || task.status === "completed") ? (
        <TaskChangeList lang={lang} teamId={teamId} taskId={task.id} />
      ) : null}
    </article>
  );
}
type TaskOperationsDraft = {
  taskId:string; note:string; nextOwner:string; subjectDraft:string; descriptionDraft:string;
  scopeDraft:string; blockerDraft:string; editing:boolean; editRevision:number;
};
function taskOperationsDraft(task:DevTeamTask):TaskOperationsDraft {
  return {taskId:task.id,note:"",nextOwner:task.ownerMemberId,subjectDraft:task.subject,descriptionDraft:task.description,
    scopeDraft:task.writeScopes.join(", "),blockerDraft:task.blockedBy.join(", "),editing:false,editRevision:task.revision};
}

function TaskOperations({
  lang,
  teamId,
  task,
  members,
  tasks,
  actorRole,
  actorId,
  pending,
  onAction,
  onDeselect,
  draft, onDraftChange,
}: {
  lang: "zh" | "en";
  teamId: string;
  task: DevTeamTask;
  members: TeamMember[];
  tasks: DevTeamTask[];
  actorRole: string;
  actorId: string;
  pending: boolean;
  onAction: (body: TaskActionBody, onSuccess?: () => void) => void;
  onDeselect: () => void;
  draft: TaskOperationsDraft;
  onDraftChange: (patch: Partial<TaskOperationsDraft>) => void;
}) {
  const {note,nextOwner,subjectDraft,descriptionDraft,scopeDraft,blockerDraft,editing,editRevision} = draft;
  const setNote = (note:string) => onDraftChange({note});
  const setNextOwner = (nextOwner:string) => onDraftChange({nextOwner});
  const setSubjectDraft = (subjectDraft:string) => onDraftChange({subjectDraft});
  const setDescriptionDraft = (descriptionDraft:string) => onDraftChange({descriptionDraft});
  const setScopeDraft = (scopeDraft:string) => onDraftChange({scopeDraft});
  const setBlockerDraft = (blockerDraft:string) => onDraftChange({blockerDraft});
  const setEditing = (editing:boolean) => onDraftChange({editing});
  const setEditRevision = (editRevision:number) => onDraftChange({editRevision});
  const text = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const owner = task.ownerName || members.find(member => member.memberId === task.ownerMemberId)?.agentName;
  const status = STATUS_LABELS[task.status] || { zh: task.status, en: task.status };
  const canClaim = (actorRole === "开发工程师 A" || actorRole === "开发工程师 B")
    && task.ready
    && (!task.ownerMemberId || task.ownerMemberId === actorId);
  const canReview = actorRole === "评审员";
  const canPlan = actorRole === "规划师";
  const nextScopes = splitList(scopeDraft);
  const nextBlockers = splitList(blockerDraft);
  const sameEdit = subjectDraft.trim() === task.subject
    && descriptionDraft.trim() === task.description
    && nextScopes.join("\n") === task.writeScopes.join("\n")
    && nextBlockers.join("\n") === task.blockedBy.join("\n");
  return (
        <section className={styles.editor} aria-label={text(`任务操作 ${task.id}`, `Task actions ${task.id}`)}>
          <div className={styles.editorHeading}><h3>{text(editing ? "编辑任务" : "任务操作", editing ? "Edit task" : "Task actions")} <span>{task.id}</span></h3>
            <VButton variant="ghost" aria-label={text("取消选择任务", "Clear task selection")} onClick={() => {setEditing(false);onDeselect();}}>×</VButton>
          </div>
          {editing && canPlan && task.status !== "completed" ? <>
          <div className={styles.editorFields}>
            <label className={styles.field}>{text("任务标题", "Task title")}
              <VNativeInput aria-label={text(`修改主题 ${task.id}`, `Edit subject ${task.id}`)} value={subjectDraft}
                onChange={(event) => setSubjectDraft(event.target.value)} />
            </label>
            <label className={styles.field}>{text("说明与验收标准", "Description and acceptance")}
              <VNativeTextarea className={styles.editorTextarea} aria-label={text(`修改说明 ${task.id}`, `Edit description ${task.id}`)} value={descriptionDraft}
                rows={3} onChange={(event) => setDescriptionDraft(event.target.value)} />
            </label>
            <div className={styles.formGrid}>
              <label className={styles.field}>{text("写范围", "Write scopes")}
                <VNativeInput aria-label={text(`修改写范围 ${task.id}`, `Edit write scopes ${task.id}`)} value={scopeDraft}
                  onChange={(event) => setScopeDraft(event.target.value)} />
              </label>
              <TaskDependencyPicker lang={lang} label={text(`修改依赖 ${task.id}`, `Edit dependencies ${task.id}`)} tasks={tasks}
                currentTaskId={task.id} value={blockerDraft} onChange={setBlockerDraft} />
            </div>
            <div className={styles.ownerSection}>
              <span className={styles.label}>{text("负责人", "Owner")}</span>
              <div className={styles.ownerControls}>
                <VStringSelect ariaLabel={text(`改派 ${task.id}`, `Assign ${task.id}`)} value={nextOwner} onValueChange={setNextOwner}
                  options={[
                    { value: "", label: text("暂不指定", "Unassigned") },
                    ...members.filter((member) => member.role !== "规划师" || member.memberId === task.ownerMemberId).map((member) => ({
                      value: member.memberId, label: [member.agentName || member.memberId, member.role].filter(Boolean).join(" · "),
                    })),
                  ]} />
                <VButton variant="secondary" isDisabled={pending || nextOwner === task.ownerMemberId}
                  onClick={() => onAction({ taskId: task.id, action: "assign", expectedRevision: editRevision, ownerMemberId: nextOwner }, () => setEditing(false))}>
                  {text("应用指派", "Apply owner")}
                </VButton>
              </div>
            </div>
          </div>
<div className={styles.editorFooter}>
            <VButton variant="ghost" className={styles.deleteButton} isDisabled={pending}
              onClick={() => onAction({ taskId: task.id, action: "delete", expectedRevision: task.revision }, () => setEditing(false))}>
              {text("删除任务", "Delete task")}
            </VButton>
            <div className={styles.footerMain}>
              <VButton variant="secondary" isDisabled={pending} onClick={() => setEditing(false)}>{text("取消", "Cancel")}</VButton>
              <VButton variant="primary" isDisabled={pending || !subjectDraft.trim() || sameEdit}
                aria-label={text(`保存修改 ${task.id}`, `Save edits ${task.id}`)}
                onClick={() => onAction({
                  taskId: task.id, action: "update", expectedRevision: editRevision,
                  subject: subjectDraft.trim(), description: descriptionDraft.trim(),
                  writeScopes: nextScopes, blockedBy: nextBlockers,
                }, () => setEditing(false))}>
                {text("保存修改", "Save changes")}
              </VButton>
            </div>
          </div>
          </> : <div className={styles.actionSummary}>
            <div className={styles.attributeRow}><span>{text("状态", "Status")}</span><VChip tone={task.status === "completed" ? "success" : "neutral"}>{lang === "zh" ? status.zh : status.en}</VChip></div>
            {canPlan && task.status !== "completed" ? <div className={styles.attributeOwner}><span>{text("负责人", "Owner")}</span>
                <VStringSelect ariaLabel={text(`改派 ${task.id}`, `Assign ${task.id}`)} value={nextOwner} onValueChange={setNextOwner}
                  options={[
                    { value: "", label: text("暂不指定", "Unassigned") },
                    ...members.filter((member) => member.role !== "规划师" || member.memberId === task.ownerMemberId).map((member) => ({
                      value: member.memberId, label: [member.agentName || member.memberId, member.role].filter(Boolean).join(" · "),
                    })),
                  ]} />
                {nextOwner !== task.ownerMemberId ? <VButton variant="secondary" isDisabled={pending || nextOwner === task.ownerMemberId}
                  onClick={() => onAction({ taskId: task.id, action: "assign", expectedRevision: task.revision, ownerMemberId: nextOwner }, () => setEditing(false))}>
                  {text("应用指派", "Apply owner")}
                </VButton> : null}
            </div>
            : <div className={styles.attributeRow}><span>{text("负责人", "Owner")}</span><span>{[owner,task.ownerRole].filter(Boolean).join(" · ") || text("未指定", "Unassigned")}</span></div>}
            <div className={styles.attributeRow}><span>{text("依赖", "Dependencies")}</span><span>{task.blockedBy.length ? text(`${task.blockedBy.length} 个任务`, `${task.blockedBy.length} tasks`) : text("无依赖", "No dependencies")}</span></div>
            {canPlan && task.status !== "completed" ? <VButton variant="secondary" onClick={() => {setEditRevision(task.revision);setEditing(true);}} aria-label={text(`编辑 ${task.id}`, `Edit ${task.id}`)}>{text("编辑任务内容", "Edit task contents")}</VButton> : null}
<div className={styles.actions}>
      {canClaim ? (
        <VNativeButton
          className={styles.primaryButton}
          type="button"
          disabled={pending}
          aria-label={text(`认领 ${task.id}`, `Claim ${task.id}`)}
          onClick={() => onAction({ taskId: task.id, action: "claim", expectedRevision: task.revision })}
        >
          {text("认领", "Claim")}
        </VNativeButton>
      ) : null}
      {canReview && (task.status === "in_progress" || task.status === "rework") ? (
        <VNativeButton
          className={styles.primaryButton}
          type="button"
          disabled={pending}
          onClick={() => onAction({ taskId: task.id, action: "complete", expectedRevision: task.revision })}
        >
          {text("完成", "Complete")}
        </VNativeButton>
      ) : null}
      {canReview && (task.status === "in_progress" || task.status === "completed") ? (
        <>
          <VNativeInput
            className={styles.input}
            aria-label={text(`退回说明 ${task.id}`, `Rework note ${task.id}`)}
            value={note}
            placeholder={text("退回说明", "Rework note")}
            onChange={(event) => setNote(event.target.value)}
          />
          <VNativeButton
            className={styles.button}
            type="button"
            disabled={pending}
            onClick={() => onAction({
              taskId: task.id,
              action: "rework",
              expectedRevision: task.revision,
              reviewNote: note.trim(),
            })}
          >
            {text("退回", "Send back")}
          </VNativeButton>
        </>
      ) : null}

      </div>
          </div>}
        </section>
  );
}

function TaskChangeList({ lang, teamId, taskId }: { lang: "zh" | "en"; teamId: string; taskId: string }) {
  const text = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const changesQuery = useQuery({
    queryKey: ["teams", teamId, "dev-tasks", taskId, "changes"],
    queryFn: ({ signal }) => listDevTeamTaskChanges(teamId, taskId, { signal }),
    enabled: Boolean(teamId && taskId),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });
  const data = changesQuery.data;
  return (
    <div className={styles.changes} aria-label={text(`改动 ${taskId}`, `Changes ${taskId}`)}>
      <strong>{text("工作区改动", "Workspace changes")}</strong>
      <TaskChangeBody lang={lang} loading={changesQuery.isLoading} failed={changesQuery.isError} data={data} text={text} />
    </div>
  );
}

function TaskChangeBody({
  lang,
  loading,
  failed,
  data,
  text,
}: {
  lang: "zh" | "en";
  loading: boolean;
  failed: boolean;
  data: DevTeamTaskChanges | undefined;
  text: (zh: string, en: string) => string;
}) {
  if (loading) {
    return <span>{text("正在看改动", "Looking at the changes")}</span>;
  }
  if (failed || !data || !data.available) {
    return <span>{text("看不出改了什么", "The changes could not be read")}</span>;
  }
  if (!data.workspace) {
    return <span>{text("还没有任务工作区", "No task workspace yet")}</span>;
  }
  if (data.changes.length === 0) {
    return <span>{text("没有改动", "No changes")}</span>;
  }
  return (
    <>
      {data.changes.map((change) => {
        const label = CHANGE_LABELS[change.status] || { zh: change.status, en: change.status };
        return <span key={`${change.status}:${change.path}`}>{lang === "zh" ? label.zh : label.en} {change.path}</span>;
      })}
      {data.truncated > 0 ? <span>{text(`还有 ${data.truncated} 个文件没有列在这里。`, `${data.truncated} more files are not listed.`)}</span> : null}
    </>
  );
}
