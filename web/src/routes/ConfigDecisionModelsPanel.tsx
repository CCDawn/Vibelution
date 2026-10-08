import { useEffect, useRef, useState } from "react";

import { testDecisionModel } from "../api/config";
import type { ConfigDecisionModelPreset, ConfigDecisionModelProbe } from "../api/types/config";
import { VButton, VCheckbox, VInput, VSection, VStringSelect } from "../components/vui";
import styles from "./ConfigDecisionModelsPanel.styles";

export type DecisionModelEntry = {
  label: string;
  model_id: string;
  base_url: string;
  min_probability: number;
  enabled: boolean;
  note: string;
};

type DecisionModelMap = Record<string, DecisionModelEntry>;

type ConfigDecisionModelsPanelProps = {
  models: DecisionModelMap;
  handoffModelId: string;
  presets: ConfigDecisionModelPreset[];
  disabled: boolean;
  lang: string;
  onCommit: (models: DecisionModelMap, handoffModelId: string) => void;
};

const MAX_ENTRIES = 24;

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
  presets,
  disabled,
  lang,
  onCommit,
}: ConfigDecisionModelsPanelProps) {
  const zh = lang === "zh";
  const [draft, setDraft] = useState<DecisionModelMap>(models);
  const [handoff, setHandoff] = useState(handoffModelId);
  const [probe, setProbe] = useState<Record<string, ConfigDecisionModelProbe>>({});
  const [probing, setProbing] = useState("");
  const [holdReason, setHoldReason] = useState("");
  const draftRef = useRef(draft);
  const handoffRef = useRef(handoff);
  const pendingCommit = useRef("");
  const dirty = useRef(false);
  const lastApplied = useRef("");
  const lastSent = useRef(snapshot(models, handoffModelId));
  draftRef.current = draft;
  handoffRef.current = handoff;

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

  function remember(nextModels: DecisionModelMap, nextHandoff: string) {
    draftRef.current = nextModels;
    handoffRef.current = nextHandoff;
    setDraft(nextModels);
    setHandoff(nextHandoff);
  }

  function publish(nextModels: DecisionModelMap, nextHandoff: string) {
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

  const full = Object.keys(draft).length >= MAX_ENTRIES;
  const enabledOptions = Object.entries(draft)
    .filter(([, entry]) => entry.enabled)
    .map(([id, entry]) => ({ value: id, label: entry.label || id }));

  return (
    <VSection id="config-decision-models" title={zh ? "决策模型" : "Decision models"} data-testid="config-decision-models">
      <p className={styles.intro}>
        {zh
          ? "这里保存一整类本地决策模型。它们不进入对话槽。可以启用多条，Agent 交接只绑定一条；没绑定就不会调用。配置页不下载权重，也不启动服务。"
          : "Store a class of local decision models here. They stay out of chat slots. Several can be enabled, and agent handoff binds exactly one. No binding means no call. This page does not download weights or start the server."}
      </p>
      {holdReason ? <p className={styles.hold}>{holdReason}</p> : null}
      <div className={styles.actions}>
        {presets.map((preset) => (
          <VButton
            key={preset.presetId}
            isDisabled={disabled || full || Boolean(draft[preset.presetId])}
            onPress={() => {
              if (draftRef.current[preset.presetId] || Object.keys(draftRef.current).length >= MAX_ENTRIES) return;
              publish(
                { ...draftRef.current, [preset.presetId]: entryFromPreset(preset, lang) },
                handoffRef.current,
              );
            }}
          >
            {preset.label}
          </VButton>
        ))}
        <VButton
          isDisabled={disabled || full}
          onPress={() => {
            if (Object.keys(draftRef.current).length >= MAX_ENTRIES) return;
            const id = nextCustomId(draftRef.current);
            publish(
              {
                ...draftRef.current,
                [id]: {
                  label: zh ? "自定义决策模型" : "Custom decision model",
                  model_id: "",
                  base_url: "http://127.0.0.1:8088/v1/systemone",
                  min_probability: 0.8,
                  enabled: true,
                  note: "",
                },
              },
              handoffRef.current,
            );
          }}
        >
          {zh ? "自定义" : "Custom"}
        </VButton>
      </div>
      <label className={styles.narrow}>
        <span>{zh ? "交接使用" : "Handoff uses"}</span>
        <VStringSelect
          ariaLabel={zh ? "交接使用的决策模型" : "Decision model bound to handoff"}
          isDisabled={disabled}
          value={handoff}
          placeholder={zh ? "不绑定" : "Unbound"}
          options={[{ value: "", label: zh ? "不绑定" : "Unbound" }, ...enabledOptions]}
          onValueChange={(value) => publish(draftRef.current, value)}
        />
      </label>
      {Object.entries(draft).map(([id, entry]) => (
        <div key={id} className={styles.card}>
          <div className={styles.cardHeader}>
            <strong className={styles.cardTitle}>{entry.label || id}</strong>
            <VCheckbox
              isSelected={entry.enabled}
              isDisabled={disabled}
              onChange={(selected) => patchEntry(id, { enabled: selected }, true)}
            >
              {zh ? "启用" : "Enabled"}
            </VCheckbox>
          </div>
          {entry.note ? <p className={styles.note}>{entry.note}</p> : null}
          <label className={styles.field}>
            <span>{zh ? "名称" : "Name"}</span>
            <VInput
              value={entry.label}
              disabled={disabled}
              onChange={(event) => patchEntry(id, { label: event.target.value }, false)}
              onBlur={() => publish(draftRef.current, handoffRef.current)}
            />
          </label>
          <label className={styles.field}>
            <span>{zh ? "模型名" : "Model id"}</span>
            <VInput
              value={entry.model_id}
              disabled={disabled}
              onChange={(event) => patchEntry(id, { model_id: event.target.value }, false)}
              onBlur={() => publish(draftRef.current, handoffRef.current)}
            />
          </label>
          <label className={styles.field}>
            <span>{zh ? "本地地址" : "Local URL"}</span>
            <VInput
              value={entry.base_url}
              disabled={disabled}
              onChange={(event) => patchEntry(id, { base_url: event.target.value }, false)}
              onBlur={() => publish(draftRef.current, handoffRef.current)}
            />
          </label>
          <label className={styles.narrow}>
            <span>{zh ? "最低概率" : "Minimum probability"}</span>
            <VInput
              type="number"
              min={0.01}
              max={1}
              step={0.01}
              value={String(entry.min_probability)}
              disabled={disabled}
              onChange={(event) => {
                const value = Number(event.target.value);
                if (Number.isFinite(value)) patchEntry(id, { min_probability: value }, false);
              }}
              onBlur={() => publish(draftRef.current, handoffRef.current)}
            />
          </label>
          <div className={styles.actions}>
            <VButton
              isDisabled={disabled || probing === id}
              onPress={() => {
                setProbing(id);
                void testDecisionModel({ baseUrl: entry.base_url, modelId: entry.model_id })
                  .then((result) => setProbe((current) => ({ ...current, [id]: result })))
                  .catch(() => {
                    setProbe((current) => ({
                      ...current,
                      [id]: { ok: false, error: zh ? "连通检查失败" : "Connectivity check failed" },
                    }));
                  })
                  .finally(() => setProbing(""));
              }}
            >
              {zh ? "检查连通" : "Check connection"}
            </VButton>
            <VButton
              isDisabled={disabled}
              onPress={() => {
                const next = { ...draftRef.current };
                delete next[id];
                publish(next, handoffRef.current === id ? "" : handoffRef.current);
              }}
            >
              {zh ? "删除" : "Remove"}
            </VButton>
          </div>
          {probe[id] ? (
            <p className={styles.probe}>
              {probe[id].ok
                ? `${probe[id].choice ?? ""} ${probe[id].probability ?? ""}`.trim()
                : probe[id].error}
            </p>
          ) : null}
        </div>
      ))}
    </VSection>
  );
}
