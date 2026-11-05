import {LauncherAssistantTaskSidebar} from "./LauncherAssistantTaskSidebar";
import styles from "./LauncherTaskNavigationSlot.styles";

/** Explicit Launcher task content; desktop/mobile share the provider in the shell. */
export function LauncherTaskNavigationSlot({lang,onNavigate}:{lang:"zh"|"en";onNavigate?:()=>void}){
 return <div className={styles.root} data-launcher-task-navigation>
  <LauncherAssistantTaskSidebar lang={lang} onNavigate={onNavigate}/>
 </div>;
}
