import { Bot, Save, SlidersHorizontal } from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";

import type { SessionLlmModelOption } from "../../src/api/types";
import { VButton, VIconButton, VInput, VNativeInput, VPopover } from "../../src/components/vui";
import { validateModelContextWindow } from "../../src/components/conversation/ConversationTurnModelControl";
import controlStyles from "../../src/components/conversation/ConversationTurnModelControl.styles";

type Props = {
  sessionId: string;
  agentId: string;
  configRevision: number;
  model: SessionLlmModelOption;
  contextWindow: number;
  maxContextWindow: number;
  currentReasoningEffort: string;
  pending: boolean;
  errorMessage: string;
  onSave: (parameters: { contextWindow: number; reasoningEffort: string }) => void;
};

function contextStops(maximum: number, custom: number) {
  return [...new Set([
    ...[8_000, 16_000, 32_000, 64_000, 128_000, 256_000, 512_000, 1_000_000, 2_000_000]
      .filter((value) => value < maximum),
    maximum,
    ...(custom > 0 && custom <= maximum ? [custom] : []),
  ])].sort((a, b) => a - b);
}

function contextLabel(value: number) {
  return value % 1_000 === 0 ? `${value / 1_000}K` : value.toLocaleString("zh-CN");
}

export function PreviewModelParametersControl(props: Props) {
  const { model, contextWindow, maxContextWindow, currentReasoningEffort, pending, errorMessage, onSave } = props;
  const [open, setOpen] = useState(false);
  const [contextDraft, setContextDraft] = useState(contextWindow);
  const [effortDraft, setEffortDraft] = useState(currentReasoningEffort);
  const [stops, setStops] = useState(() => contextStops(maxContextWindow, contextWindow));
  const [editingNumber, setEditingNumber] = useState(false);
  const [numberDraft, setNumberDraft] = useState(String(contextWindow));
  const effortStops = [
    { value: "", label: "默认" },
    ...(model.reasoningEffortValues ?? []).map((value) => ({
      value,
      label: model.reasoningEffortOptions?.find((option) => option.value === value)?.label || value,
    })),
  ];
  const contextIndex = Math.max(0, stops.indexOf(contextDraft));
  const effortIndex = Math.max(0, effortStops.findIndex((option) => option.value === effortDraft));
  const numberValidation = validateModelContextWindow(numberDraft, maxContextWindow, "zh");
  const saveContext = editingNumber && numberValidation.valid ? numberValidation.value : contextDraft;
  const dirty = saveContext !== contextWindow || effortDraft !== currentReasoningEffort;

  useEffect(() => {
    setOpen(false);
    setContextDraft(contextWindow);
    setNumberDraft(String(contextWindow));
    setEffortDraft(currentReasoningEffort);
    setStops(contextStops(maxContextWindow, contextWindow));
    setEditingNumber(false);
    // Scope changes reset the draft; save failures leave it intact.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.agentId, props.sessionId, model.modelRef]);

  function commitNumber() {
    if (!numberValidation.valid || pending) return;
    setContextDraft(numberValidation.value);
    setStops((current) => [...new Set([...current, numberValidation.value])].sort((a, b) => a - b));
    setEditingNumber(false);
  }

  return (
    <div className={controlStyles.root}>
      <VPopover
        open={open}
        onOpenChange={(nextOpen) => {
          if (pending) return;
          if (nextOpen && !open) {
            setStops(contextStops(maxContextWindow, contextDraft));
            setEditingNumber(false);
          }
          setOpen(nextOpen);
        }}
        side="top"
        align="end"
        sideOffset={6}
        aria-label="模型参数"
        contentClassName={`${controlStyles.popover} slider-preview-panel`}
        trigger={(
          <VButton
            type="button"
            contentLayout="plain"
            className={controlStyles.trigger}
            isDisabled={pending}
            aria-label={`Agent 模型: ${model.label}`}
            aria-haspopup="dialog"
            aria-expanded={open}
            data-open={open ? "true" : "false"}
          >
            <Bot className={controlStyles.icon} size={12} aria-hidden="true" />
            <span className={controlStyles.label}>{model.label}</span>
            <SlidersHorizontal className={controlStyles.settingsIcon} size={12} aria-hidden="true" />
          </VButton>
        )}
      >
        <div className="slider-preview-fields">
          {effortStops.length > 1 ? (
            <div className="slider-preview-field">
              <div className="slider-preview-heading">
                <span>思考强度</span>
                <output className="slider-preview-value">{effortStops[effortIndex].label}</output>
              </div>
              <VNativeInput
                type="range"
                className="slider-preview-range"
                min={0}
                max={effortStops.length - 1}
                step={1}
                value={effortIndex}
                disabled={pending}
                aria-label="思考强度"
                aria-valuetext={effortStops[effortIndex].label}
                style={{ "--slider-progress": `${effortIndex / (effortStops.length - 1) * 100}%` } as CSSProperties}
                onChange={(event) => setEffortDraft(effortStops[Number(event.target.value)].value)}
              />
              <div className="slider-preview-ticks" aria-hidden="true">
                {effortStops.map((stop) => <span key={stop.value} data-selected={stop.value === effortDraft}>{stop.label}</span>)}
              </div>
            </div>
          ) : null}
          <div className="slider-preview-field">
            <div className="slider-preview-heading">
              <span>上下文上限</span>
              {editingNumber ? (
                <VInput
                  type="number"
                  min={1}
                  max={maxContextWindow}
                  step={1}
                  autoFocus
                  className="slider-preview-number"
                  aria-label="精确上下文大小"
                  aria-invalid={!numberValidation.valid}
                  value={numberDraft}
                  disabled={pending}
                  onChange={(event) => setNumberDraft(event.target.value)}
                  onBlur={commitNumber}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") { event.preventDefault(); commitNumber(); }
                    if (event.key === "Escape") { event.preventDefault(); setEditingNumber(false); }
                  }}
                />
              ) : (
                <VButton
                  type="button"
                  variant="ghost"
                  contentLayout="plain"
                  className="slider-preview-number-trigger"
                  aria-label={`精确设置上下文，当前 ${contextDraft} tokens`}
                  isDisabled={pending}
                  onPress={() => { setNumberDraft(String(contextDraft)); setEditingNumber(true); }}
                >
                  {contextLabel(contextDraft)}
                </VButton>
              )}
            </div>
            <VNativeInput
              type="range"
              className="slider-preview-range"
              min={0}
              max={stops.length - 1}
              step={1}
              value={contextIndex}
              disabled={pending || stops.length < 2}
              aria-label="上下文大小"
              aria-valuetext={`${contextDraft.toLocaleString("zh-CN")} tokens`}
              style={{ "--slider-progress": `${stops.length > 1 ? contextIndex / (stops.length - 1) * 100 : 0}%` } as CSSProperties}
              onChange={(event) => { setContextDraft(stops[Number(event.target.value)]); setEditingNumber(false); }}
            />
            <div className="slider-preview-context-labels" aria-hidden="true">
              <span>{contextLabel(stops[0])}</span>
              <span>{contextLabel(maxContextWindow)}</span>
            </div>
            {editingNumber && !numberValidation.valid ? <p className={controlStyles.error} role="alert">{numberValidation.error}</p> : null}
          </div>
          {errorMessage ? <p className={controlStyles.error} role="alert">{errorMessage}</p> : null}
          <div className={controlStyles.actions}>
            <VIconButton
              type="button"
              label="保存模型参数"
              title="保存"
              variant="ghost"
              className={controlStyles.saveButton}
              icon={<Save size={14} aria-hidden="true" />}
              isPending={pending}
              isDisabled={pending || !dirty || (editingNumber && !numberValidation.valid)}
              onPress={() => onSave({ contextWindow: saveContext, reasoningEffort: effortDraft })}
            />
          </div>
        </div>
      </VPopover>
    </div>
  );
}
