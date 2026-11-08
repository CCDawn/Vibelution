import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Bot, ChevronRight, Plus } from "lucide-react";

import { testDecisionModel } from "../api/config";
import type { ConfigDecisionModelPreset, ConfigDecisionModelProbe } from "../api/types/config";
import { VButton, VCheckbox, VChip, VDropdownMenu, VInput, VSection, VStringSelect } from "../components/vui";
import styles from "./ConfigDecisionModelsPanel.styles";

export type DecisionModelEntry = {
  [key: string]: unknown;
  label: string;
  model_id: string;
  base_url: string;
  min_probability: number;
  enabled: boolean;
  note: string;
};

export type DecisionModelMap = Record<string, DecisionModelEntry>;

type ConfigDecisionModelsPanelProps = {
  models: DecisionModelMap;
  handoffModelId: string;
  savedModels?: DecisionModelMap;
  savedHandoffModelId?: string;
  presets: ConfigDecisionModelPreset[];
  disabled: boolean;
  lang: string;
  onCommit: (models: DecisionModelMap, handoffModelId: string) => void;
  /** Local values not yet represented by the parent draft, including incomplete entries. */
  onPendingChange?: (pending: boolean) => void;
  onToggleEnabled?: (id: string, enabled: boolean) => Promise<boolean>;
  onSelectHandoff?: (handoffId: string) => Promise<boolean>;
};

const MAX_ENTRIES = 24;
const ENTRY_FIELDS = new Set(["label", "model_id", "base_url", "min_probability", "enabled", "note"]);

export function readDecisionModelMap(raw: unknown): DecisionModelMap {
  if (!raw || typeof raw !== "object") return {};
  const models: DecisionModelMap = {};
  for (const [id, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== "object") continue;
    const row = value as Record<string, unknown>;
    const probability = typeof row.min_probability === "number"
      ? row.min_probability
      : Number(row.min_probability);
    models[id] = {
      ...row,
      label: typeof row.label === "string" ? row.label : "",
      model_id: typeof row.model_id === "string" ? row.model_id : "",
      base_url: typeof row.base_url === "string" ? row.base_url : "",
      min_probability: Number.isFinite(probability) ? probability : 0.8,
      enabled: row.enabled !== false,
      note: typeof row.note === "string" ? row.note : "",
    };
  }
  return models;
}

function nextCustomId(models: DecisionModelMap): string {
  let index = 1;
  while (models[`custom-${index}`]) {
    index += 1;
  }
  return `custom-${index}`;
}

function entryFromPreset(preset: ConfigDecisionModelPreset, lang: string): DecisionModelEntry {
  return {
    label: preset.label,
    model_id: preset.modelId,
    base_url: preset.baseUrl,
    min_probability: 0.8,
    enabled: true,
    note: lang === "zh" ? preset.noteZh : preset.noteEn,
  };
}

function isLoopbackOrPrivate(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  if (host === "localhost" || host === "127.0.0.1" || host === "::1") return true;
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!match) return false;
  const parts = match.slice(1).map(Number);
  if (parts.some((part) => part > 255)) return false;
  const [first, second] = parts;
  if (first === 10 || first === 127) return true;
  if (first === 192 && second === 168) return true;
  return first === 172 && second >= 16 && second <= 31;
}

function entryReady(entry: DecisionModelEntry): boolean {
  if (!entry.label.trim() || entry.label.trim().length > 80) return false;
  if (!entry.model_id.trim() || entry.model_id.trim().length > 200) return false;
  if (!(entry.min_probability > 0 && entry.min_probability <= 1)) return false;
  if (entry.note.length > 240) return false;
  let url: URL;
  try {
    url = new URL(entry.base_url.trim());
  } catch {
    return false;
  }
  if (url.username || url.password || url.search || url.hash) return false;
  if (url.protocol !== "http:" && url.protocol !== "https:") return false;
  const path = url.pathname.replace(/\/+$/, "") || "/";
  if (path !== "/" && path !== "/v1/systemone") return false;
  return isLoopbackOrPrivate(url.hostname);
}

function catalogReady(models: DecisionModelMap): boolean {
  return Object.values(models).every(entryReady);
}

function canonicalUrl(value: string): string {
  try {
    const url = new URL(value.trim());
    const path = url.pathname.replace(/\/+$/, "") || "/v1/systemone";
    const port = url.port ? `:${url.port}` : "";
    return `${url.protocol}//${url.hostname}${port}${path}`;
  } catch {
    return value.trim();
  }
}

function snapshot(models: DecisionModelMap, handoffModelId: string): string {
  const rows = Object.keys(models).sort().map((id) => {
    const entry = models[id];
    return [
      id,
      entry.label,
      entry.model_id,
      entry.base_url,
      entry.min_probability,
      entry.enabled,
      entry.note,
      Object.keys(entry).filter((key) => !ENTRY_FIELDS.has(key)).sort().map((key) => [key, entry[key]]),
    ];
  });
  return JSON.stringify({ handoffModelId, rows });
}

function sameCatalog(
  local: DecisionModelMap,
  localHandoff: string,
  remote: DecisionModelMap,
  remoteHandoff: string,
): boolean {
  if (localHandoff !== remoteHandoff) return false;
  const localIds = Object.keys(local).sort();
  const remoteIds = Object.keys(remote).sort();
  if (localIds.join("\n") !== remoteIds.join("\n")) return false;
  return localIds.every((id) => {
    const left = local[id];
    const right = remote[id];
    return left.label.trim() === right.label.trim()
      && left.model_id.trim() === right.model_id.trim()
      && canonicalUrl(left.base_url) === canonicalUrl(right.base_url)
      && left.enabled === right.enabled
      && Math.abs(left.min_probability - right.min_probability) < 0.0001
      && left.note.trim() === right.note.trim();
  });
}

export function ConfigDecisionModelsPanel({
  models,
  handoffModelId,
  savedModels,
  savedHandoffModelId,
  presets,
  disabled,
  lang,
  onCommit,
  onPendingChange,
  onToggleEnabled,
  onSelectHandoff,
}: ConfigDecisionModelsPanelProps) {
  const zh = lang === "zh";
  const [draft, setDraft] = useState<DecisionModelMap>(models);
  const [handoff, setHandoff] = useState(handoffModelId);
  const [probe, setProbe] = useState<Record<string, ConfigDecisionModelProbe>>({});
  const probeTargets = useRef<Record<string, string>>({});
  const [probing, setProbing] = useState("");
  const [holdReason, setHoldReason] = useState("");
  const [savingImmediate, setSavingImmediate] = useState(false);
  const [editingId, setEditingId] = useState("");
  const listTriggers = useRef<Record<string, HTMLButtonElement | null>>({});
  const addTrigger = useRef<HTMLButtonElement | null>(null);
  const lastEditingId = useRef("");
  const persistedModels = savedModels ?? models;
  const persistedHandoff = savedHandoffModelId ?? handoffModelId;
  const draftRef = useRef(draft);
  const handoffRef = useRef(handoff);
  const pendingCommit = useRef("");
  const dirty = useRef(false);
  const lastApplied = useRef("");
  const lastSent = useRef(snapshot(models, handoffModelId));
  const lastReportedPending = useRef<boolean | null>(null);
  draftRef.current = draft;
  handoffRef.current = handoff;

  useEffect(() => {
    if (editingId) {
      lastEditingId.current = editingId;
    } else if (lastEditingId.current) {
      (listTriggers.current[lastEditingId.current] ?? addTrigger.current)?.focus();
      lastEditingId.current = "";
    }
  }, [editingId]);

  useEffect(() => {
    const remote = snapshot(models, handoffModelId);
    if (
      pendingCommit.current
      && sameCatalog(draftRef.current, handoffRef.current, models, handoffModelId)
    ) {
      pendingCommit.current = "";
      dirty.current = false;
      lastSent.current = remote;
      lastApplied.current = remote;
      draftRef.current = models;
      handoffRef.current = handoffModelId;
      setDraft(models);
      setHandoff(handoffModelId);
      return;
    }
    if (dirty.current || pendingCommit.current) return;
    if (lastApplied.current === remote) return;
    lastApplied.current = remote;
    lastSent.current = remote;
    draftRef.current = models;
    handoffRef.current = handoffModelId;
    setDraft(models);
    setHandoff(handoffModelId);
  }, [models, handoffModelId]);

  useEffect(() => {
    if (!onPendingChange) return;
    // Saved switch and binding props own immediate actions. Their older local
    // copies must neither create pending text nor hide a retained text draft.
    const comparableDraft = onToggleEnabled
      ? Object.fromEntries(Object.entries(draftRef.current).map(([id, entry]) => [
        id,
        models[id] ? { ...entry, enabled: models[id].enabled } : entry,
      ]))
      : draftRef.current;
    const pending = snapshot(comparableDraft, onSelectHandoff ? handoffModelId : handoffRef.current)
      !== snapshot(models, handoffModelId);
    if (lastReportedPending.current === pending) return;
    lastReportedPending.current = pending;
    onPendingChange(pending);
  }, [draft, handoff, models, handoffModelId, onPendingChange, onToggleEnabled, onSelectHandoff]);

  function remember(nextModels: DecisionModelMap, nextHandoff: string) {
    draftRef.current = nextModels;
    handoffRef.current = nextHandoff;
    setDraft(nextModels);
    setHandoff(nextHandoff);
  }

  function publish(nextModels: DecisionModelMap, nextHandoff: string) {
    // Text drafts may outlive an immediate save. Never publish their old switches
    // or handoff binding back over the latest saved values.
    if (onToggleEnabled) {
      nextModels = Object.fromEntries(Object.entries(nextModels).map(([id, entry]) => [
        id,
        persistedModels[id] ? { ...entry, enabled: persistedModels[id].enabled } : entry,
      ]));
    }
    if (onSelectHandoff) nextHandoff = persistedHandoff;
    const bound = nextModels[nextHandoff];
    const handoffId = bound?.enabled ? nextHandoff : "";
    remember(nextModels, handoffId);
    if (Object.keys(nextModels).length > MAX_ENTRIES || !catalogReady(nextModels)) {
      pendingCommit.current = "";
      dirty.current = true;
      setHoldReason(zh
        ? "地址或模型名还不完整，还没写入配置草稿。"
        : "The address or model id is incomplete, so the draft was not updated.");
      return;
    }
    setHoldReason("");
    const nextSnapshot = snapshot(nextModels, handoffId);
    if (nextSnapshot === lastSent.current) {
      dirty.current = false;
      return;
    }
    lastSent.current = nextSnapshot;
    pendingCommit.current = nextSnapshot;
    dirty.current = true;
    onCommit(nextModels, handoffId);
  }

  function patchEntry(id: string, patch: Partial<DecisionModelEntry>, publishNow: boolean) {
    const current = draftRef.current[id];
    if (!current) return;
    const next = { ...draftRef.current, [id]: { ...current, ...patch } };
    remember(next, handoffRef.current);
    dirty.current = true;
    if (publishNow) publish(next, handoffRef.current);
  }

  async function saveImmediate(save: () => Promise<boolean>) {
    if (disabled || savingImmediate) return;
    setSavingImmediate(true);
    try {
      await save();
    } catch {
      // The owner reports save errors; saved props remain the control authority.
    } finally {
      setSavingImmediate(false);
    }
  }

  function closeEditor() {
    if (!disabled) publish(draftRef.current, handoffRef.current);
    setEditingId("");
  }

  function checkConnection(id: string) {
    const entry = draftRef.current[id];
    if (!entry || disabled || probing) return;
    probeTargets.current[id] = JSON.stringify([entry.base_url, entry.model_id]);
    setProbing(id);
    void testDecisionModel({ baseUrl: entry.base_url, modelId: entry.model_id })
      .then((result) => setProbe((current) => ({ ...current, [id]: result })))
      .catch(() => {
        setProbe((current) => ({
          ...current,
          [id]: { ok: false, error: zh ? "连通检查失败" : "Connectivity check failed" },
        }));
      })
      .finally(() => setProbing((current) => current === id ? "" : current));
  }

  function probeMessage(result: ConfigDecisionModelProbe) {
    return result.ok
      ? `${zh ? "模型响应" : "Model response"}: ${result.choice ?? ""} ${result.probability ?? ""}`.trim()
      : result.error;
  }

  function currentProbe(id: string) {
    const entry = draft[id];
    return entry && probeTargets.current[id] === JSON.stringify([entry.base_url, entry.model_id])
      ? probe[id]
      : undefined;
  }

  const full = Object.keys(draft).length >= MAX_ENTRIES;
  const editingEntry = draft[editingId];
  const activeHandoff = onSelectHandoff ? persistedHandoff : handoff;
  const enabledOptions = Object.entries(onSelectHandoff ? persistedModels : draft)
    .filter(([, entry]) => entry.enabled)
    .map(([id, entry]) => ({ value: id, label: entry.label || id }));

  function addEntry(id: string, entry: DecisionModelEntry) {
    if (disabled || draftRef.current[id] || Object.keys(draftRef.current).length >= MAX_ENTRIES) return;
    publish({ ...draftRef.current, [id]: entry }, handoffRef.current);
    setEditingId(id);
  }

  return (
    <VSection
      id="config-decision-models"
      title={editingEntry ? editingEntry.label || editingId : (zh ? "决策模型" : "Decision models")}
      actions={editingEntry ? (
        <VButton
          variant="ghost"
          isIconOnly
          icon={<ArrowLeft size={18} />}
          aria-label={zh ? "返回用途" : "Back to usage"}
          onPress={closeEditor}
        />
      ) : (
        <VDropdownMenu
          aria-label={zh ? "添加决策模型" : "Add decision model"}
          trigger={<VButton ref={addTrigger} isDisabled={disabled || full} icon={<Plus size={15} />}>{zh ? "添加" : "Add"}</VButton>}
          items={[
            ...presets.map((preset) => ({
              id: preset.presetId,
              label: preset.label,
              disabled: disabled || full || Boolean(draft[preset.presetId]),
              onSelect: () => addEntry(preset.presetId, entryFromPreset(preset, lang)),
            })),
            {
              id: "custom",
              label: zh ? "自定义" : "Custom",
              disabled: disabled || full,
              onSelect: () => addEntry(nextCustomId(draftRef.current), {
                label: zh ? "自定义决策模型" : "Custom decision model",
                model_id: "",
                base_url: "http://127.0.0.1:8088/v1/systemone",
                min_probability: 0.8,
                enabled: true,
                note: "",
              }),
            },
          ]}
        />
      )}
      className={styles.section}
      headerClassName={[styles.header, editingEntry ? styles.editorHeader : ""].join(" ")}
      data-testid="config-decision-models"
    >
      {!editingEntry ? (
        <div className={styles.content}>
          {holdReason ? <p className={styles.hold} role="status">{holdReason}</p> : null}
          <label className={styles.narrow}>
            <span>{zh ? "交接" : "Handoff"}</span>
            <VStringSelect
              ariaLabel={zh ? "交接使用的决策模型" : "Decision model bound to handoff"}
              isDisabled={disabled || savingImmediate}
              value={onSelectHandoff ? persistedHandoff : handoff}
              placeholder={zh ? "不绑定" : "Unbound"}
              options={[{ value: "", label: zh ? "不绑定" : "Unbound" }, ...enabledOptions]}
              onValueChange={(value) => {
                if (onSelectHandoff) {
                  void saveImmediate(() => onSelectHandoff(value));
                } else {
                  publish(draftRef.current, value);
                }
              }}
            />
          </label>
          {!Object.keys(draft).length ? (
            <p className={styles.note}>{zh ? "还没有决策模型" : "No decision models yet"}</p>
          ) : null}
          <ul className={styles.list} aria-label={zh ? "决策模型列表" : "Decision model list"}>
            {Object.entries(draft).map(([id, entry]) => (
              <li key={id} className={styles.row} data-decision-model-id={id}>
                <VButton
                  ref={(button) => { listTriggers.current[id] = button; }}
                  variant="ghost"
                  contentLayout="plain"
                  className={styles.rowButton}
                  isDisabled={disabled}
                  aria-label={zh ? `编辑 ${entry.label || id}` : `Edit ${entry.label || id}`}
                  onPress={() => setEditingId(id)}
                >
                  <Bot size={20} className={styles.rowIcon} />
                  <span className={styles.summary}>
                    <span className={styles.summaryHeading}>
                      <strong className={styles.cardTitle}>{entry.label || id}</strong>
                      {activeHandoff === id ? <VChip tone="info">{zh ? "用于交接" : "Handoff"}</VChip> : null}
                      {!entryReady(entry) ? <VChip tone="warning">{zh ? "待补全" : "Incomplete"}</VChip> : null}
                    </span>
                    <span className={styles.modelId}>{entry.model_id || (zh ? "尚未填写模型名" : "Model id not set")}</span>
                    {currentProbe(id) ? <span className={styles.probe} role="status">{probeMessage(currentProbe(id)!)}</span> : null}
                  </span>
                  <ChevronRight size={16} className={styles.rowIcon} />
                </VButton>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className={styles.editor} data-testid="decision-model-editor">
          {holdReason ? <p className={styles.hold} role="status">{holdReason}</p> : null}
          <div className={styles.formGrid}>
            <label className={styles.field}>
              <span>{zh ? "名称" : "Name"}</span>
              <VInput
                autoFocus
                value={editingEntry.label}
                disabled={disabled}
                onChange={(event) => patchEntry(editingId, { label: event.target.value }, false)}
                onBlur={() => publish(draftRef.current, handoffRef.current)}
              />
            </label>
            <label className={styles.field}>
              <span>{zh ? "模型名" : "Model id"}</span>
              <VInput
                value={editingEntry.model_id}
                disabled={disabled}
                onChange={(event) => patchEntry(editingId, { model_id: event.target.value }, false)}
                onBlur={() => publish(draftRef.current, handoffRef.current)}
              />
            </label>
          </div>
          <label className={styles.field}>
            <span>{zh ? "本地地址" : "Local URL"}</span>
            <VInput
              value={editingEntry.base_url}
              disabled={disabled}
              onChange={(event) => patchEntry(editingId, { base_url: event.target.value }, false)}
              onBlur={() => publish(draftRef.current, handoffRef.current)}
            />
          </label>
          <div className={styles.formGrid}>
            <label className={styles.narrow}>
              <span>{zh ? "最低概率" : "Minimum probability"}</span>
              <VInput
                type="number"
                min={0.01}
                max={1}
                step={0.01}
                value={String(editingEntry.min_probability)}
                disabled={disabled}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isFinite(value)) patchEntry(editingId, { min_probability: value }, false);
                }}
                onBlur={() => publish(draftRef.current, handoffRef.current)}
              />
            </label>
            <div className={styles.field}>
              <span>{zh ? "启用" : "Enabled"}</span>
              <VCheckbox
                aria-label={zh ? `启用 ${editingEntry.label || editingId}` : `Enable ${editingEntry.label || editingId}`}
                isSelected={onToggleEnabled ? (persistedModels[editingId]?.enabled ?? editingEntry.enabled) : editingEntry.enabled}
                isDisabled={disabled || savingImmediate || Boolean(onToggleEnabled && !persistedModels[editingId])}
                onChange={(selected) => {
                  if (onToggleEnabled) {
                    if (persistedModels[editingId]) void saveImmediate(() => onToggleEnabled(editingId, selected));
                  } else {
                    patchEntry(editingId, { enabled: selected }, true);
                  }
                }}
              >
                {zh ? "启用" : "Enabled"}
              </VCheckbox>
          </div>
          </div>
          {editingEntry.note ? <p className={styles.note}>{editingEntry.note}</p> : null}
          <div className={styles.actions}>
            <VButton
              isDisabled={disabled || Boolean(probing)}
              isPending={probing === editingId}
              onPress={() => checkConnection(editingId)}
            >
              {zh ? "检查连通" : "Check connection"}
            </VButton>
            <VButton
              variant="danger"
              isDisabled={disabled}
              onPress={() => {
                const next = { ...draftRef.current };
                delete next[editingId];
                publish(next, handoffRef.current === editingId ? "" : handoffRef.current);
                setEditingId("");
              }}
            >
              {zh ? "删除" : "Remove"}
            </VButton>
          </div>
          {currentProbe(editingId) ? <p className={styles.probe} role="status">{probeMessage(currentProbe(editingId)!)}</p> : null}
        </div>
      )}
    </VSection>
  );
}
