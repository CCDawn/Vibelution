import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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
  VNativeButton,
  VNativeInput,
  VStringSelect,
  VNativeTextarea,
  VSection,
  VStateSurface,
  VChip,
} from "../../components/vui";
import { taskBoardStyles as styles } from "./DevTeamTaskBoard.styles";

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

export function DevTeamTaskBoard({ lang, teamId, members, speakingMemberId = "" }: DevTeamTaskBoardProps) {
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
  const errorMessage = createTask.error instanceof Error
    ? createTask.error.message
    : changeTask.error instanceof Error
      ? changeTask.error.message
      : tasksQuery.error instanceof Error
        ? tasksQuery.error.message
        : "";
  const text = (zh: string, en: string) => (lang === "zh" ? zh : en);

  return (
    <VSection
      aria-label={text("共享任务板", "Shared task board")}
      title={text("共享任务板", "Shared task board")}
      className={styles.root}
      meta={text(`${tasks.length} 个任务`, `${tasks.length} tasks`)}
    >
      <div className={styles.toolbar}>
        <div className={styles.summary} aria-label={text("任务概览", "Task summary")}>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <span key={key}>{lang === "zh" ? label.zh : label.en} {tasks.filter((task) => task.status === key).length}</span>
          ))}
        </div>
      <div className={styles.actor}>
        {text("当前身份", "Acting as")}
        <strong aria-label={text("当前身份", "Acting as")}>{actorRole || text("未指定", "Unassigned")}</strong>
      {isPlanner ? (
        <VNativeButton className={styles.primaryButton} aria-expanded={creating} onClick={() => setCreating(!creating)}>
          {creating ? text("收起新建", "Close new task") : text("新建任务", "Add task")}
        </VNativeButton>
      ) : null}
      </div>
      </div>
      {isPlanner && creating ? (
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            if (!subject.trim() || createTask.isPending) {
              return;
            }
            createTask.mutate();
          }}
        >
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
            className={styles.input}
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
          <label className={styles.field}>{text("依赖任务编号", "Dependency IDs")}
          <VNativeInput
            className={styles.input}
            aria-label={text("依赖任务", "Blocked by")}
            value={blockers}
            placeholder={text("依赖任务编号，例如 task-1", "Blocked by, for example task-1")}
            onChange={(event) => setBlockers(event.target.value)}
          />
          </label>
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
                label: member.role,
              })),
            ]}
          />
          <VNativeButton className={styles.primaryButton} type="submit" disabled={!subject.trim() || createTask.isPending}>
            {createTask.isPending ? text("正在创建", "Creating") : text("创建任务", "Create task")}
          </VNativeButton>
          </div>
        </form>
      ) : null}
      {errorMessage ? (
        <VStateSurface tone="error" density="compact" title={errorMessage} role="alert" />
      ) : null}
      {tasksQuery.isLoading ? (
        <VStateSurface tone="loading" density="compact" title={text("正在读取任务板", "Loading tasks")} />
      ) : null}
      {!tasksQuery.isLoading && tasks.length === 0 ? (
        <VStateSurface tone="empty" density="compact" title={text("还没有任务", "No tasks yet")}>
          {text("规划师新建后，工程师认领，评审员收口或退回。", "The planner adds a task, an engineer claims it, and the reviewer closes or sends it back.")}
        </VStateSurface>
      ) : null}
      <div className={styles.list}>
      {tasks.map((task) => (
        <TaskCard
          key={task.id}
          lang={lang}
          teamId={teamId}
          task={task}
          members={members}
          tasks={tasks}
          actorRole={actorRole}
          actorId={actorId}
          pending={changeTask.isPending}
          onAction={(body, onSuccess) => changeTask.mutate(body, { onSuccess })}
        />
      ))}
      </div>
    </VSection>
  );
}

function TaskCard({
  lang,
  teamId,
  task,
  members,
  tasks,
  actorRole,
  actorId,
  pending,
  onAction,
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
}) {
  const [note, setNote] = useState("");
  const [nextOwner, setNextOwner] = useState(task.ownerMemberId);
  const scopeText = task.writeScopes.join(", ");
  const blockerText = task.blockedBy.join(", ");
  const [subjectDraft, setSubjectDraft] = useState(task.subject);
  const [descriptionDraft, setDescriptionDraft] = useState(task.description);
  const [scopeDraft, setScopeDraft] = useState(scopeText);
  const [blockerDraft, setBlockerDraft] = useState(blockerText);
  const [editing, setEditing] = useState(false);
  const [editRevision, setEditRevision] = useState(task.revision);
  useEffect(() => {
    if (editing) return;
    setSubjectDraft(task.subject);
    setDescriptionDraft(task.description);
    setScopeDraft(scopeText);
    setBlockerDraft(blockerText);
    setNextOwner(task.ownerMemberId);
  }, [editing, task.revision, task.subject, task.description, task.ownerMemberId, scopeText, blockerText]);
  const text = (zh: string, en: string) => (lang === "zh" ? zh : en);
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
  const owner = task.ownerName || members.find((member) => member.memberId === task.ownerMemberId)?.agentName;
  const dependencyLabels = task.blockedBy.map((id) => {
    const dependency = tasks.find((item) => item.id === id);
    if (!dependency) return id;
    const label = STATUS_LABELS[dependency.status];
    const dependencyStatus = label ? (lang === "zh" ? label.zh : label.en) : dependency.status;
    return `${id} · ${dependency.subject} (${dependencyStatus})`;
  });
  const nextStep = task.status === "completed"
    ? text("已完成，可查看产出", "Completed; inspect the output")
    : task.status === "in_progress"
      ? text("负责人继续实现，评审员检查改动后收口", "Owner continues implementation; reviewer checks the changes")
      : task.status === "rework"
        ? text("负责人按退回说明修改，再交评审员检查", "Owner addresses the rework note, then requests another review")
        : !task.ready
          ? text("检查依赖与写范围，满足条件后再认领", "Check dependencies and write scopes before claiming")
          : task.ownerMemberId
            ? text("等待负责人认领并开始", "Waiting for the assigned owner to claim and start")
            : text("可由开发工程师认领开始", "Ready for an engineer to claim and start");

  return (
    <article className={styles.card} aria-label={task.subject}>
      <div className={styles.cardHeader}>
        <strong className={styles.title}>{task.subject}</strong>
        <VChip tone={task.status === "completed" ? "success" : task.status === "rework" ? "warning" : task.status === "in_progress" ? "info" : "neutral"}>
          {lang === "zh" ? status.zh : status.en}
        </VChip>
      </div>
      <span className={styles.taskId}>{task.id}</span>
      {task.description ? <p className={styles.description}>{task.description}</p> : null}
      <dl className={styles.facts}>
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
      <div className={styles.next}><span className={styles.label}>{text("下一步", "Next step")}</span><span className={styles.value}>{nextStep}</span></div>
      {task.reviewNote ? <p className={styles.description}>{text("退回说明：", "Rework note: ")}{task.reviewNote}</p> : null}
      {task.writeScopeWarnings.map((warning) => (
        <p className={styles.warning} key={warning} role="status">{warning}</p>
      ))}
      {canReview && (task.status === "in_progress" || task.status === "rework" || task.status === "completed") ? (
        <TaskChangeList lang={lang} teamId={teamId} taskId={task.id} />
      ) : null}
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
      {canPlan && task.status !== "completed" ? (
        <VNativeButton className={styles.button} aria-label={text(`编辑 ${task.id}`, `Edit ${task.id}`)} aria-expanded={editing} onClick={() => {
          if (!editing) setEditRevision(task.revision);
          setEditing(!editing);
        }}>{editing ? text("收起编辑", "Close editor") : text("编辑任务", "Edit task")}</VNativeButton>
      ) : null}
      </div>
      {canPlan && task.status !== "completed" && editing ? (
        <div className={styles.form}>
          <VNativeInput
            className={styles.input}
            aria-label={text(`修改主题 ${task.id}`, `Edit subject ${task.id}`)}
            value={subjectDraft}
            placeholder={text("任务主题", "Task subject")}
            onChange={(event) => setSubjectDraft(event.target.value)}
          />
          <VNativeTextarea
            className={styles.input}
            aria-label={text(`修改说明 ${task.id}`, `Edit description ${task.id}`)}
            value={descriptionDraft}
            placeholder={text("验收标准和边界", "Acceptance and boundary")}
            onChange={(event) => setDescriptionDraft(event.target.value)}
          />
          <VNativeInput
            className={styles.input}
            aria-label={text(`修改写范围 ${task.id}`, `Edit write scopes ${task.id}`)}
            value={scopeDraft}
            placeholder={text("写范围，例如 web/src/routes/login", "Write scopes, for example web/src/routes/login")}
            onChange={(event) => setScopeDraft(event.target.value)}
          />
          <VNativeInput
            className={styles.input}
            aria-label={text(`修改依赖 ${task.id}`, `Edit dependencies ${task.id}`)}
            value={blockerDraft}
            placeholder={text("依赖任务编号，例如 task-1", "Blocked by, for example task-1")}
            onChange={(event) => setBlockerDraft(event.target.value)}
          />
          <VNativeButton
            className={styles.primaryButton}
            type="button"
            disabled={pending || !subjectDraft.trim() || sameEdit}
            aria-label={text(`保存修改 ${task.id}`, `Save edits ${task.id}`)}
            onClick={() => onAction({
              taskId: task.id,
              action: "update",
              expectedRevision: editRevision,
              subject: subjectDraft.trim(),
              description: descriptionDraft.trim(),
              writeScopes: nextScopes,
              blockedBy: nextBlockers,
            }, () => setEditing(false))}
          >
            {text("保存修改", "Save edits")}
          </VNativeButton>
          <VStringSelect
            ariaLabel={text(`改派 ${task.id}`, `Assign ${task.id}`)}
            value={nextOwner}
            onValueChange={setNextOwner}
            options={[
              { value: "", label: text("不指定", "Unassigned") },
              ...members.filter((member) => member.role !== "规划师").map((member) => ({
                value: member.memberId,
                label: member.role,
              })),
            ]}
          />
          <VNativeButton
            className={styles.button}
            type="button"
            disabled={pending}
            onClick={() => onAction({
              taskId: task.id,
              action: "assign",
              expectedRevision: editRevision,
              ownerMemberId: nextOwner,
            }, () => setEditing(false))}
          >
            {text("指派", "Assign")}
          </VNativeButton>
          <VNativeButton
            className={styles.button}
            type="button"
            disabled={pending}
            onClick={() => onAction({ taskId: task.id, action: "delete", expectedRevision: task.revision })}
          >
            {text("删除", "Delete")}
          </VNativeButton>
        </div>
      ) : null}
    </article>
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
