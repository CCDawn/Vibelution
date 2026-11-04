import {useEffect,useState} from "react";
import {Bot,LoaderCircle,RefreshCw,Trash2,UsersRound} from "lucide-react";
import {VButton,VTabs,VSkeleton} from "../../../components/vui";
// Approved reuse boundary: use the existing Agent-card recipe as the geometry authority.
// Do not import its Agent/Session directory controller or alter ordinary conversation code.
import agentStyles from "../../AgentConversationDirectory.styles";
import {useLauncherTasks} from "./LauncherTaskContext";
import {taskCardOwner,taskCardState,taskCardTitle} from "./assistantTaskPresentation";
import {taskCleanupTargets,taskGroup} from "./assistantTaskCleanup";
import styles from "./LauncherAssistantTaskSidebar.styles";
import type {AssistantTask} from "./assistantTeamRunTasks";
import {COPY} from "./assistantTaskCopy";

type Group="attention"|"active"|"ended";
function TaskRow({task,lang,onNavigate}:{task:AssistantTask;lang:"zh"|"en";onNavigate?:()=>void}){
 const model=useLauncherTasks()!;
 const title=taskCardTitle(task,lang),owner=taskCardOwner(task,lang),state=taskCardState(task,lang);
 const active=model.selectedId===task.id;
 const localOnly=task.state==="unknown";
 const removeLabel=localOnly?COPY[lang].removeRecord:task.kind==="dispatch"&&task.cleanupPending===true?COPY[lang].retryCleanup:COPY[lang].remove;
 const tone=task.state==="running"||task.state==="stopping"?"running":task.state==="waiting_user"||task.state==="waiting_input"?"approval":task.state==="failed"?"error":"none";
 const indicator=tone==="running"?agentStyles.agentActivityRunning:tone==="approval"?agentStyles.agentActivityApproval:tone==="error"?agentStyles.agentActivityError:"";
 const avatar=task.kind==="team_run"?<UsersRound size={16}/>:task.agentName&&task.agentName!==task.agentId?Array.from(task.agentName)[0]:<Bot size={16}/>;
 return <article aria-label={title} data-assistant-task-id={task.id} tabIndex={-1} data-task-state={task.state} data-task-kind={task.kind} className={styles.row}>
  <VButton variant="ghost" contentLayout="plain" className={[agentStyles.agentRow,active?agentStyles.agentRowActive:""].join(" ")}
   aria-label={[title,owner,state].join(" · ")} aria-haspopup="dialog" aria-expanded={active} data-selected={active?"true":undefined} data-assistant-task-open
   tooltip={[title,owner,state].join(" · ")} onClick={event=>{onNavigate?.();model.openTask(task,event.currentTarget);}}>
   <span className={agentStyles.agentAvatar} aria-hidden="true">{avatar}</span>
   <span className={agentStyles.agentCopy}>
    <span className={agentStyles.agentTitleRow}><span className={agentStyles.agentTitle} data-task-title>{title}</span></span>
    <span className={agentStyles.agentMeta}><span className={agentStyles.agentMetaItem}>{owner} · {state}</span></span>
   </span>
   <span className={agentStyles.agentStatusSlot} aria-label={state} title={state}>
    {tone!=="none"?<span className={[agentStyles.agentActivity,indicator].join(" ")}>
     {tone==="error"?null:<LoaderCircle size={11} aria-hidden="true" className={agentStyles.agentActivitySpinner}/>}
    </span>:null}
   </span>
  </VButton>
  {taskCleanupTargets(task).length>0?<VButton variant="ghost" density="compact" isIconOnly icon={<Trash2 size={14}/>} className={styles.remove}
   aria-label={lang==="zh"?`${localOnly?"移除记录":"清理"}“${title}”`:`${localOnly?"Remove record":"Clean up"} “${title}”`}
   data-assistant-task-cleanup tooltip={localOnly?`${removeLabel} · ${COPY[lang].removeRecordHint}`:`${removeLabel} · ${task.kind==="dispatch"?COPY[lang].dispatchCleanupHint:COPY[lang].teamCleanupHint}`} isDisabled={!model.enabled||model.cleanupBusy}
   onClick={()=>{onNavigate?.();model.remove(task);}}/>:null}
 </article>;
}
export function LauncherAssistantTaskSidebar({lang="zh",onNavigate}:{lang?:"zh"|"en";onNavigate?:()=>void}){
 const model=useLauncherTasks();
 const [chosen,setChosen]=useState<{identity:string|undefined;group:Group}|null>(null);const copy=COPY[lang];
 const groups:Group[]=["attention","active","ended"];
 const initial=groups.find(value=>model?.tasks.some(task=>taskGroup(task)===value))??"attention";
 const settled=Boolean(model?.enabled&&!model.loading&&!model.refreshing);
 useEffect(()=>{
  if(model&&settled&&chosen?.identity!==model.identity)setChosen({identity:model.identity,group:initial});
  else if(model&&settled&&!chosen)setChosen({identity:model.identity,group:initial});
 },[model?.identity,settled,initial,chosen]);
 if(!model)return null;
 const count=(group:Group)=>model.tasks.filter(task=>taskGroup(task)===group).length;
 const group=chosen&&chosen.identity===model.identity?chosen.group:initial;
 const filtered=model.tasks.filter(task=>taskGroup(task)===group);
 const warning=model.unavailable?copy.unavailable:model.teamUnavailable?copy.teamUnavailable:model.partial?copy.teamPartial:model.invalid?copy.invalid:"";
 return <section className={styles.root} aria-label={copy.label} data-assistant-task-cards>
  <header className={styles.toolbar}><span>{lang==="zh"?"任务":"Tasks"}</span><VButton variant="ghost" density="compact" isIconOnly aria-label={copy.refresh} tooltip={copy.refresh} data-assistant-task-refresh icon={<RefreshCw size={13}/>} isPending={model.refreshing} onClick={()=>{void model.refresh();}}/>
   <VButton variant="ghost" density="compact" className={styles.cleanup} data-assistant-task-bulk-cleanup title={copy.cleanupHint} isDisabled={!model.enabled||model.cleanupBusy||!model.canCleanCompleted} isPending={model.cleanupBusy} onClick={model.cleanCompleted}>{copy.cleanup}</VButton>
  </header>
  <VTabs value={group} onValueChange={value=>setChosen({identity:model.identity,group:value as Group})} aria-label={lang==="zh"?"任务分类":"Task categories"}
   className={styles.tabs} listClassName={styles.tabList} triggerClassName={styles.tab}
   items={groups.map(value=>({id:value,label:(value==="attention"?(lang==="zh"?"待处理":"Needs you"):copy[value])+" "+count(value)}))}/>
  {warning?<div className={styles.notice} role="status"><span>{warning}</span><VButton variant="ghost" density="compact" isPending={model.refreshing} onClick={()=>{void model.refresh();}}>{copy.refresh}</VButton></div>:null}
  {model.historyIncomplete||model.legacyUnrecoverable?<p className={styles.notice}>{copy.teamHistory}{model.legacyUnrecoverable?` ${copy.teamLegacy}`:""}</p>:null}
  {model.loading&&!model.tasks.length?<div role="status" aria-label={copy.loading} className={styles.list}><VSkeleton className="h-12"/><VSkeleton className="h-12"/></div>:null}
  <div className={styles.list} data-task-group={group}>{filtered.slice(0,model.shown).map(task=><TaskRow key={task.id} task={task} lang={lang} onNavigate={onNavigate}/>)}</div>
  {!model.loading&&!warning&&!filtered.length?<p className={styles.empty}>{lang==="zh"?"暂无此类任务":"No tasks in this category"}</p>:null}
  {filtered.length>model.shown||model.hasNextPage?<VButton variant="ghost" density="compact" isPending={model.loadingMore} onClick={()=>{void model.more(group);}}>{copy.more}</VButton>:null}
 </section>;
}
