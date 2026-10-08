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
  VNativeSelect,
  VNativeTextarea,
  VSection,
  VStack,
  VStateSurface,
} from "../../components/vui";

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
};

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

export function DevTeamTaskBoard({ lang, teamId, members }: DevTeamTaskBoardProps) {
  const queryClient = useQueryClient();
  const planner = members.find((member) => member.role === "规划师");
  const [actorId, setActorId] = useState(planner?.memberId || members[0]?.memberId || "");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [scopes, setScopes] = useState("");
  const [blockers, setBlockers] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const tasksQuery = useQuery({
    queryKey: taskKey(teamId),
    queryFn: ({ signal }) => listDevTeamTasks(teamId, { signal }),
    enabled: Boolean(teamId),
  });
  const replaceTasks = (data: DevTeamTaskList) => {
    queryClient.setQueryData(taskKey(teamId), data);
  };
  const createTask = useMutation({
    mutationFn: () => createDevTeamTask(teamId, {
      actorMemberId: actorId,
      subject: subject.trim(),
      description: description.trim(),
      writeScopes: splitList(scopes),
      blockedBy: splitList(blockers),
      ownerMemberId: ownerId,
    }),
    onSuccess: (data) => {
      replaceTasks(data);
      setSubject("");
      setDescription("");
      setScopes("");
      setBlockers("");
      setOwnerId("");
    },
  });
  const changeTask = useMutation({
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
      meta={text("群聊仍只记录这一轮讨论", "The room still only keeps this round")}
    >
      <VStack>
      <label>
        {text("当前身份", "Acting as")}
        <VNativeSelect
          aria-label={text("当前身份", "Acting as")}
          value={actorId}
          onChange={(event) => setActorId(event.target.value)}
        >
          {members.map((member) => (
            <option key={member.memberId} value={member.memberId}>
              {member.role}
            </option>
          ))}
        </VNativeSelect>
      </label>
      {isPlanner ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!subject.trim() || createTask.isPending) {
              return;
            }
            createTask.mutate();
          }}
        >
          <VStack>
          <VNativeInput
            aria-label={text("任务主题", "Task subject")}
            value={subject}
            placeholder={text("任务主题", "Task subject")}
            onChange={(event) => setSubject(event.target.value)}
          />
          <VNativeTextarea
            aria-label={text("任务说明", "Task description")}
            value={description}
            placeholder={text("验收标准和边界", "Acceptance and boundary")}
            onChange={(event) => setDescription(event.target.value)}
          />
          <VNativeInput
            aria-label={text("写范围", "Write scopes")}
            value={scopes}
            placeholder={text("写范围，例如 web/src/routes/login", "Write scopes, for example web/src/routes/login")}
            onChange={(event) => setScopes(event.target.value)}
          />
          <VNativeInput
            aria-label={text("依赖任务", "Blocked by")}
            value={blockers}
            placeholder={text("依赖任务编号，例如 task-1", "Blocked by, for example task-1")}
            onChange={(event) => setBlockers(event.target.value)}
          />
          <VNativeSelect
            aria-label={text("负责人", "Owner")}
            value={ownerId}
            onChange={(event) => setOwnerId(event.target.value)}
          >
            <option value="">{text("先不指定负责人", "No owner yet")}</option>
            {members.filter((member) => member.role !== "规划师").map((member) => (
              <option key={member.memberId} value={member.memberId}>
                {member.role}
              </option>
            ))}
          </VNativeSelect>
          <VNativeButton type="submit" disabled={!subject.trim() || createTask.isPending}>
            {text("新建任务", "Add task")}
          </VNativeButton>
          </VStack>
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
      {tasks.map((task) => (
        <TaskCard
          key={task.id}
          lang={lang}
          teamId={teamId}
          task={task}
          members={members}
          actorRole={actorRole}
          actorId={actorId}
          pending={changeTask.isPending}
          onAction={(body) => changeTask.mutate(body)}
        />
      ))}
      </VStack>
    </VSection>
  );
}

function TaskCard({
  lang,
  teamId,
  task,
  members,
  actorRole,
  actorId,
  pending,
  onAction,
}: {
  lang: "zh" | "en";
  teamId: string;
  task: DevTeamTask;
  members: TeamMember[];
  actorRole: string;
  actorId: string;
  pending: boolean;
  onAction: (body: TaskActionBody) => void;
}) {
  const [note, setNote] = useState("");
  const [nextOwner, setNextOwner] = useState(task.ownerMemberId);
  const scopeText = task.writeScopes.join("、");
  const blockerText = task.blockedBy.join("、");
  const [subjectDraft, setSubjectDraft] = useState(task.subject);
  const [descriptionDraft, setDescriptionDraft] = useState(task.description);
  const [scopeDraft, setScopeDraft] = useState(scopeText);
  const [blockerDraft, setBlockerDraft] = useState(blockerText);
  useEffect(() => {
    setSubjectDraft(task.subject);
    setDescriptionDraft(task.description);
    setScopeDraft(scopeText);
    setBlockerDraft(blockerText);
  }, [task.revision, task.subject, task.description, scopeText, blockerText]);
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

  return (
    <article aria-label={task.subject}>
      <VStack>
      <strong>{task.subject}</strong>
      <span>{lang === "zh" ? status.zh : status.en}</span>
      <span>{task.ownerRole || text("未指定", "Unassigned")}</span>
      {task.workspaceBranch ? <span>{text("工作区", "Workspace")} {task.workspaceBranch}</span> : null}
      {task.description ? <p>{task.description}</p> : null}
      {task.writeScopes.length > 0 ? <p>{task.writeScopes.join("、")}</p> : null}
      {task.blockedBy.length > 0 ? <p>{text("依赖", "Blocked by")} {task.blockedBy.join("、")}</p> : null}
      {task.reviewNote ? <p>{task.reviewNote}</p> : null}
      {task.writeScopeWarnings.map((warning) => (
        <p key={warning} role="status">{warning}</p>
      ))}
      {canReview && (task.status === "in_progress" || task.status === "rework" || task.status === "completed") ? (
        <TaskChangeList lang={lang} teamId={teamId} taskId={task.id} />
      ) : null}
      {canClaim ? (
        <VNativeButton
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
            aria-label={text(`退回说明 ${task.id}`, `Rework note ${task.id}`)}
            value={note}
            placeholder={text("退回说明", "Rework note")}
            onChange={(event) => setNote(event.target.value)}
          />
          <VNativeButton
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
        <>
          <VNativeInput
            aria-label={text(`修改主题 ${task.id}`, `Edit subject ${task.id}`)}
            value={subjectDraft}
            placeholder={text("任务主题", "Task subject")}
            onChange={(event) => setSubjectDraft(event.target.value)}
          />
          <VNativeTextarea
            aria-label={text(`修改说明 ${task.id}`, `Edit description ${task.id}`)}
            value={descriptionDraft}
            placeholder={text("验收标准和边界", "Acceptance and boundary")}
            onChange={(event) => setDescriptionDraft(event.target.value)}
          />
          <VNativeInput
            aria-label={text(`修改写范围 ${task.id}`, `Edit write scopes ${task.id}`)}
            value={scopeDraft}
            placeholder={text("写范围，例如 web/src/routes/login", "Write scopes, for example web/src/routes/login")}
            onChange={(event) => setScopeDraft(event.target.value)}
          />
          <VNativeInput
            aria-label={text(`修改依赖 ${task.id}`, `Edit dependencies ${task.id}`)}
            value={blockerDraft}
            placeholder={text("依赖任务编号，例如 task-1", "Blocked by, for example task-1")}
            onChange={(event) => setBlockerDraft(event.target.value)}
          />
          <VNativeButton
            type="button"
            disabled={pending || !subjectDraft.trim() || sameEdit}
            aria-label={text(`保存修改 ${task.id}`, `Save edits ${task.id}`)}
            onClick={() => onAction({
              taskId: task.id,
              action: "update",
              expectedRevision: task.revision,
              subject: subjectDraft.trim(),
              description: descriptionDraft.trim(),
              writeScopes: nextScopes,
              blockedBy: nextBlockers,
            })}
          >
            {text("保存修改", "Save edits")}
          </VNativeButton>
          <VNativeSelect
            aria-label={text(`改派 ${task.id}`, `Assign ${task.id}`)}
            value={nextOwner}
            onChange={(event) => setNextOwner(event.target.value)}
          >
            <option value="">{text("不指定", "Unassigned")}</option>
            {members.filter((member) => member.role !== "规划师").map((member) => (
              <option key={member.memberId} value={member.memberId}>{member.role}</option>
            ))}
          </VNativeSelect>
          <VNativeButton
            type="button"
            disabled={pending}
            onClick={() => onAction({
              taskId: task.id,
              action: "assign",
              expectedRevision: task.revision,
              ownerMemberId: nextOwner,
            })}
          >
            {text("指派", "Assign")}
          </VNativeButton>
          <VNativeButton
            type="button"
            disabled={pending}
            onClick={() => onAction({ taskId: task.id, action: "delete", expectedRevision: task.revision })}
          >
            {text("删除", "Delete")}
          </VNativeButton>
        </>
      ) : null}
      </VStack>
    </article>
  );
}

function TaskChangeList({ lang, teamId, taskId }: { lang: "zh" | "en"; teamId: string; taskId: string }) {
  const text = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const changesQuery = useQuery({
    queryKey: ["teams", teamId, "dev-tasks", taskId, "changes"],
    queryFn: ({ signal }) => listDevTeamTaskChanges(teamId, taskId, { signal }),
    enabled: Boolean(teamId && taskId),
  });
  const data = changesQuery.data;
  return (
    <div aria-label={text(`改动 ${taskId}`, `Changes ${taskId}`)}>
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
