import { Bot, Menu } from "lucide-react";
import { VIconButton, VToolbar } from "../components/vui";
import styles from "./LauncherTitlebar.styles";
export function LauncherTitlebar({lang,desktop,onOpenNavigation}:{lang:"zh"|"en";desktop:boolean;onOpenNavigation:()=>void}) {
  return <VToolbar ariaLabel={lang === "zh" ? "Launcher 顶栏" : "Launcher title bar"} wrap={false} className={`${styles.root} ${desktop ? styles.desktop : ""}`}>
    <VIconButton className={styles.menu} label={lang === "zh" ? "打开功能导航" : "Open navigation"} variant="ghost" icon={<Menu size={18}/>} onClick={onOpenNavigation}/>
    <Bot size={17} aria-hidden="true" className={styles.icon}/><strong className={styles.brand}>Vibelution</strong><span className={styles.subtitle}>{lang === "zh" ? "个人助理" : "Personal assistant"}</span><span className={styles.drag} aria-hidden="true"/>
  </VToolbar>;
}
