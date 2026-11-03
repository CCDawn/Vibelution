import {createContext,useContext} from "react";
import type {AssistantTask} from "./assistantTeamRunTasks";
export type TaskReviewRequest={task:AssistantTask;nonce:string;identity:string};
export type LauncherTaskModel={tasks:AssistantTask[];loading:boolean;unavailable:boolean;refreshing:boolean;teamUnavailable:boolean;partial:boolean;invalid:number;enabled:boolean;shown:number;hasNextPage:boolean;loadingMore:boolean;selectedId:string|null;cleanableCount:number;refresh:()=>Promise<void>;more:(group:"attention"|"active"|"ended")=>Promise<void>;openTask:(task:AssistantTask,trigger?:HTMLElement)=>void;cleanCompleted:()=>void;reviewRequest:TaskReviewRequest|null};
export const LauncherTaskContext=createContext<LauncherTaskModel|null>(null);
export const useLauncherTasks=()=>useContext(LauncherTaskContext);
