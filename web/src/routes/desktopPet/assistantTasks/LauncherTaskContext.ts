import {createContext,useContext} from "react";
import type {AssistantTask} from "./assistantTeamRunTasks";
import {usePublishLauncherNotices} from "../../../app/LauncherNotifications";
export type TaskReviewRequest={task:AssistantTask;nonce:string;identity:string};
export type LauncherTaskModel={identity?:string;tasks:AssistantTask[];loading:boolean;unavailable:boolean;refreshing:boolean;teamUnavailable:boolean;partial:boolean;historyIncomplete?:boolean;legacyUnrecoverable?:number;invalid:number;enabled:boolean;shown:number;hasNextPage:boolean;loadingMore:boolean;selectedId:string|null;cleanableCount:number;cleanupBusy:boolean;canCleanCompleted:boolean;refresh:()=>Promise<void>;more:(group:"attention"|"active"|"ended")=>Promise<void>;openTask:(task:AssistantTask,trigger?:HTMLElement)=>void;remove:(task:AssistantTask)=>void;cleanCompleted:()=>void;reviewRequest:TaskReviewRequest|null};
export const LauncherTaskContext=createContext<LauncherTaskModel|null>(null);
export const useLauncherTasks=()=>useContext(LauncherTaskContext);

/** The shared task owner publishes once for both desktop and mobile navigation. */
export function usePublishLauncherTaskNotices(model:LauncherTaskModel,lang:"zh"|"en"){
 const warning=model.unavailable||model.teamUnavailable||model.partial||model.invalid>0;
 usePublishLauncherNotices(warning?[{
  id:"assistant-task-status",kind:"connection",tone:"warning",
  title:lang==="zh"?"任务状态未更新":"Task status is out of date",
  description:lang==="zh"?"暂时无法核对部分任务的最新状态。":"The latest status of some tasks could not be verified.",
  actions:[{id:"refresh",label:lang==="zh"?"刷新":"Refresh",pending:model.refreshing,run:model.refresh}],
 }]:[]);
}
