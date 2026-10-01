/**
 * Team create dialog: template picker → team name → created outcome
 * (plus the discard-confirm guard). VUI-only surface; mutations and cache
 * invalidation live in useTeamCreateActions (injected via props), copy is an
 * inline zh/en table. Mirrors AgentCreateWizardDialog's three-state structure.
 */
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, RefreshCw, SquarePlus, Users } from "lucide-react";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { listTeamTemplates } from "../../api/teams";
import type { TeamTemplateSummary } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { VButton, VDialog, VNativeInput } from "../../components/vui";
import {
  TEAM_NAME_MAX_LENGTH,
  createTeamCreateDraft,
  resolveTemplateOptions,
  teamCreateReady,
  type TeamCreateDraft,
} from "./teamCreateLogic";
import type { TeamCreateOutcome } from "./useTeamCreateActions";
import styles from "./TeamCreateDialog.styles";

export type TeamCreateDialogCopy = {
  title: string;
  description: string;
  successTitle: string;
  successDescription: string;
  selectHeading: string;
  blankTeamName: string;
  blankTeamDescription: string;
  rolesLabel: (count: number) => string;
  chatRoomIncluded: string;
  nameHeading: string;
  namePlaceholder: string;
  backToTemplates: string;
  create: string;
  creating: string;
  templatesLoading: string;
  templatesError: string;
  retry: string;
  createdAgentsLabel: (count: number) => string;
  chatRoomReady: string;
  blankSuccessDetail: string;
  goToTeam: string;
  done: string;
  discardTitle: string;
  discardBody: string;
  keepEditing: string;
  discard: string;
};

export function teamCreateCopy(lang: "zh" | "en"): TeamCreateDialogCopy {
  if (lang === "en") {
    return {
      title: "New team",
      description: "Create a team from a template in one step, or start from a blank team.",
      successTitle: "Team created",
      successDescription: "The new team is ready in the workspace.",
      selectHeading: "Choose how to create the team",
      blankTeamName: "Blank team",
      blankTeamDescription: "No preset roles; add members yourself later.",
      rolesLabel: (count) => `${count} role${count === 1 ? "" : "s"}`,
      chatRoomIncluded: "Includes team chat room",
      nameHeading: "Team name",
      namePlaceholder: "e.g. Development team",
      backToTemplates: "Back to templates",
      create: "Create team",
      creating: "Creating…",
      templatesLoading: "Loading templates…",
      templatesError: "Failed to load templates. You can retry.",
      retry: "Retry",
      createdAgentsLabel: (count) => `Created ${count} agent${count === 1 ? "" : "s"}`,
      chatRoomReady: "Chat room is ready",
      blankSuccessDetail: "The blank team was created. You can add members next.",
      goToTeam: "Go to team",
      done: "Done",
      discardTitle: "Discard this draft?",
      discardBody: "No team has been created. Closing discards this draft.",
      keepEditing: "Keep editing",
      discard: "Discard",
    };
  }
  return {
    title: "新建团队",
    description: "从模板一键创建团队，或先建一个空白团队。",
    successTitle: "团队已创建",
    successDescription: "新团队已进入工作台。",
    selectHeading: "选择创建方式",
    blankTeamName: "空白团队",
    blankTeamDescription: "不预置角色，稍后自行添加成员。",
    rolesLabel: (count) => `${count} 个角色`,
    chatRoomIncluded: "含团队群聊",
    nameHeading: "团队名称",
    namePlaceholder: "例如：开发团队",
    backToTemplates: "返回选择",
    create: "创建团队",
    creating: "正在创建…",
    templatesLoading: "正在加载模板…",
    templatesError: "模板加载失败，可以重试。",
    retry: "重试",
    createdAgentsLabel: (count) => `已创建 ${count} 个 Agent`,
    chatRoomReady: "群聊已就绪",
    blankSuccessDetail: "空白团队已创建，可以继续添加成员。",
    goToTeam: "前往团队",
    done: "完成",
    discardTitle: "放弃本次创建？",
    discardBody: "尚未创建团队，关闭后本次选择不会保留。",
    keepEditing: "继续填写",
    discard: "放弃并关闭",
  };
}

export type TeamCreateDialogProps = {
  open: boolean;
  lang: "zh" | "en";
  /** The invoking control receives focus again when this modal closes. */
  triggerRef?: RefObject<HTMLButtonElement | null>;
  triggerId?: string;
  pending: boolean;
  errorMessage: string;
  outcome: TeamCreateOutcome | null;
  /** templateId "" = blank team. */
  onSubmit: (input: { templateId: string; name: string }) => void;
  /** Success-page primary action ("前往团队"); parent closes the dialog. */
  onGoToTeam: () => void;
  onClose: () => void;
};

export function TeamCreateDialog({
  open,
  lang,
  triggerRef,
  triggerId,
  pending,
  errorMessage,
  outcome,
  onSubmit,
  onGoToTeam,
  onClose,
}: TeamCreateDialogProps) {
  const copy = useMemo(() => teamCreateCopy(lang), [lang]);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const [draft, setDraft] = useState<TeamCreateDraft>(createTeamCreateDraft);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);

  const templatesQuery = useQuery({
    queryKey: queryKeys.teamTemplates(),
    queryFn: ({ signal }) => listTeamTemplates({ signal }),
    enabled: open,
    staleTime: 10_000,
  });
  const templates: TeamTemplateSummary[] = useMemo(
    () => templatesQuery.data?.templates ?? [],
    [templatesQuery.data],
  );
  const templateOptions = useMemo(() => resolveTemplateOptions(templates), [templates]);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = triggerRef?.current
      ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    setDraft(createTeamCreateDraft());
    setDiscardConfirmOpen(false);
    return () => {
      const fallbackFocusTarget = returnFocusRef.current;
      // Radix unmounts the portal in the same commit; defer so focus is not
      // stolen by body after the dialog close control is removed.
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const focusTarget = triggerId ? document.getElementById(triggerId) : fallbackFocusTarget;
          if (focusTarget instanceof HTMLElement && focusTarget.isConnected) {
            focusTarget.focus();
          }
        });
      });
    };
  }, [open, triggerId, triggerRef]);

  const closeNow = () => {
    setDiscardConfirmOpen(false);
    onClose();
  };
  const draftTouched = draft.step === "name" || draft.name.trim() !== "";
  const requestClose = () => {
    if (pending) return;
    if (outcome || !draftTouched) {
      closeNow();
      return;
    }
    setDiscardConfirmOpen(true);
  };
  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen) return;
    requestClose();
  };

  const selectTemplate = (templateId: string, defaultTeamName: string) => {
    setDraft({ step: "name", templateId, name: defaultTeamName });
  };
  const ready = teamCreateReady(draft, templates);
  const canSubmit = ready && !pending;

  const title = outcome ? copy.successTitle : copy.title;
  const description = outcome ? copy.successDescription : copy.description;

  return (
    <VDialog
      open={open}
      onOpenChange={handleOpenChange}
      title={title}
      description={description}
      size="xl"
      contentClassName={styles.content}
      aria-label={title}
      hideClose={pending}
    >
      {discardConfirmOpen ? (
        <section className={styles.confirmation} aria-live="polite">
          <strong>{copy.discardTitle}</strong>
          <p>{copy.discardBody}</p>
          <div className={styles.confirmationActions}>
            <VButton type="button" variant="secondary" onPress={() => setDiscardConfirmOpen(false)}>
              {copy.keepEditing}
            </VButton>
            <VButton type="button" variant="danger" onPress={closeNow}>
              {copy.discard}
            </VButton>
          </div>
        </section>
      ) : outcome ? (
        <section className={styles.success} aria-live="polite">
          <CheckCircle2 size={28} aria-hidden="true" />
          <div className={styles.successCopy}>
            <strong>{outcome.team.name}</strong>
            {outcome.templateName ? (
              <p>
                {copy.createdAgentsLabel(outcome.createdAgentCount)}
                {outcome.chatRoomReady ? ` · ${copy.chatRoomReady}` : ""}
              </p>
            ) : (
              <p>{copy.blankSuccessDetail}</p>
            )}
          </div>
          <div className={styles.successActions}>
            <VButton
              type="button"
              variant="primary"
              icon={<Users size={15} aria-hidden="true" />}
              onPress={onGoToTeam}
            >
              {copy.goToTeam}
            </VButton>
            <VButton type="button" variant="secondary" onPress={closeNow}>
              {copy.done}
            </VButton>
          </div>
        </section>
      ) : draft.step === "name" ? (
        <div className={styles.content}>
          <label className={styles.nameField}>
            <span className={styles.nameLabel}>{copy.nameHeading}</span>
            <VNativeInput
              value={draft.name}
              maxLength={TEAM_NAME_MAX_LENGTH}
              disabled={pending}
              placeholder={copy.namePlaceholder}
              onChange={(event) => {
                const name = event.target.value;
                setDraft((current) => ({ ...current, name }));
              }}
            />
          </label>
          {errorMessage ? <p className={styles.error}>{errorMessage}</p> : null}
          <div className={styles.actions}>
            <VButton
              type="button"
              variant="secondary"
              className={styles.backAction}
              isDisabled={pending}
              onPress={() => setDraft((current) => ({ ...current, step: "select" }))}
            >
              {copy.backToTemplates}
            </VButton>
            <VButton
              type="button"
              variant="primary"
              icon={<CheckCircle2 size={15} aria-hidden="true" />}
              isDisabled={!canSubmit}
              isPending={pending}
              onPress={() => onSubmit({ templateId: draft.templateId, name: draft.name.trim() })}
            >
              {pending ? copy.creating : copy.create}
            </VButton>
          </div>
        </div>
      ) : (
        <div className={styles.content}>
          <div className={styles.templateList} role="listbox" aria-label={copy.selectHeading}>
            {templateOptions.map((option) => (
              <div
                key={option.blank ? "blank" : option.templateId}
                role="option"
                aria-selected={draft.templateId === option.templateId}
                tabIndex={0}
                className={`${styles.templateCard} ${draft.templateId === option.templateId ? styles.templateCardSelected : ""}`}
                onClick={() => selectTemplate(option.templateId, option.defaultTeamName)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectTemplate(option.templateId, option.defaultTeamName);
                  }
                }}
              >
                <span className={styles.templateIcon} aria-hidden="true">
                  {option.blank ? <SquarePlus size={18} /> : <Users size={18} />}
                </span>
                <span className={styles.templateCopy}>
                  <strong className={styles.templateName}>
                    {option.blank ? copy.blankTeamName : option.name}
                  </strong>
                  <small className={styles.templateMeta}>
                    {option.blank
                      ? copy.blankTeamDescription
                      : [option.description, copy.rolesLabel(option.roleCount), option.roleCount > 0 ? copy.chatRoomIncluded : ""]
                        .filter(Boolean)
                        .join(" · ")}
                  </small>
                </span>
              </div>
            ))}
          </div>
          {templatesQuery.isPending ? (
            <p className={styles.templateMeta}>{copy.templatesLoading}</p>
          ) : null}
          {templatesQuery.isError ? (
            <p className={styles.error}>
              {copy.templatesError}
              <VButton
                type="button"
                variant="ghost"
                density="compact"
                icon={<RefreshCw size={13} aria-hidden="true" />}
                onPress={() => void templatesQuery.refetch()}
              >
                {copy.retry}
              </VButton>
            </p>
          ) : null}
          {errorMessage ? <p className={styles.error}>{errorMessage}</p> : null}
        </div>
      )}
    </VDialog>
  );
}
