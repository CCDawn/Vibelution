import type {AssistantTask} from "./assistantTeamRunTasks";
import {displayText,taskDisplayTitle} from "./assistantTaskMetadata";
import {COPY} from "./assistantTaskCopy";
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
