import { useState } from "react";

import { LauncherTitlebar } from "../../../app/LauncherTitlebar";
import { LauncherNotificationTopbar } from "../../../app/LauncherNotificationTopbar";
import { LauncherNotificationProvider, usePublishLauncherNotices } from "../../../app/LauncherNotifications";
import { LauncherAssistantWelcome } from "../../../routes/desktopPet/LauncherAssistantWelcome";
import { LauncherAssistantModelControl } from "../../../routes/desktopPet/LauncherAssistantModelControl";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";
import { launcherCatalogStyles as styles } from "./LauncherCatalog.styles";

function NotificationExample() {
  const [connectionFailed, setConnectionFailed] = useState(true);
  const [imageFailed, setImageFailed] = useState(true);
  usePublishLauncherNotices([
    ...(connectionFailed ? [{ id: "preview-connection", kind: "connection" as const, tone: "warning" as const,
      title: "聊天没能刷新", description: "稍后再试一次。", features: ["conversation" as const, "approvals" as const, "tasks" as const],
      details: "聊天记录：ASSISTANT_REQUEST_TIMEOUT", actions: [{ id: "retry", label: "再试一次", run: () => setConnectionFailed(false) }] }] : []),
    ...(imageFailed ? [{ id: "preview-appearance", kind: "appearance" as const, tone: "info" as const,
      title: "外观图片未加载", description: "示例：使用默认外观，不影响聊天。",
      actions: [{ id: "retry", label: "重试", run: () => setImageFailed(false) }] }] : []),
  ]);
  return <LauncherNotificationTopbar lang="zh" />;
}

export function LauncherCatalog() {
  const [prompt, setPrompt] = useState("");
  const [navigationRequested, setNavigationRequested] = useState(false);
  const [modelId, setModelId] = useState("preview-model-a");
  const [modelSettingsRequested, setModelSettingsRequested] = useState(false);

  return (
    <VuiPreviewSection title="Launcher">
      <VuiPreviewCard name="LauncherNotificationTopbar" className={styles.card}>
        <LauncherNotificationProvider><NotificationExample /></LauncherNotificationProvider>
      </VuiPreviewCard>
      <VuiPreviewCard name="LauncherAssistantModelControl" className={styles.card}>
        <LauncherAssistantModelControl lang="zh" modelId={modelId} modelDisplay="示例对话模型"
          choices={["a", "b"].map(id => ({ modelId: `preview-model-${id}`, label: `示例模型 ${id.toUpperCase()}`,
            providerLabel: "示例服务", isDefault: id === "a", providerHealthy: true, missingApiKey: false, availability: "ready" }))}
          pending={false} selectionDisabled={false} onModelChange={setModelId}
          onOpenSettings={() => setModelSettingsRequested(true)} />
        {modelSettingsRequested ? <p role="status">示例：已请求打开模型设置</p> : null}
      </VuiPreviewCard>
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
