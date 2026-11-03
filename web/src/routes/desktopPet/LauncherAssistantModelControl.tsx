import { Bot, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import type { LauncherAssistantModelChoice } from "../../api/launcherAssistant";
import styles from "../../components/conversation/ConversationTurnModelControl.styles";
import { VButton, VNativeSelect, VPopover } from "../../components/vui";

/** Native Launcher model actions in the shared conversation toolbar recipe. */
export function LauncherAssistantModelControl({
  lang, modelId, modelDisplay, choices = [], pending, selectionDisabled,
  onModelChange, onOpenSettings,
}: {
  lang: "zh" | "en";
  modelId: string;
  modelDisplay: string;
  choices?: LauncherAssistantModelChoice[];
  pending: boolean;
  selectionDisabled: boolean;
  onModelChange: (modelId: string) => void;
  onOpenSettings?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const zh = lang === "zh";
  const label = choices.find(choice => choice.modelId === modelId)?.label || modelDisplay;
  return <div className={styles.root} data-launcher-assistant-model-control>
    <VPopover open={open} onOpenChange={setOpen} side="top" align="end" sideOffset={6}
      aria-label={zh ? "助理模型" : "Assistant model"} contentClassName={styles.popover}
      trigger={<VButton type="button" contentLayout="plain" className={styles.trigger}
        isDisabled={pending} aria-haspopup="dialog" aria-expanded={open}
        aria-busy={pending || undefined}
        aria-label={`${zh ? "助理模型" : "Assistant model"}: ${label}`}
        data-open={open ? "true" : "false"} title={label}>
        <Bot className={styles.icon} size={12} aria-hidden="true" />
        <span className={styles.label}>{label}</span>
        <SlidersHorizontal className={styles.settingsIcon} size={12} aria-hidden="true" />
      </VButton>}>
      <p className={styles.fullName}>{label}</p>
      {choices.length ? <VNativeSelect aria-label={zh ? "切换助理模型" : "Change assistant model"}
        value={modelId} disabled={pending || selectionDisabled}
        onChange={event => { onModelChange(event.currentTarget.value); setOpen(false); }}>
        {!choices.some(choice => choice.modelId === modelId) ? <option value={modelId}>{modelDisplay}</option> : null}
        {choices.map(choice => <option key={choice.modelId} value={choice.modelId}
          disabled={choice.providerHealthy === false || choice.missingApiKey === true}>
          {choice.label || choice.modelId}
        </option>)}
      </VNativeSelect> : null}
      {onOpenSettings ? <VButton variant="ghost" density="compact" isDisabled={pending}
        icon={<SlidersHorizontal size={12} aria-hidden="true" />}
        onClick={() => { setOpen(false); onOpenSettings(); }}>
        {zh ? "模型设置" : "Model settings"}
      </VButton> : null}
    </VPopover>
  </div>;
}
