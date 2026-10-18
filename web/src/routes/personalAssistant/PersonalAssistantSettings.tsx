import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchPersonalAssistantSettings,
  updatePersonalAssistantModel,
  updatePersonalAssistantSettings,
} from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import type { PersonalAssistantModelChoice } from "../../api/types/personalAssistant";
import { VButton, VDialog, VInput, VStateSurface, VStringSelect } from "../../components/vui";
import styles from "./PersonalAssistantSettings.styles";
import { useShellI18n } from "../../i18n/useShellI18n";

/** Local settings key shares the personal-assistant query prefix for prefix invalidation. */
export const assistantSettingsKey = ["personal-assistant", "settings"] as const;

const COPY = {
  zh: {
    title: "助理设置",
    loading: "正在读取助理设置",
    readFailed: "助理设置读取失败",
    retry: "重试",
    displayName: "助理名称",
    rename: "保存名称",
    renaming: "保存中…",
    appearance: "默认外观",
    appearanceDafeiyu: "大肥鲸",
    appearanceXiaoluo: "小洛",
    model: "对话模型",
    modelDefault: "选择模型",
    modelUnavailable: "暂无可选模型，请先在设置页配置模型库。",
    saved: "已保存",
    saveFailed: "保存失败：",
    channelUnhealthy: "通道不可用",
    channelMissingKey: "未配置 API Key",
  },
  en: {
    title: "Assistant settings",
    loading: "Loading assistant settings",
    readFailed: "Could not read assistant settings",
    retry: "Retry",
    displayName: "Assistant name",
    rename: "Save name",
    renaming: "Saving…",
    appearance: "Default appearance",
    appearanceDafeiyu: "The whale",
    appearanceXiaoluo: "Xiao Luo",
    model: "Chat model",
    modelDefault: "Select a model",
    modelUnavailable: "No selectable models yet. Configure the model library first.",
    saved: "Saved",
    saveFailed: "Save failed: ",
    channelUnhealthy: "Channel unavailable",
    channelMissingKey: "API key missing",
  },
} as const;

export function assistantModelChoiceLabel(choice: PersonalAssistantModelChoice, lang: "zh" | "en"): string {
  const provider = choice.providerLabel ? `${choice.providerLabel} · ` : "";
  if (choice.missingApiKey) return `${provider}${choice.label}（${COPY[lang].channelMissingKey}）`;
  if (choice.providerHealthy === false) return `${provider}${choice.label}（${COPY[lang].channelUnhealthy}）`;
  return `${provider}${choice.label}`;
}

/**
 * Assistant settings dialog: rename, default appearance (whale rig or Xiao
 Luo Live2D — the same assistant, appearance only), and the whitelisted
 * dialogue model. Backend owns every value; nothing is provisioned here.
 */
export function PersonalAssistantSettings({ open, onOpenChange }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: assistantSettingsKey,
    queryFn: ({ signal }) => fetchPersonalAssistantSettings({ signal }),
    enabled: open, staleTime: 0, retry: false,
  });
  const [nameDraft, setNameDraft] = useState("");
  const [namePending, setNamePending] = useState(false);
  const [appearancePending, setAppearancePending] = useState(false);
  const [modelPending, setModelPending] = useState(false);
  const [feedback, setFeedback] = useState("");
  const data = settings.data?.settings;

  useEffect(() => {
    if (open && data) {
      setNameDraft(data.displayName);
      setFeedback("");
    }
  }, [open, data]);

  async function saveName() {
    const next = nameDraft.trim();
    if (!data || namePending || next === data.displayName) return;
    setNamePending(true);
    setFeedback("");
    try {
      await updatePersonalAssistantSettings({ displayName: next });
      await queryClient.invalidateQueries({ queryKey: queryKeys.personalAssistant() });
      await queryClient.invalidateQueries({ queryKey: assistantSettingsKey });
      setFeedback(copy.saved);
    } catch (error) {
      setFeedback(copy.saveFailed + (error instanceof Error ? error.message : ""));
    } finally {
      setNamePending(false);
    }
  }

  async function saveAppearance(characterId: "dafeiyu" | "xiaoluo") {
    if (!data || appearancePending || characterId === data.preferences.characterId) return;
    setAppearancePending(true);
    setFeedback("");
    try {
      await updatePersonalAssistantSettings({ preferences: { characterId } });
      await queryClient.invalidateQueries({ queryKey: queryKeys.personalAssistant() });
      await queryClient.invalidateQueries({ queryKey: assistantSettingsKey });
      setFeedback(copy.saved);
    } catch (error) {
      setFeedback(copy.saveFailed + (error instanceof Error ? error.message : ""));
    } finally {
      setAppearancePending(false);
    }
  }

  async function saveModel(modelId: string) {
    if (!data || modelPending || !modelId || modelId === data.model.currentModelId) return;
    setModelPending(true);
    setFeedback("");
    try {
      await updatePersonalAssistantModel(modelId);
      await queryClient.invalidateQueries({ queryKey: assistantSettingsKey });
      setFeedback(copy.saved);
    } catch (error) {
      setFeedback(copy.saveFailed + (error instanceof Error ? error.message : ""));
    } finally {
      setModelPending(false);
    }
  }

  return <VDialog open={open} onOpenChange={onOpenChange} title={copy.title} size="sm">
    {settings.isError ? <VStateSurface density="compact" tone="error" title={copy.readFailed}
      actions={<VButton variant="secondary" onClick={() => void settings.refetch()}>{copy.retry}</VButton>}>
      {settings.error instanceof Error ? settings.error.message : ""}
    </VStateSurface>
      : settings.isPending || !data ? <VStateSurface density="compact" tone="loading" busy skeletonLines title={copy.loading} />
        : <div className={styles.form}>
          <label className={styles.field}>
            {copy.displayName}
            <div className={styles.nameRow}>
              <VInput value={nameDraft} maxLength={80} onChange={(event) => setNameDraft(event.target.value)}
                aria-label={copy.displayName} />
              <VButton variant="secondary" isPending={namePending}
                isDisabled={!nameDraft.trim() || nameDraft.trim() === data.displayName}
                onClick={() => void saveName()}>{namePending ? copy.renaming : copy.rename}</VButton>
            </div>
          </label>
          <label className={styles.field}>
            {copy.appearance}
            <VStringSelect ariaLabel={copy.appearance} value={data.preferences.characterId}
              isDisabled={appearancePending}
              onValueChange={(value) => { if (value === "dafeiyu" || value === "xiaoluo") void saveAppearance(value); }}
              options={[
                { value: "dafeiyu", label: copy.appearanceDafeiyu },
                { value: "xiaoluo", label: copy.appearanceXiaoluo },
              ]} />
          </label>
          <label className={styles.field}>
            {copy.model}
            {data.model.choices.length ? <VStringSelect ariaLabel={copy.model} value={data.model.currentModelId}
              isDisabled={modelPending} placeholder={copy.modelDefault} onValueChange={(value) => void saveModel(value)}
              options={data.model.choices.map((choice) => ({
                value: choice.modelId,
                label: assistantModelChoiceLabel(choice, lang),
                disabled: choice.providerHealthy === false || choice.missingApiKey,
              }))} />
              : <p className={styles.caption}>{copy.modelUnavailable}</p>}
          </label>
          {feedback ? <p role="status" className={styles.caption}>{feedback}</p> : null}
        </div>}
  </VDialog>;
}
