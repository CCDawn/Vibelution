import { fetchJson } from "./client";

export type DevTeamTaskStatus = "pending" | "in_progress" | "rework" | "completed" | string;

export type DevTeamTask = {
  id: string;
  revision: number;
  subject: string;
  description: string;
  status: DevTeamTaskStatus;
  ownerMemberId: string;
  ownerName: string;
  ownerRole: string;
  blockedBy: string[];
  writeScopes: string[];
  reviewNote: string;
  ready: boolean;
  writeScopeWarnings: string[];
  workspacePath?: string;
  workspaceBranch?: string;
  updatedAt: string;
};

export type DevTeamTaskList = {
  schemaVersion: number;
  teamId: string;
  tasks: DevTeamTask[];
  updatedAt: string;
};

export type DevTeamTaskAction = "assign" | "claim" | "complete" | "rework" | "update" | "delete";

function writeJson<T>(url: string, method: string, body: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listDevTeamTasks(teamId: string, init?: RequestInit) {
  return fetchJson<DevTeamTaskList>(`/api/teams/${encodeURIComponent(teamId)}/dev-tasks`, init);
}

export function createDevTeamTask(
  teamId: string,
  body: {
    actorMemberId: string;
    subject: string;
    description?: string;
    writeScopes?: string[];
    blockedBy?: string[];
    ownerMemberId?: string;
  },
) {
  return writeJson<DevTeamTaskList>(`/api/teams/${encodeURIComponent(teamId)}/dev-tasks`, "POST", body);
}

export function mutateDevTeamTask(
  teamId: string,
  taskId: string,
  body: {
    actorMemberId: string;
    action: DevTeamTaskAction;
    expectedRevision: number;
    ownerMemberId?: string;
    reviewNote?: string;
    subject?: string;
    description?: string;
    writeScopes?: string[];
    blockedBy?: string[];
  },
) {
  return writeJson<DevTeamTaskList>(
    `/api/teams/${encodeURIComponent(teamId)}/dev-tasks/${encodeURIComponent(taskId)}`,
    "POST",
    body,
  );
}
