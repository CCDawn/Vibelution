import "../design/route-css/workbench-secondary.tailwind.css";
import { LauncherUpdateTopbar } from "../app/LauncherUpdateTopbar";
import { VDenseOpsPage, VSurface } from "../components/vui";
import { useLauncherLanguage } from "../i18n/useLauncherLanguage";
import styles from "./LauncherUpdatesRoute.styles";
/** Keep the existing serialized update/confirmation behavior behind a stable sidebar destination. */
export function LauncherUpdatesRoute() {
  const lang=useLauncherLanguage();
  return <VDenseOpsPage title={lang === "zh" ? "版本更新" : "Updates"} className={styles.page} bodyClassName={styles.body}>
    <VSurface tone="panel" className={styles.panel}><p className={styles.description}>{lang === "zh" ? "查看当前版本和更新详情。更新仍由 Launcher 保存任务记录并完成重启。" : "View version and update details. Launcher saves task records and manages the restart."}</p><LauncherUpdateTopbar lang={lang}/></VSurface>
  </VDenseOpsPage>;
}
