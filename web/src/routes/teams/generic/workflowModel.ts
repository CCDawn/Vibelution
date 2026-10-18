import type { Team, TeamMember } from "../../../api/types";
import type { TeamFlow, WorkflowInput, WorkflowStep, TeamFlowRun } from "../../../api/types/genericTeamWorkflow";

export type Flow = TeamFlow;
export type InputField = WorkflowInput;
export type Step = WorkflowStep;
export type StepKind = WorkflowStep["kind"];
export type Run = TeamFlowRun;
export type WorkflowMember = { id: string; name: string; initial: string; detail: string; available: boolean };
export const KIND_LABEL: Record<StepKind, string> = { input: "用户输入", agent: "Agent 任务", human: "人工确认", output: "交付结果", research: "研究故障监督", session: "会话故障监督" };
// Source supervision is configured through the typed API, not this editor.
export const isEditableWorkflow = (flow: Flow): boolean => !flow.steps.some(step => step.kind === "research" || step.kind === "session");
export const copyFlow = (flow: Flow): Flow => structuredClone(flow);
export const memberName = (id: string, members: WorkflowMember[]) => members.find(member => member.id === id)?.name || id || "未分配";

export function workflowMembers(team: Team | undefined): WorkflowMember[] {
  return (team?.members ?? []).map((member: TeamMember) => {
    const name = member.agentName || member.agentCode || member.role || member.agentId;
    return { id: member.agentId, name, initial: name.slice(0, 1), detail: member.role || member.purpose, available: member.agentStatus === "active" };
  });
}

export function missingInputLabels(flow: Flow, values: Record<string, string>): string[] {
  return flow.fields.filter(field => field.required && !values[field.id]?.trim()).map(field => field.label);
}

export function sameFlowContent(a: Flow, b: Flow): boolean {
  const content = (flow: Flow) => JSON.stringify([flow.id, flow.name, flow.description, flow.fields, flow.steps]);
  return content(a) === content(b);
}

export function mergeSavedFlows(local: Flow[], saved: Flow[], dirtyIds: string[]): Flow[] {
  const dirty = new Set(dirtyIds);
  return [...saved.map(flow => dirty.has(flow.id) ? local.find(item => item.id === flow.id) ?? flow : flow),
    ...local.filter(flow => dirty.has(flow.id) && !saved.some(item => item.id === flow.id))];
}
