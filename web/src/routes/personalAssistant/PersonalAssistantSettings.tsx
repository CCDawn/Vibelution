import { useEffect, useState, type ReactNode } from "react";
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
import { readPetPreferences, savePetPreferences } from "../desktopPet/desktopPetPreferences";
import { enqueuePetPreferenceOperation } from "../desktopPet/usePetPreferences";

/** Local settings key shares the personal-assistant query prefix for prefix invalidation. */
export const assistantSettingsKey = ["personal-assistant", "settings"] as const;
export type PersonalAssistantSettingsTransport = { cacheKey: readonly unknown[]; invalidationKey?: readonly unknown[] } & Pick<typeof import("../../api/personalAssistant"),
  "fetchPersonalAssistantSettings" | "updatePersonalAssistantSettings" | "updatePersonalAssistantModel">;
const workbenchSettings = { fetchPersonalAssistantSettings, updatePersonalAssistantSettings, updatePersonalAssistantModel };

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
    modelHint: "这是助理新会话的默认模型；在某个会话里手动切换模型只对那个会话生效，不会改这里的默认。",
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
    modelHint: "This is the default for the assistant's new sessions; switching a model inside one session only affects that session and never changes this default.",
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
export function PersonalAssistantSettings({ open, onOpenChange, children, transport, presentation = "dialog" }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children?: ReactNode;
  transport?: PersonalAssistantSettingsTransport;
  presentation?: "dialog" | "page";
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const api = transport ?? workbenchSettings;
  const settingsKey = transport ? [...transport.cacheKey, "settings"] : assistantSettingsKey;
  const identityKey = transport?.invalidationKey ?? transport?.cacheKey ?? queryKeys.personalAssistant();
  const settings = useQuery({
    queryKey: settingsKey,
    queryFn: ({ signal }) => api.fetchPersonalAssistantSettings({ signal }),
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
      await api.updatePersonalAssistantSettings({ displayName: next });
      await queryClient.invalidateQueries({ queryKey: identityKey });
      await queryClient.invalidateQueries({ queryKey: settingsKey });
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
      const update = async () => {
        const response = await api.updatePersonalAssistantSettings({ preferences: { characterId } });
        // Workbench's fallback cache belongs to that host; Launcher reads its native settings.
        if (!transport && response.settings) savePetPreferences({ ...readPetPreferences(), characterId: response.settings.preferences.characterId });
      };
      if (transport) await update(); else await enqueuePetPreferenceOperation(update);
      await queryClient.invalidateQueries({ queryKey: identityKey });
      await queryClient.invalidateQueries({ queryKey: settingsKey });
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
      await api.updatePersonalAssistantModel(modelId);
      await queryClient.invalidateQueries({ queryKey: settingsKey });
      setFeedback(copy.saved);
    } catch (error) {
      setFeedback(copy.saveFailed + (error instanceof Error ? error.message : ""));
    } finally {
      setModelPending(false);
    }
  }

  const content = <>
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
            <span className={styles.caption}>{copy.modelHint}</span>
          </label>
          {children}
          {feedback ? <p role="status" className={styles.caption}>{feedback}</p> : null}
        </div>}
  </>;
  return presentation === "page" ? <div className={styles.page}>{content}</div>
    : <VDialog open={open} onOpenChange={onOpenChange} title={copy.title} size="sm">{content}</VDialog>;
}
