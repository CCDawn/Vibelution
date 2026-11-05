import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import type { LauncherAssistantModelChoice } from "../../api/launcherAssistant";
import styles from "./LauncherAssistantModelControl.styles";
import { VButton, VPopover, VStringSelect } from "../../components/vui";
import { ConversationModelControlTrigger } from "../../components/conversation/ConversationModelControlTrigger";

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
  const modelOptions = [
    ...(!choices.some(choice => choice.modelId === modelId) ? [{ value: modelId, label: modelDisplay }] : []),
    ...choices.map(choice => ({
      value: choice.modelId,
      label: choice.label || choice.modelId,
      disabled: choice.providerHealthy === false || choice.missingApiKey === true,
    })),
  ];
  return <div className={styles.root} data-launcher-assistant-model-control>
    <VPopover open={open} onOpenChange={setOpen} side="top" align="end" sideOffset={6}
      aria-label={zh ? "助理模型" : "Assistant model"} contentClassName={styles.popover}
      trigger={<ConversationModelControlTrigger label={label} open={open} isPending={pending}
        aria-label={`${zh ? "助理模型" : "Assistant model"}: ${label}`}
      />}>
      <p className={styles.fullName}>{label}</p>
      {choices.length ? <VStringSelect ariaLabel={zh ? "切换助理模型" : "Change assistant model"}
        value={modelId} isDisabled={pending || selectionDisabled} options={modelOptions}
        onValueChange={value => { onModelChange(value); setOpen(false); }} /> : null}
      {onOpenSettings ? <VButton variant="ghost" density="compact" isDisabled={pending}
        icon={<SlidersHorizontal size={12} aria-hidden="true" />}
        onClick={() => { setOpen(false); onOpenSettings(); }}>
        {zh ? "模型设置" : "Model settings"}
      </VButton> : null}
    </VPopover>
  </div>;
}
