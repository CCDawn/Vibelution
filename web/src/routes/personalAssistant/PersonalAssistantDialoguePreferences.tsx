import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { CheckCircle2, HeartHandshake } from "lucide-react";
import {
  acceptVirtualHumanPreferenceProposal,
  fetchVirtualHumanDialogueSettings,
  fetchVirtualHumanPreferenceProposals,
  rejectVirtualHumanPreferenceProposal,
  updateVirtualHumanDialogueSettings,
} from "../../api/virtualHumanLife";
import type {
  VirtualHumanDialogueSettings,
  VirtualHumanDialogueSettingsField,
  VirtualHumanDialogueSettingsUpdate,
  VirtualHumanPreferenceProposal,
  VirtualHumanPreferenceProposalType,
} from "../../api/types/virtualHumanLife";
import { queryKeys } from "../../api/queryKeys";
import { VButton, VStateSurface, VStringSelect } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import styles from "./PersonalAssistantDialoguePreferences.styles";

/** Interface copy only; preference values arrive from the backend closed enums. */
const COPY = {
  zh: {
    title: "对话偏好",
    subtitle: "调整助理的说话方式，并确认它在对话中学到的偏好。",
    speaking: "说话主动性",
    question: "提问主动性",
    proposalMode: "偏好建议",
    speakingHint: "克制时点到为止，健谈时会多补充想法。",
    questionHint: "少问时尽量自己判断，主动时会先向你确认。",
    proposalModeHint: "“先问我”允许助理在对话中提出偏好建议；“仅手动”只在本面板调整。",
    settingsOptions: {
      speakingInitiative: { restrained: "克制", natural: "自然", talkative: "健谈" },
      questionInitiative: { few: "少问", natural: "自然", proactive: "主动" },
      preferenceProposalMode: { ask_first: "先问我", manual_only: "仅手动" },
    },
    pendingTitle: "待确认的偏好建议",
    decidedTitle: "最近已处理",
    emptyPending: "没有待确认的偏好建议",
    accept: "采纳",
    reject: "保留原样",
    candidate: (value: string) => `建议：${value}`,
    typeLabels: {
      verbosity: "表达详略",
      question_initiative: "提问主动性",
      address: "称呼",
      humor: "幽默感",
      proactive_contact: "主动联系",
    } as Record<VirtualHumanPreferenceProposalType, string>,
    proposalValueLabels: {
      response_length: { brief: "尽量简短", compact: "偏简短", balanced: "适中", detailed: "详细展开" },
      question_tolerance: { low: "少问", normal: "适中", high: "多问确认" },
      humor: { off: "不幽默", light: "偶尔轻松", natural: "自然幽默" },
      proactive_frequency: { low: "少主动", normal: "适中", high: "更主动" },
    } as Record<string, Record<string, string>>,
    statusLabels: { pending: "待确认", accepted: "已采纳", rejected: "已保留原样", expired: "已过期" } as Record<string, string>,
    saveFailed: "保存失败，请稍后重试。",
    loadFailed: "偏好读取失败",
    retry: "重试",
    loading: "正在读取偏好…",
  },
  en: {
    title: "Dialogue preferences",
    subtitle: "Tune how the assistant speaks and confirm what it learns from chats.",
    speaking: "Speaking initiative",
    question: "Question initiative",
    proposalMode: "Preference proposals",
    speakingHint: "Restrained stays brief; talkative adds more thoughts.",
    questionHint: "Few decides on its own; proactive checks with you first.",
    proposalModeHint: "\"Ask first\" lets the assistant propose preferences in chat; \"Manual only\" limits changes to this panel.",
    settingsOptions: {
      speakingInitiative: { restrained: "Restrained", natural: "Natural", talkative: "Talkative" },
      questionInitiative: { few: "Few", natural: "Natural", proactive: "Proactive" },
      preferenceProposalMode: { ask_first: "Ask first", manual_only: "Manual only" },
    },
    pendingTitle: "Pending preference proposals",
    decidedTitle: "Recently handled",
    emptyPending: "No pending preference proposals",
    accept: "Accept",
    reject: "Keep as is",
    candidate: (value: string) => `Proposes: ${value}`,
    typeLabels: {
      verbosity: "Detail level",
      question_initiative: "Question initiative",
      address: "Address",
      humor: "Humor",
      proactive_contact: "Proactive contact",
    } as Record<VirtualHumanPreferenceProposalType, string>,
    proposalValueLabels: {
      response_length: { brief: "Brief", compact: "Compact", balanced: "Balanced", detailed: "Detailed" },
      question_tolerance: { low: "Few questions", normal: "Normal", high: "More checks" },
      humor: { off: "Off", light: "Light", natural: "Natural" },
      proactive_frequency: { low: "Rare", normal: "Normal", high: "Often" },
    } as Record<string, Record<string, string>>,
    statusLabels: { pending: "Pending", accepted: "Accepted", rejected: "Kept as is", expired: "Expired" } as Record<string, string>,
    saveFailed: "Failed to save; please retry later.",
    loadFailed: "Failed to load preferences",
    retry: "Retry",
    loading: "Loading preferences…",
  },
} as const;

const FIELD_KINDS: Record<VirtualHumanPreferenceProposalType, string> = {
  verbosity: "response_length",
  question_initiative: "question_tolerance",
  address: "address",
  humor: "humor",
  proactive_contact: "proactive_frequency",
};

const SPEAKING_OPTIONS = ["restrained", "natural", "talkative"] as const;
const QUESTION_OPTIONS = ["few", "natural", "proactive"] as const;
const PROPOSAL_MODE_OPTIONS = ["ask_first", "manual_only"] as const;

function proposalValueText(
  proposal: VirtualHumanPreferenceProposal,
  copy: (typeof COPY)["zh" | "en"],
): string {
  const raw = proposal.candidateValue;
  const text = typeof raw === "string" ? raw : String(raw ?? "");
  const kind = FIELD_KINDS[proposal.preferenceType];
  const mapped = copy.proposalValueLabels[kind]?.[text];
  return mapped || text;
}

export function PersonalAssistantDialoguePreferences({ agentId, headerAction }: {
  agentId: string;
  headerAction?: ReactNode;
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const [savingField, setSavingField] = useState<VirtualHumanDialogueSettingsField | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [decidingKey, setDecidingKey] = useState<string | null>(null);
  const settings = useQuery({
    queryKey: queryKeys.virtualHumanDialogueSettings(agentId),
    queryFn: ({ signal }) => fetchVirtualHumanDialogueSettings(agentId, { signal }),
    enabled: Boolean(agentId),
    retry: 1,
  });
  const proposals = useQuery({
    queryKey: queryKeys.virtualHumanPreferenceProposals(agentId),
    queryFn: ({ signal }) => fetchVirtualHumanPreferenceProposals(agentId, { signal }),
    enabled: Boolean(agentId),
    retry: 1,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  const data = settings.data;

  async function saveField<K extends VirtualHumanDialogueSettingsField>(
    field: K,
    value: VirtualHumanDialogueSettings[K],
  ) {
    if (!data || savingField || value === data[field]) return;
    setSavingField(field);
    setActionError(null);
    try {
      const payload: VirtualHumanDialogueSettingsUpdate = {};
      payload[field] = value;
      await updateVirtualHumanDialogueSettings(agentId, payload);
      await queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanDialogueSettings(agentId) });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveFailed);
    } finally {
      setSavingField(null);
    }
  }

  async function decideProposal(proposalId: string, decision: "accept" | "reject") {
    if (decidingKey) return;
    setDecidingKey(`${proposalId}:${decision}`);
    setActionError(null);
    try {
      if (decision === "accept") {
        await acceptVirtualHumanPreferenceProposal(agentId, proposalId);
      } else {
        await rejectVirtualHumanPreferenceProposal(agentId, proposalId);
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanPreferenceProposals(agentId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanDialogueSettings(agentId) });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : copy.saveFailed);
    } finally {
      setDecidingKey(null);
    }
  }

  const pending = (proposals.data?.proposals ?? []).filter(item => item.status === "pending");
  const decided = (proposals.data?.proposals ?? [])
    .filter(item => item.status !== "pending")
    .slice(-6)
    .reverse();

  return <section className={styles.root} aria-label={copy.title}>
    <div className={styles.pinned}>
      <header className={styles.header}>
        <div>
          <h2>{copy.title}</h2>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <div className={styles.headerActions}>{headerAction}</div>
      </header>
    </div>
    <div className={styles.content}>
      {settings.isError ? <VStateSurface density="compact" tone="error" title={copy.loadFailed}
        actions={<VButton variant="secondary" onClick={() => void settings.refetch()}>{copy.retry}</VButton>}>
        {settings.error instanceof Error ? settings.error.message : ""}
      </VStateSurface> : null}
      {settings.isPending ? <VStateSurface density="compact" tone="loading" busy skeletonLines title={copy.loading} /> : null}
      {actionError ? <p className={styles.error} role="alert">{actionError}</p> : null}
      {data ? <div className={styles.fields}>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>{copy.speaking}</span>
          <VStringSelect ariaLabel={copy.speaking} value={data.speakingInitiative}
            isDisabled={savingField === "speakingInitiative"}
            onValueChange={value => void saveField("speakingInitiative", value as VirtualHumanDialogueSettings["speakingInitiative"])}
            options={SPEAKING_OPTIONS.map(value => ({ value, label: copy.settingsOptions.speakingInitiative[value] }))} />
          <span className={styles.hint}>{copy.speakingHint}</span>
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>{copy.question}</span>
          <VStringSelect ariaLabel={copy.question} value={data.questionInitiative}
            isDisabled={savingField === "questionInitiative"}
            onValueChange={value => void saveField("questionInitiative", value as VirtualHumanDialogueSettings["questionInitiative"])}
            options={QUESTION_OPTIONS.map(value => ({ value, label: copy.settingsOptions.questionInitiative[value] }))} />
          <span className={styles.hint}>{copy.questionHint}</span>
        </label>
        <label className={styles.field}>
          <span className={styles.fieldLabel}>{copy.proposalMode}</span>
          <VStringSelect ariaLabel={copy.proposalMode} value={data.preferenceProposalMode}
            isDisabled={savingField === "preferenceProposalMode"}
            onValueChange={value => void saveField("preferenceProposalMode", value as VirtualHumanDialogueSettings["preferenceProposalMode"])}
            options={PROPOSAL_MODE_OPTIONS.map(value => ({ value, label: copy.settingsOptions.preferenceProposalMode[value] }))} />
          <span className={styles.hint}>{copy.proposalModeHint}</span>
        </label>
      </div> : null}
      {proposals.data ? <>
        <h3 className={styles.sectionTitle}>{copy.pendingTitle}</h3>
        {pending.length ? <ul className={styles.list}>
          {pending.map(proposal => <li key={proposal.proposalId}>
            <div className={styles.proposal}>
              <span className={styles.rowCopy}>
                <strong>{copy.typeLabels[proposal.preferenceType]}</strong>
                <span>{copy.candidate(proposalValueText(proposal, copy))}</span>
              </span>
              <span className={styles.proposalActions}>
                <VButton variant="secondary" isPending={decidingKey === `${proposal.proposalId}:accept`}
                  isDisabled={decidingKey !== null && decidingKey !== `${proposal.proposalId}:accept`}
                  onClick={() => void decideProposal(proposal.proposalId, "accept")}>{copy.accept}</VButton>
                <VButton variant="ghost" isPending={decidingKey === `${proposal.proposalId}:reject`}
                  isDisabled={decidingKey !== null && decidingKey !== `${proposal.proposalId}:reject`}
                  onClick={() => void decideProposal(proposal.proposalId, "reject")}>{copy.reject}</VButton>
              </span>
            </div>
          </li>)}
        </ul> : <div className={styles.empty}><CheckCircle2 size={20} /><strong>{copy.emptyPending}</strong></div>}
        {decided.length ? <>
          <h3 className={styles.sectionTitle}>{copy.decidedTitle}</h3>
          <ul className={styles.list}>
            {decided.map(proposal => <li key={proposal.proposalId}>
              <div className={styles.decidedRow}>
                <HeartHandshake size={13} />
                <span className={styles.rowCopy}>
                  <strong>{copy.typeLabels[proposal.preferenceType]}</strong>
                  <span>{proposalValueText(proposal, copy)}</span>
                </span>
                <span className={styles.decidedBadge}>{copy.statusLabels[proposal.status]}</span>
              </div>
            </li>)}
          </ul>
        </> : null}
      </> : null}
    </div>
  </section>;
}
