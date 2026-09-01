import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MessageCircleHeart, Trash2 } from "lucide-react";

import { queryKeys } from "../../api/queryKeys";
import type {
  VirtualHumanCompanionPreferenceCard as PreferenceCard,
  VirtualHumanCompanionPreferenceKind,
  VirtualHumanCompanionPreferenceProjection,
} from "../../api/types";
import { executeVirtualHumanCommand } from "../../api/virtualHumanLife";
import { VButton, VInput, VSelect } from "../../components/vui";
import styles from "./CompanionChatRails.styles";

const PREFERENCE_KINDS: VirtualHumanCompanionPreferenceKind[] = [
  "address",
  "response_length",
  "question_tolerance",
  "humor",
  "proactive_frequency",
  "interests",
  "privacy",
];

const ENUM_OPTIONS: Partial<Record<VirtualHumanCompanionPreferenceKind, string[]>> = {
  response_length: ["brief", "compact", "balanced", "detailed"],
  question_tolerance: ["low", "normal", "high"],
  humor: ["off", "light", "natural"],
  proactive_frequency: ["low", "normal", "high"],
  privacy: ["never_mention_memory", "relevant_only"],
};

function preferenceLabel(kind: VirtualHumanCompanionPreferenceKind, lang: "zh" | "en"): string {
  const labels: Record<VirtualHumanCompanionPreferenceKind, [string, string]> = {
    address: ["怎么称呼你", "How to address you"],
    response_length: ["回答长度", "Reply length"],
    question_tolerance: ["追问频率", "Follow-up questions"],
    humor: ["幽默程度", "Humor"],
    proactive_frequency: ["主动联系", "Proactive contact"],
    interests: ["你的兴趣", "Your interests"],
    privacy: ["记忆提及", "Memory mentions"],
  };
  return labels[kind][lang === "zh" ? 0 : 1];
}

function optionLabel(kind: VirtualHumanCompanionPreferenceKind, value: string, lang: "zh" | "en"): string {
  const zh: Record<string, string> = {
    brief: "很短",
    compact: "简洁",
    balanced: "自然",
    detailed: "详细",
    low: "少一些",
    normal: "自然",
    high: "多一些",
    off: "不开玩笑",
    light: "偶尔轻松",
    natural: "自然幽默",
    never_mention_memory: "不要主动提起记忆",
    relevant_only: "只在相关时提起",
  };
  if (lang === "zh") return zh[value] || value;
  return value.replaceAll("_", " ");
}

function displayValue(card: PreferenceCard, lang: "zh" | "en"): string {
  if (Array.isArray(card.value)) return card.value.join(" · ");
  return optionLabel(card.preferenceKind, card.value, lang);
}

function draftValue(card: PreferenceCard | undefined): string {
  if (!card) return "";
  return Array.isArray(card.value) ? card.value.join("，") : card.value;
}

function preferenceIdempotencyKey(
  agentId: string,
  kind: VirtualHumanCompanionPreferenceKind,
  value: string,
  episodeId: string,
  operation: "upsert" | "delete",
): string {
  const material = `${agentId}:${kind}:${value}:${episodeId}:${operation}`;
  let hash = 2166136261;
  for (let index = 0; index < material.length; index += 1) {
    hash ^= material.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `companion-preference:${operation}:${(hash >>> 0).toString(16)}`;
}

export function CompanionPreferenceCard({
  agentId,
  stateVersion,
  projection,
  lang,
}: {
  agentId: string;
  stateVersion: number;
  projection: VirtualHumanCompanionPreferenceProjection | null | undefined;
  lang: "zh" | "en";
}) {
  const queryClient = useQueryClient();
  const cards = projection?.cards ?? [];
  const byKind = useMemo(
    () => new Map(cards.map((card) => [card.preferenceKind, card])),
    [cards],
  );
  const [selectedKind, setSelectedKind] = useState<VirtualHumanCompanionPreferenceKind>("address");
  const selectedCard = byKind.get(selectedKind);
  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState("");

  useEffect(() => {
    setValue(draftValue(selectedCard));
    setFeedback("");
  }, [agentId, selectedKind, selectedCard?.episodeId]);

  const mutation = useMutation({
    mutationFn: ({ operation }: { operation: "upsert" | "delete" }) => {
      const normalizedValue = selectedKind === "interests"
        ? value.split(/[，,]/).map((item) => item.trim()).filter(Boolean)
        : value.trim();
      return executeVirtualHumanCommand(agentId, {
        agentId,
        command: operation === "upsert" ? "upsertCompanionPreference" : "deleteCompanionPreference",
        expectedVersion: stateVersion,
        idempotencyKey: preferenceIdempotencyKey(
          agentId,
          selectedKind,
          value,
          selectedCard?.episodeId || "new",
          operation,
        ),
        arguments: operation === "upsert"
          ? { preferenceKind: selectedKind, value: normalizedValue }
          : { preferenceKind: selectedKind },
      });
    },
    onMutate: () => setFeedback(""),
    onSuccess: async (_result, request) => {
      setFeedback(
        request.operation === "delete"
          ? (lang === "zh" ? "这项偏好已删除，旧版本仍保留在原生记忆历史中。" : "Preference removed; its prior version remains in native memory history.")
          : (lang === "zh" ? "偏好已更新，之后的表达会从下一轮开始采用。" : "Preference updated and will apply from the next turn."),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanCompanions() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanSnapshot(agentId) }),
      ]);
    },
    onError: async (error) => {
      setFeedback(error instanceof Error ? error.message : (lang === "zh" ? "偏好没有保存成功。" : "Preference was not saved."));
      await queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanSnapshot(agentId) });
    },
  });

  const enumValues = ENUM_OPTIONS[selectedKind];
  const hasValue = selectedKind === "interests"
    ? value.split(/[，,]/).some((item) => item.trim())
    : Boolean(value.trim());
  const disabled = mutation.isPending || !stateVersion;

  return (
    <section className={styles.lifeCard} data-companion-preferences="true">
      <p className={styles.cardLabel}><MessageCircleHeart size={13} aria-hidden="true" /> {lang === "zh" ? "陪伴偏好" : "Companion preferences"}</p>
      <p className={styles.cardCopy}>
        {lang === "zh" ? "只使用你确认过的偏好；可以随时改正或删除。" : "Only preferences you confirmed are used. Correct or remove them at any time."}
      </p>
      {cards.length ? (
        <div className={styles.preferenceGrid} aria-label={lang === "zh" ? "已确认的陪伴偏好" : "Confirmed companion preferences"}>
          {cards.map((card) => (
            <VButton
              key={card.episodeId}
              variant="ghost"
              contentLayout="plain"
              className={styles.preferenceItem}
              data-active={selectedKind === card.preferenceKind}
              onPress={() => setSelectedKind(card.preferenceKind)}
            >
              <span>{preferenceLabel(card.preferenceKind, lang)}</span>
              <strong>{displayValue(card, lang)}</strong>
            </VButton>
          ))}
        </div>
      ) : <p className={styles.preferenceEmpty}>{lang === "zh" ? "还没有已确认的陪伴偏好。" : "No confirmed companion preferences yet."}</p>}
      <details className={styles.detailDisclosure}>
        <summary className={styles.detailSummary}>{lang === "zh" ? "编辑偏好" : "Edit preferences"}</summary>
        <div className={styles.preferenceForm}>
          <label className={styles.preferenceField}>
            <span>{lang === "zh" ? "偏好类型" : "Preference"}</span>
            <VSelect
              aria-label={lang === "zh" ? "偏好类型" : "Preference kind"}
              selectedKey={selectedKind}
              onSelectionChange={(key) => key && setSelectedKind(String(key) as VirtualHumanCompanionPreferenceKind)}
              options={PREFERENCE_KINDS.map((kind) => ({ id: kind, label: preferenceLabel(kind, lang) }))}
              isDisabled={disabled}
            />
          </label>
          <label className={styles.preferenceField}>
            <span>{preferenceLabel(selectedKind, lang)}</span>
            {enumValues ? (
              <VSelect
                aria-label={preferenceLabel(selectedKind, lang)}
                selectedKey={value || null}
                onSelectionChange={(key) => setValue(String(key || ""))}
                placeholder={lang === "zh" ? "请选择" : "Select"}
                options={enumValues.map((item) => ({ id: item, label: optionLabel(selectedKind, item, lang) }))}
                isDisabled={disabled}
              />
            ) : (
              <VInput
                value={value}
                maxLength={selectedKind === "address" ? 40 : 400}
                placeholder={selectedKind === "interests" ? (lang === "zh" ? "用逗号分隔，例如：音乐，散步" : "Comma separated, e.g. music, walks") : (lang === "zh" ? "输入希望使用的称呼" : "Enter the preferred address")}
                disabled={disabled}
                onChange={(event) => setValue(event.target.value)}
              />
            )}
          </label>
          <div className={styles.preferenceActions}>
            {selectedCard ? (
              <VButton
                variant="ghost"
                isDisabled={disabled}
                onPress={() => mutation.mutate({ operation: "delete" })}
              >
                <Trash2 size={13} aria-hidden="true" /> {lang === "zh" ? "删除" : "Delete"}
              </VButton>
            ) : null}
            <VButton
              variant="primary"
              isDisabled={disabled || !hasValue}
              onPress={() => mutation.mutate({ operation: "upsert" })}
            >
              {mutation.isPending ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "保存偏好" : "Save preference")}
            </VButton>
          </div>
          {feedback ? <p className={styles.preferenceNotice} role={mutation.isError ? "alert" : "status"}>{feedback}</p> : null}
        </div>
      </details>
    </section>
  );
}
