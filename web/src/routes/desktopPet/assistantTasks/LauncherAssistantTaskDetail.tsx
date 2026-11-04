import {useState} from "react";
import {VButton,VChip,VDialog} from "../../../components/vui";
import type {AssistantTask} from "./assistantTeamRunTasks";
import type {AssistantDispatchTask} from "./assistantDispatchTasks";
import {taskCleanupTargets} from "./assistantTaskCleanup";
import {dispatchFailureCodeLabel,taskCardOwner,taskCardState,taskCardTitle} from "./assistantTaskPresentation";
import {COPY} from "./assistantTaskCopy";
import {taskDisplayTitle} from "./assistantTaskMetadata";
import styles from "./LauncherAssistantTaskDetail.styles";
type Props={task:AssistantTask;lang:"zh"|"en";actionsEnabled:boolean;cleanupBusy:boolean;onClose:()=>void;onReview:(task:AssistantTask)=>void;onApproval:(task:AssistantDispatchTask)=>void;onDelete:(task:AssistantTask)=>void;onCloseAutoFocus:(event:Event)=>void};
export function LauncherAssistantTaskDetail({task,lang,actionsEnabled,cleanupBusy,onClose,onReview,onApproval,onDelete,onCloseAutoFocus}:Props){
 const [references,setReferences]=useState(false);const copy=COPY[lang];
 const pending=task.kind==="dispatch"&&task.cleanupPending===true;
 const failureLabel=task.state==="failed"?dispatchFailureCodeLabel(task.errorCode,lang):"";
 const localOnly=task.state==="unknown";
 const summary=pending?copy.cleanupRecovery:(task.state==="failed"?task.error:task.resultSummary)||(task.state==="failed"?copy.noFailure:copy.noSummary);
 const title=taskCardTitle(task,lang);const providedTitle=taskDisplayTitle(task.title,"",lang);
 const titleMissing=providedTitle===(lang==="zh"?"委派任务":"Delegated task")||providedTitle!==title;
 const team=task.kind==="team_run"?task.lastKnown??task:null;
 const time=(value:string|undefined)=>value?new Date(value).toLocaleString(lang==="zh"?"zh-CN":"en-GB"):copy.notProvided;
 const ref=(label:string,value:unknown)=><div key={label}><dt className={styles.referenceLabel}>{label}</dt><dd className={styles.referenceValue}>{value==null||value===""?copy.notBound:String(value)}</dd></div>;
 return <VDialog open title={title} size="lg" className={styles.modal}
  data-vui="launcher-task-detail" onOpenChange={open=>{if(!open)onClose();}} onCloseAutoFocus={onCloseAutoFocus}
  footer={<><VButton variant="ghost" tooltip={localOnly?copy.removeRecordHint:undefined} isDisabled={!actionsEnabled||cleanupBusy||!taskCleanupTargets(task).length} onClick={()=>onDelete(task)}>{localOnly?copy.removeRecord:pending?copy.retryCleanup:copy.remove}</VButton>
   <VButton variant="secondary" onClick={onClose}>{lang==="zh"?"关闭":"Close"}</VButton>
   {task.kind==="dispatch"&&task.state==="waiting_user"?<VButton variant="primary" isDisabled={!actionsEnabled} onClick={()=>onApproval(task)}>{copy.approval}</VButton>
    :<VButton variant="primary" isDisabled={!actionsEnabled} onClick={()=>onReview(task)}>{copy.review}</VButton>}</>}>
  <div className={styles.detail}>
  <div className={styles.section}>
  <div className={styles.meta}><span>{copy.owner}：{taskCardOwner(task,lang)}</span><VChip tone={pending?"warning":COPY[lang].states[task.state].tone}>{taskCardState(task,lang)}</VChip></div>
  {titleMissing?<p className={styles.context}>{lang==="zh"?"原任务未提供可读名称，可在关联对话中核对。":"The original task has no readable name. Check its linked conversation."}</p>:null}
  <p className={styles.context}>{copy.project}：{task.projectName||copy.notProvided} · {copy.updated}：{time(task.updatedAt)}</p>
  {task.kind==="team_run"&&!task.currentAgentName?<p className={styles.context}>{lang==="zh"?"来源尚未提供当前负责的 Agent。":"The source has not reported a current responsible Agent."}</p>:null}
  {task.state==="unknown"&&!task.sourceAvailable?<p className={styles.context}>{copy.unknownCached}</p>:null}
  </div>
  <section className={styles.section}><h2 className={styles.heading}>{task.state==="failed"?(lang==="zh"?"失败原因":"Failure reason"):task.state==="awaiting_verification"?(lang==="zh"?"执行结果":"Execution result"):copy.summary}</h2>{failureLabel?<p className={styles.context}>{failureLabel}</p>:null}<p className={styles.summary}>{summary}</p></section>
  {task.state==="failed"&&task.resultSummary?<section className={styles.section}><h2 className={styles.heading}>{copy.summary}</h2><p className={styles.summary}>{task.resultSummary}</p></section>:null}
  {task.state==="awaiting_verification"?<p className={styles.context}>{copy.executionEnded}</p>:null}
  <VButton variant="ghost" density="compact" className="justify-self-start" aria-expanded={references} onClick={()=>setReferences(value=>!value)}>{references?(lang==="zh"?"收起引用信息":"Hide references"):(lang==="zh"?"引用信息":"References")}</VButton>
  {references?<div className={styles.section}>{task.kind==="team_run"&&task.lastKnown?<p className={styles.context}>{copy.lastVerified}</p>:null}<dl className={styles.references}>
   {ref(copy.created+"：",time(task.createdAt))}{ref(copy.projectId,task.projectId)}
   {task.kind==="dispatch"?<>{ref(copy.dispatchId,task.dispatchId)}{ref(copy.nativeTaskId,task.nativeTaskId)}</>:<>
    {ref(copy.current+"：",task.current)}{ref(copy.steps+"：",task.stepCount)}{ref(copy.attempts+"：",task.attemptCount)}
    {ref(copy.requestId,task.requestId)}{ref(copy.teamId,team?.teamId)}{ref(copy.flowId,team?.flowId)}{ref(copy.runId,team?.runId)}{ref(copy.revision,team?.revision)}{ref(copy.observedAt,team?.observedAt)}
   </>}
  </dl></div>:null}
  </div>
 </VDialog>;
}
