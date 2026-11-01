import "../design/route-css/workbench-secondary.tailwind.css";
import { LauncherUpdateTopbar } from "../app/LauncherUpdateTopbar";
import { VDenseOpsPage } from "../components/vui";
import { useLauncherLanguage } from "../i18n/useLauncherLanguage";
import styles from "./LauncherUpdatesRoute.styles";

export function LauncherUpdatesRoute() {
  const lang = useLauncherLanguage();
  return <VDenseOpsPage hideHeader className={styles.page} bodyClassName={styles.body}>
    <h1 className={styles.title}>{lang === "zh" ? "版本更新" : "Updates"}</h1>
    <LauncherUpdateTopbar lang={lang} />
  </VDenseOpsPage>;
}
