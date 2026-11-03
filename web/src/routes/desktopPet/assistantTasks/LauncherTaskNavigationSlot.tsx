import {useLayoutEffect,useRef,useState,type ReactNode} from "react";
import {createPortal} from "react-dom";
import {launcherAssistantPanelPath} from "../../../app/launcherNavigationModel";
import {LauncherAssistantTaskSidebar} from "./LauncherAssistantTaskSidebar";
import styles from "./LauncherTaskNavigationSlot.styles";

/** Launcher-only extension of its existing Tasks anchor. The navigation owner
 * stays untouched; this component owns only its portal host and scoped hiding.
 * Desktop/mobile use separate hosts over the same task provider. */
export function LauncherTaskNavigationSlot({children,lang,onNavigate}:{children:ReactNode;lang:"zh"|"en";onNavigate?:()=>void}){
 const root=useRef<HTMLDivElement>(null);
 const [host,setHost]=useState<HTMLDivElement|null>(null);
 useLayoutEffect(()=>{
  const matches=root.current?.querySelectorAll<HTMLAnchorElement>('a[href="'+launcherAssistantPanelPath("tasks")+'"]');
  if(matches?.length!==1)return;
  const anchor=matches[0];
  const ownedHost=document.createElement("div");
  ownedHost.dataset.launcherTaskSlot="true";
  anchor.after(ownedHost);setHost(ownedHost);
  return()=>{ownedHost.remove();};
 },[]);
 return <div ref={root} className={[styles.root,host?styles.ready:""].join(" ")} data-launcher-task-navigation>
  {children}
  {host?createPortal(<LauncherAssistantTaskSidebar lang={lang} onNavigate={onNavigate}/>,host):null}
 </div>;
}
