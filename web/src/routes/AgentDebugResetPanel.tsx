import { RefreshCw } from "lucide-react";

import { VButton, VContextualHint, VNativeInput } from "../components/vui";
import styles from "./AgentDebugResetPanel.styles";

export type AgentResetOptions = {
  clearRuntimeState: boolean;
  resetDirectSession: boolean;
  resetPersonaProfile: boolean;
  resetTaskProfile: boolean;
  resetToolPolicy: boolean;
  resetMemoryPolicy: boolean;
  resetRuntimePolicy: boolean;
};

export type AgentDebugResetPanelCopy = {
  resetAgent: string;
  resetAgentTitle: string;
  resetAgentHint: string;
  resettingAgent: string;
  resetClearRuntimeState: string;
  resetClearRuntimeStateHint: string;
  resetDirectSession: string;
  resetDirectSessionHint: string;
  resetPersonaProfile: string;
  resetPersonaProfileHint: string;
  resetTaskProfile: string;
  resetTaskProfileHint: string;
  resetToolPolicy: string;
  resetToolPolicyHint: string;
  resetMemoryPolicy: string;
  resetMemoryPolicyHint: string;
  resetRuntimePolicy: string;
  resetRuntimePolicyHint: string;
};

type ResetOptionKey = keyof AgentResetOptions;

type ResetOptionRow = {
  key: ResetOptionKey;
  label: keyof Pick<
    AgentDebugResetPanelCopy,
    | "resetClearRuntimeState"
    | "resetDirectSession"
    | "resetPersonaProfile"
    | "resetTaskProfile"
    | "resetToolPolicy"
    | "resetMemoryPolicy"
    | "resetRuntimePolicy"
  >;
  hint: keyof Pick<
    AgentDebugResetPanelCopy,
    | "resetClearRuntimeStateHint"
    | "resetDirectSessionHint"
    | "resetPersonaProfileHint"
    | "resetTaskProfileHint"
    | "resetToolPolicyHint"
    | "resetMemoryPolicyHint"
    | "resetRuntimePolicyHint"
  >;
};

const resetOptionRows: ResetOptionRow[] = [
  { key: "clearRuntimeState", label: "resetClearRuntimeState", hint: "resetClearRuntimeStateHint" },
  { key: "resetDirectSession", label: "resetDirectSession", hint: "resetDirectSessionHint" },
  { key: "resetPersonaProfile", label: "resetPersonaProfile", hint: "resetPersonaProfileHint" },
  { key: "resetTaskProfile", label: "resetTaskProfile", hint: "resetTaskProfileHint" },
  { key: "resetToolPolicy", label: "resetToolPolicy", hint: "resetToolPolicyHint" },
  { key: "resetMemoryPolicy", label: "resetMemoryPolicy", hint: "resetMemoryPolicyHint" },
  { key: "resetRuntimePolicy", label: "resetRuntimePolicy", hint: "resetRuntimePolicyHint" },
];

type AgentDebugResetPanelProps = {
  copy: AgentDebugResetPanelCopy;
  options: AgentResetOptions;
  canReset: boolean;
  pending: boolean;
  onOptionChange: (key: ResetOptionKey, value: boolean) => void;
  onReset: () => void;
};

export function AgentDebugResetPanel({
  copy,
  options,
  canReset,
  pending,
  onOptionChange,
  onReset,
}: AgentDebugResetPanelProps) {
  return (
    <section className={styles.resetZone}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.resetAgentTitle}</p>
          <h3 className="inline-flex items-center gap-1.5">
            {copy.resetAgent}
            <VContextualHint content={copy.resetAgentHint} label={`${copy.resetAgentTitle}说明`} tone="danger" />
          </h3>
        </div>
        <RefreshCw size={16} />
      </div>
      <div className={styles.resetOptionGrid}>
        {resetOptionRows.map((row) => (
          <label key={row.key} className={styles.resetOptionField}>
            <VNativeInput
              type="checkbox"
              checked={options[row.key]}
              onChange={(event) => onOptionChange(row.key, event.target.checked)}
            />
            <span>
              <strong className="inline-flex items-center gap-1.5">
                {copy[row.label]}
                <VContextualHint content={copy[row.hint]} label={`${copy[row.label]}说明`} tone="warning" />
              </strong>
            </span>
          </label>
        ))}
      </div>
      <div className={styles.editorActions}>
        <VButton
          type="button"
          variant="secondary"
          icon={<RefreshCw size={15} />}
          isDisabled={!canReset || pending}
          tooltip={copy.resetAgentHint}
          disabledReason={!canReset ? copy.resetAgentHint : copy.resettingAgent}
          onPress={onReset}
        >
          {pending ? copy.resettingAgent : copy.resetAgent}
        </VButton>
      </div>
    </section>
  );
}
