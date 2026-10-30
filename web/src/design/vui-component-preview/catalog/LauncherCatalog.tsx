import { useState } from "react";

import { LauncherTitlebar } from "../../../app/LauncherTitlebar";
import { LauncherAssistantWelcome } from "../../../routes/desktopPet/LauncherAssistantWelcome";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";
import { launcherCatalogStyles as styles } from "./LauncherCatalog.styles";

export function LauncherCatalog() {
  const [prompt, setPrompt] = useState("");
  const [navigationRequested, setNavigationRequested] = useState(false);

  return (
    <VuiPreviewSection title="Launcher">
      <VuiPreviewCard name="LauncherTitlebar" className={styles.card}>
        <div className={styles.titlebar}>
          <LauncherTitlebar lang="zh" desktop={false} onOpenNavigation={() => setNavigationRequested(true)} />
          {navigationRequested ? <p role="status">已请求打开功能导航</p> : null}
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="LauncherAssistantWelcome" className={styles.card}>
        <div className={styles.welcome}>
          <LauncherAssistantWelcome lang="zh" onPrompt={setPrompt} />
        </div>
        {prompt ? <p role="status">已选择：{prompt}</p> : null}
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
