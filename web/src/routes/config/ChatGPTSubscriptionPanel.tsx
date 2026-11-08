import { useId, useState } from "react";
import { ArrowUpRight, ExternalLink, Globe2, LogOut, RefreshCw, ShieldCheck, Sparkles, X } from "lucide-react";

import { CHATGPT_SUBSCRIPTION_USAGE_URL, ChatGPTSubscriptionApiError } from "../../api/chatgptSubscription";
import { openExternalUrl } from "../../api/desktopPlatform";
import type { SubscriptionModel } from "../../api/types/chatgptSubscription";
import { VButton, VConfirmDialog, VRouteLinkButton, VSettingsGroupCard, VSettingsRow, VStateSurface, VStatusChip, VSwitch } from "../../components/vui";
import { CHATGPT_SUBSCRIPTION_COPY, subscriptionErrorContent } from "./chatgptSubscriptionCopy";
import { useChatGPTSubscription } from "./useChatGPTSubscription";
import styles from "./ChatGPTSubscriptionPanel.styles";

export type AddSubscriptionModels = (models: SubscriptionModel[], provider: Record<string, unknown>) => Promise<void>;

export type ChatGPTSubscriptionPanelProps = {
  language?: "zh" | "en";
  disabled?: boolean;
  setupBlockedReason?: string;
  onAddModels: AddSubscriptionModels;
};

export function ChatGPTSubscriptionPanel({ language = "zh", disabled = false, setupBlockedReason, onAddModels }: ChatGPTSubscriptionPanelProps) {
  const copy = CHATGPT_SUBSCRIPTION_COPY[language];
  const headingId = useId();
  const subscription = useChatGPTSubscription();
  const { statusQuery, modelsQuery, pending, commandPending } = subscription;
  const status = statusQuery.data;
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [adding, setAdding] = useState(false);
  const [addResult, setAddResult] = useState<"success" | "error" | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [manualUsage, setManualUsage] = useState(false);
  const error = subscription.actionError ?? statusQuery.error ?? modelsQuery.error;
  const errorCode = error instanceof ChatGPTSubscriptionApiError ? error.code
    : error ? "network" : status?.lastError?.code ?? (status?.state === "reauth_required" ? "reauth_required" : status?.state === "unavailable" ? "unavailable" : "");
  const issue = errorCode && errorCode !== "login_cancelled" ? subscriptionErrorContent(errorCode, copy) : null;
  const models = modelsQuery.data?.models.filter((model) => model.visibility === "list" && model.supported_in_api) ?? [];
  const chosen = models.filter((model) => selected.has(model.slug));
  const setupBlocked = Boolean(setupBlockedReason?.trim());
  const canChoose = status?.connected === true && !pending && !disabled && !commandPending && !adding;
  const blocked = disabled || commandPending || adding;
  const statusLabel = pending ? copy.pending : errorCode === "rate_limited" ? copy.quota
    : status?.state === "reauth_required" ? copy.reauth : status?.connected ? copy.connected
      : status?.state === "unavailable" || statusQuery.isError ? copy.unavailable : copy.signedOut;

  const openUsage = async () => setManualUsage(!(await openExternalUrl(CHATGPT_SUBSCRIPTION_USAGE_URL)));
  const addModels = async () => {
    if (!canChoose || setupBlocked || !chosen.length || !modelsQuery.data) return;
    setAdding(true);
    setAddResult(null);
    try {
      await onAddModels(chosen, modelsQuery.data.provider);
      setAddResult("success");
    } catch {
      setAddResult("error");
    } finally {
      setAdding(false);
    }
  };

  return (
    <section className={styles.section} aria-labelledby={headingId} data-vui-region="chatgpt-subscription">
      <div className={styles.heading}><h2 id={headingId}>{copy.heading}</h2><span>{copy.existingPlan}</span></div>
      <VSettingsGroupCard>
        <div className={styles.cardHeader}>
          <div className={styles.identity}>
            <span className={styles.mark} aria-hidden="true"><Sparkles size={23} strokeWidth={1.7} /></span>
            <div className={styles.title}><h3>{copy.title}</h3><p>{copy.subtitle}</p></div>
          </div>
          <VStatusChip tone={pending ? "neutral" : issue ? "warning" : status?.connected ? "success" : "neutral"}>{statusLabel}</VStatusChip>
        </div>
        {statusQuery.isPending ? <div className={styles.state}><VStateSurface tone="loading" density="compact" title={copy.checking} /></div> : null}
        {status?.account ? (
          <>
            <div className={styles.account}>
              <div className={styles.accountIdentity}><strong>{status.account.email || copy.title}</strong><span>{copy.browserAuth}</span></div>
              {status.connected || status.state === "reauth_required" ? <VButton variant="ghost" icon={<LogOut size={14} />} isDisabled={blocked || pending} onPress={() => setConfirmDisconnect(true)}>{copy.disconnect}</VButton> : null}
            </div>
            <div className={styles.usage}>
              <span className={styles.hint}><ShieldCheck size={14} />{copy.plan}</span>
              <VButton variant="ghost" trailingIcon={<ArrowUpRight size={13} />} onPress={() => void openUsage()}>{copy.usage}</VButton>
            </div>
            {status.connected ? <p className={`${styles.note} ${styles.state}`}>{copy.authorizationNote}</p> : null}
          </>
        ) : null}
        {!statusQuery.isPending && !status?.connected && !pending && issue?.recovery !== "login" ? (
          <div className={styles.body}>
            <p className={styles.note}>{copy.connectDescription}</p>
            <div className={styles.actions}>
              <VButton variant="primary" icon={<Sparkles size={15} />} isPending={subscription.starting} isDisabled={blocked} onPress={() => void subscription.startLogin()}>{status?.state === "reauth_required" ? copy.relogin : copy.connect}</VButton>
              <span className={styles.hint}><Globe2 size={13} />{copy.browser}</span>
            </div>
          </div>
        ) : null}
        {pending ? (
          <div className={styles.state}>
            <VStateSurface tone="loading" skeletonLines={false} title={status?.login?.state === "exchanging" ? copy.exchangingTitle : copy.waitingTitle} actions={<>
              {subscription.authorization ? <VButton trailingIcon={<ExternalLink size={13} />} isDisabled={blocked} onPress={() => void subscription.reopenAuthorization()}>{copy.reopen}</VButton> : null}
              <VButton variant="ghost" icon={<X size={14} />} isPending={subscription.cancelling} isDisabled={blocked} onPress={() => void subscription.cancelLogin()}>{copy.cancelLogin}</VButton>
            </>}>{copy.waitingBody}</VStateSurface>
          </div>
        ) : null}
        {subscription.manualAuthorization && subscription.authorization && pending ? (
          <div className={styles.body}>
            <p className={styles.note}>{copy.manualBrowser}</p>
            <VRouteLinkButton to={subscription.authorization.authorizationUrl} target="_blank" rel="noopener noreferrer" reloadDocument trailingIcon={<ExternalLink size={13} />}>{copy.openAuthorization}</VRouteLinkButton>
          </div>
        ) : null}
        {issue ? (
          <div className={styles.state}>
            <VStateSurface tone={issue.recovery === "retry" ? "error" : "unavailable"} density="compact" role="alert" title={issue.title} actions={issue.recovery === "login"
              ? <VButton variant="primary" isDisabled={blocked || pending} onPress={() => void subscription.startLogin()}>{copy.relogin}</VButton>
              : issue.recovery === "usage"
                ? <VButton trailingIcon={<ArrowUpRight size={13} />} onPress={() => void openUsage()}>{copy.usage}</VButton>
                : <VButton icon={<RefreshCw size={14} />} isDisabled={blocked} onPress={() => void subscription.refresh()}>{copy.retry}</VButton>}>{issue.body}</VStateSurface>
          </div>
        ) : null}
        {manualUsage ? <div className={styles.state}><VRouteLinkButton to={CHATGPT_SUBSCRIPTION_USAGE_URL} target="_blank" rel="noopener noreferrer" reloadDocument trailingIcon={<ExternalLink size={13} />}>{copy.usageFallback}</VRouteLinkButton></div> : null}
        <p className={styles.footnote}><ShieldCheck size={14} /><span>{copy.securityNote}</span></p>
      </VSettingsGroupCard>
      {subscription.disconnectNotice ? <VStateSurface tone="info" density="compact" role="status" title={subscription.disconnectNotice === "local_only" ? copy.localDisconnected : copy.disconnected} /> : null}
      {setupBlocked ? <VStateSurface tone="info" density="compact" role="status" title={setupBlockedReason} /> : null}
      {status?.account || modelsQuery.data ? (
        <div className={styles.modelSection}>
          <div className={styles.heading}><h2>{copy.modelsTitle}{modelsQuery.data ? ` (${models.length})` : ""}</h2><VButton variant="ghost" icon={<RefreshCw size={13} />} isPending={modelsQuery.isFetching} isDisabled={blocked || pending || !status?.connected} onPress={() => void subscription.refresh()}>{copy.refresh}</VButton></div>
          {modelsQuery.isPending && modelsQuery.isFetching ? <VStateSurface tone="loading" density="compact" title={copy.modelsLoading} /> : null}
          {models.length ? <VSettingsGroupCard>{models.map((model) => (
            <VSettingsRow key={model.slug} label={<span className={styles.modelIdentity}>{model.display_name || model.slug}{model.display_name && model.display_name !== model.slug ? <small>{model.slug}</small> : null}</span>}
              description={[
                model.context_window ? `${copy.context} ${model.context_window.toLocaleString(language === "zh" ? "zh-CN" : "en-US")} ${copy.tokens}` : "",
                model.supported_reasoning_levels.length ? `${copy.reasoning}: ${model.supported_reasoning_levels.map((level) => level.effort).join(" / ")}` : "",
              ].filter(Boolean).join(" · ")}
              control={<span className={styles.modelToggle}><span>{selected.has(model.slug) ? copy.selected : copy.notSelected}</span><VSwitch aria-label={`${copy.selectModel} ${model.display_name || model.slug}`} isSelected={selected.has(model.slug)} isDisabled={!canChoose} onChange={(value) => {
                setSelected((current) => { const next = new Set(current); if (value) next.add(model.slug); else next.delete(model.slug); return next; });
                setAddResult(null);
              }} /></span>} />
          ))}</VSettingsGroupCard> : modelsQuery.isSuccess ? <VStateSurface tone="empty" density="compact" title={copy.modelsEmpty}>{copy.modelsEmptyBody}</VStateSurface> : null}
          <p className={styles.note}>{copy.modelsNote}</p>
          <VButton variant="primary" isPending={adding} isDisabled={!canChoose || setupBlocked || !chosen.length || modelsQuery.isError} onPress={() => void addModels()}>{copy.addModels}{chosen.length ? ` (${chosen.length})` : ""}</VButton>
          {addResult ? <VStateSurface tone={addResult === "success" ? "info" : "error"} density="compact" role={addResult === "error" ? "alert" : "status"} title={addResult === "success" ? copy.added : copy.addFailed}>{addResult === "error" ? copy.addFailedBody : null}</VStateSurface> : null}
        </div>
      ) : null}
      <VConfirmDialog open={confirmDisconnect} onOpenChange={(open) => { if (!subscription.disconnecting) setConfirmDisconnect(open); }} title={copy.disconnectTitle} description={copy.disconnectBody} confirmLabel={copy.disconnect} cancelLabel={copy.cancel} tone="danger" confirmPending={subscription.disconnecting} onConfirm={() => {
        void subscription.disconnect().then((done) => { if (done) setConfirmDisconnect(false); });
      }} />
    </section>
  );
}
