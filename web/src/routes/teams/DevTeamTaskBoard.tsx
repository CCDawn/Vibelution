import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createDevTeamTask,
  listDevTeamTasks,
  mutateDevTeamTask,
  type DevTeamTask,
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
    mutationFn: (body: { taskId: string; action: "assign" | "claim" | "complete" | "rework" | "delete"; expectedRevision: number; ownerMemberId?: string; reviewNote?: string }) =>
      mutateDevTeamTask(teamId, body.taskId, {
        actorMemberId: actorId,
        action: body.action,
        expectedRevision: body.expectedRevision,
        ownerMemberId: body.ownerMemberId,
        reviewNote: body.reviewNote,
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
  task,
  members,
  actorRole,
  actorId,
  pending,
  onAction,
}: {
  lang: "zh" | "en";
  task: DevTeamTask;
  members: TeamMember[];
  actorRole: string;
  actorId: string;
  pending: boolean;
  onAction: (body: { taskId: string; action: "assign" | "claim" | "complete" | "rework" | "delete"; expectedRevision: number; ownerMemberId?: string; reviewNote?: string }) => void;
}) {
  const [note, setNote] = useState("");
  const [nextOwner, setNextOwner] = useState(task.ownerMemberId);
  const text = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const status = STATUS_LABELS[task.status] || { zh: task.status, en: task.status };
  const canClaim = (actorRole === "开发工程师 A" || actorRole === "开发工程师 B")
    && task.ready
    && (!task.ownerMemberId || task.ownerMemberId === actorId);
  const canReview = actorRole === "评审员";
  const canPlan = actorRole === "规划师";

  return (
    <article aria-label={task.subject}>
      <VStack>
      <strong>{task.subject}</strong>
      <span>{lang === "zh" ? status.zh : status.en}</span>
      <span>{task.ownerRole || text("未指定", "Unassigned")}</span>
      {task.description ? <p>{task.description}</p> : null}
      {task.writeScopes.length > 0 ? <p>{task.writeScopes.join("、")}</p> : null}
      {task.blockedBy.length > 0 ? <p>{text("依赖", "Blocked by")} {task.blockedBy.join("、")}</p> : null}
      {task.reviewNote ? <p>{task.reviewNote}</p> : null}
      {task.writeScopeWarnings.map((warning) => (
        <p key={warning} role="status">{warning}</p>
      ))}
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
