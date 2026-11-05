import type {AssistantTask} from "./assistantTeamRunTasks";
import {displayText,taskDisplayTitle} from "./assistantTaskMetadata";
import {COPY} from "./assistantTaskCopy";
/** Failure codes survive the API contract (`lastError.code` / `receipt.error.code`)
 * and are display evidence only — they never change task state or unlock actions.
 * Labels translate the code's meaning in restrained zh/en wording; an unknown or
 * missing code yields "" so every caller keeps its existing generic fallback. */
const FAILURE_CODE_LABELS: Record<string, readonly [string, string]> = {
  BACKEND_ERROR: ["后端错误", "Backend error"],
  BACKEND_PROTOCOL_ERROR: ["后端协议错误", "Backend protocol error"],
  BACKEND_RESPONSE_TOO_LARGE: ["后端响应过大", "Backend response too large"],
  BACKEND_TIMEOUT: ["后端超时", "Backend timeout"],
  BACKEND_UNAVAILABLE: ["后端不可用", "Backend unavailable"],
  BROWSER_ACTION_OUTCOME_UNKNOWN: ["浏览器操作结果未知", "Browser action outcome unknown"],
  BROWSER_UNAVAILABLE: ["浏览器不可用", "Browser unavailable"],
  CLEANUP_OWNER_CHANGED: ["清理归属已变化", "Cleanup owner changed"],
  CLEANUP_STALE: ["清理已过期", "Cleanup stale"],
  DELEGATION_GOAL_CONFLICT: ["委派目标冲突", "Delegation goal conflict"],
  DELEGATION_GOAL_INACTIVE: ["委派目标已失效", "Delegation goal inactive"],
  DELEGATION_PERMISSION_DENIED: ["委派权限不足", "Delegation permission denied"],
  DELEGATION_QUOTA_EXHAUSTED: ["委派配额已用尽", "Delegation quota exhausted"],
  DELEGATION_TARGET_DENIED: ["委派目标被拒绝", "Delegation target denied"],
  DISPATCH_ALREADY_CLEANED: ["派遣已清理", "Dispatch already cleaned"],
  DISPATCH_CONFLICT: ["派遣冲突", "Dispatch conflict"],
  DISPATCH_NOT_CONFIRMED: ["派遣未确认", "Dispatch unconfirmed"],
  DISPATCH_NOT_FOUND: ["派遣不存在", "Dispatch not found"],
  DISPATCH_STATE_CORRUPT: ["派遣记录损坏", "Dispatch record corrupt"],
  DISPATCH_STATE_INVALID: ["派遣状态无效", "Invalid dispatch state"],
  DISPATCH_STATE_SHAPE_INVALID: ["派遣记录格式无效", "Dispatch record shape invalid"],
  DISPATCH_STATE_UNKNOWN: ["派遣状态未知", "Dispatch state unknown"],
  GATEWAY_NOT_READY: ["网关未就绪", "Gateway not ready"],
  INVALID_DISPATCH: ["派遣无效", "Invalid dispatch"],
  QUOTA_EXHAUSTED: ["配额已用尽", "Quota exhausted"],
  REAUTHORIZATION_REQUIRED: ["需要重新授权", "Reauthorization required"],
  RUNTIME_IDENTITY_MISMATCH: ["运行时身份不匹配", "Runtime identity mismatch"],
  SUBMISSION_UNCONFIRMED: ["提交未确认", "Submission unconfirmed"],
  TASK_ALREADY_CLEANED: ["任务已清理", "Task already cleaned"],
  TASK_CONFLICT: ["任务冲突", "Task conflict"],
  TASK_NOT_FOUND: ["任务不存在", "Task not found"],
  TASK_NOT_TERMINAL: ["任务尚未结束", "Task not ended yet"],
  TASK_REVISION_CONFLICT: ["任务版本冲突", "Task revision conflict"],
  TASK_SOURCE_INVALID: ["任务来源无效", "Invalid task source"],
  TASK_SOURCE_UNAVAILABLE: ["任务来源不可用", "Task source unavailable"],
  TURN_CONTINUATION_LIMIT: ["达到续跑次数上限", "Continuation limit reached"],
  TURN_FAILED: ["执行轮次失败", "Turn failed"],
};

export function dispatchFailureCodeLabel(code: string | null | undefined, lang: "zh" | "en"): string {
  if (!code) return "";
  // One restrained family label covers every PROJECT_REGISTRY_* variant the
  // backend can report instead of enumerating them here.
  if (code.startsWith("PROJECT_REGISTRY_")) return lang === "zh" ? "项目登记待核对" : "Project registry needs checking";
  return FAILURE_CODE_LABELS[code]?.[lang === "zh" ? 0 : 1] ?? "";
}

export function taskCardTitle(task:AssistantTask,lang:"zh"|"en"){
 const ids=task.kind==="dispatch"?[task.id,task.dispatchId,task.nativeTaskId]:[task.id,task.requestId,task.teamId,task.flowId,task.runId];
 const title=taskDisplayTitle(ids.includes(task.title)?"":task.title,"",lang);
 if(title!==(lang==="zh"?"委派任务":"Delegated task"))return title;
 const supplied=displayText(task.kind==="team_run"?task.teamName:task.agentName,100);
 const owner=supplied!== (task.kind==="team_run"?task.teamId:task.agentId)?supplied:"";
 return owner? (lang==="zh"?owner+(task.kind==="team_run"?"的团队运行":"的委派任务"):owner+(task.kind==="team_run"?" team run":" delegated task")):task.kind==="team_run"?(lang==="zh"?"团队运行记录":"Team run record"):title;
}
export function taskCardOwner(task:AssistantTask,lang:"zh"|"en"){
 if(task.kind==="dispatch"){const name=displayText(task.agentName,100);return name&&name!==task.agentId?name:(lang==="zh"?"负责Agent待确认":"Agent unconfirmed");}
 const team=displayText(task.teamName,100);
 return displayText(task.currentAgentName,100)|| (team&&team!==task.teamId?(lang==="zh"?"团队：":"Team: ")+team:(lang==="zh"?"执行Agent待确认":"Agent unconfirmed"));
}
export function taskCardState(task:AssistantTask,lang:"zh"|"en"){
 const copy=COPY[lang];
 if(task.kind==="dispatch"&&task.cleanupPending)return lang==="zh"?"待清理":"Cleanup pending";
 if(task.state==="unknown")return !task.sourceAvailable?(lang==="zh"?"待同步":"Sync unavailable"):!task.receiptBound?(lang==="zh"?"待核对":"Unconfirmed"):copy.states.unknown.label;
 return task.state==="awaiting_verification"?(lang==="zh"?"已结束":"Ended"):copy.states[task.state].label;
}
