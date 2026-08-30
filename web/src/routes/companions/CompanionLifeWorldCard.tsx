import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BriefcaseBusiness, Laptop, MessageCircleMore, Save, Smartphone } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  confirmVirtualHumanLifeWorld,
  updateVirtualHumanLifeDraft,
} from "../../api/virtualHumanLife";
import { queryKeys } from "../../api/queryKeys";
import type {
  VirtualHumanCompanion,
  VirtualHumanLifeDraft,
  VirtualHumanLifeDraftPayload,
  VirtualHumanLifeWorldFacts,
} from "../../api/types";
import { VButton, VInput, VStatusChip } from "../../components/vui";
import styles from "./CompanionLifeWorldCard.styles";

type LifeDraftForm = {
  roleTitle: string;
  stage: string;
  affiliationName: string;
  affiliationDepartment: string;
  affiliationRole: string;
  phoneBrand: string;
  phoneModel: string;
  computerBrand: string;
  computerModel: string;
};

const EMPTY_FORM: LifeDraftForm = {
  roleTitle: "",
  stage: "",
  affiliationName: "",
  affiliationDepartment: "",
  affiliationRole: "",
  phoneBrand: "",
  phoneModel: "",
  computerBrand: "",
  computerModel: "",
};

function itemByCategory(payload: VirtualHumanLifeDraftPayload, category: string) {
  return payload.items.find((item) => item.category === category);
}

function formFromDraft(draft: VirtualHumanLifeDraft | null | undefined): LifeDraftForm {
  const payload = draft?.payload;
  if (!payload) return EMPTY_FORM;
  const affiliation = payload.affiliations[0];
  const phone = itemByCategory(payload, "phone");
  const computer = itemByCategory(payload, "computer");
  return {
    roleTitle: payload.identity.roleTitle || "",
    stage: payload.identity.stage || "",
    affiliationName: affiliation?.name || "",
    affiliationDepartment: affiliation?.department || "",
    affiliationRole: affiliation?.role || "",
    phoneBrand: phone?.brand || "",
    phoneModel: phone?.model || "",
    computerBrand: computer?.brand || "",
    computerModel: computer?.model || "",
  };
}

function actionKey(prefix: string, draftId: string, revision: number): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}:${draftId}:${revision}:${random}`;
}

function identityLabel(kind: string, lang: "zh" | "en"): string {
  const labels: Record<string, [string, string]> = {
    student: ["学生", "Student"],
    employee: ["上班族", "Employee"],
    freelancer: ["自由职业者", "Freelancer"],
    unemployed: ["待业探索期", "Between roles"],
    retired: ["退休生活", "Retired"],
  };
  const pair = labels[kind] ?? [kind || "未设置", kind || "Not set"];
  return lang === "zh" ? pair[0] : pair[1];
}

function formatMoney(amountMinor: number, currency: string, lang: "zh" | "en"): string {
  const divisor = currency === "JPY" ? 1 : 100;
  try {
    return new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en-US", {
      style: "currency",
      currency: currency || "CNY",
      maximumFractionDigits: divisor === 1 ? 0 : 2,
    }).format(amountMinor / divisor);
  } catch {
    return `${currency || ""} ${amountMinor}`.trim();
  }
}

function viewFacts(companion: VirtualHumanCompanion) {
  const world = companion.snapshot.lifeWorld;
  const draftPayload = world?.draft?.payload;
  const facts: VirtualHumanLifeWorldFacts | undefined = world?.facts;
  return {
    world,
    draft: world?.draft ?? null,
    identity: world?.setupState === "ready" ? facts?.identities[0] : draftPayload?.identity,
    affiliation: world?.setupState === "ready" ? facts?.affiliations[0] : draftPayload?.affiliations[0],
    routines: world?.setupState === "ready" ? facts?.routines ?? [] : draftPayload?.routines ?? [],
    items: world?.setupState === "ready" ? facts?.items ?? [] : draftPayload?.items ?? [],
    accounts: world?.setupState === "ready" ? facts?.accounts ?? [] : draftPayload?.accounts ?? [],
    recurringRules: world?.setupState === "ready" ? facts?.recurringRules ?? [] : draftPayload?.recurringRules ?? [],
    location: draftPayload?.homeLocation ?? companion.snapshot.binding?.homeLocation ?? companion.snapshot.environment?.location,
  };
}

export function CompanionLifeWorldCard({
  companion,
  lang,
  onOpenSteward,
}: {
  companion: VirtualHumanCompanion;
  lang: "zh" | "en";
  onOpenSteward: (sessionId: string) => void;
}) {
  const queryClient = useQueryClient();
  const projection = useMemo(() => viewFacts(companion), [companion]);
  const [form, setForm] = useState<LifeDraftForm>(() => formFromDraft(projection.draft));
  const [feedback, setFeedback] = useState("");
  const initialForm = useMemo(() => formFromDraft(projection.draft), [projection.draft]);
  const dirty = JSON.stringify(form) !== JSON.stringify(initialForm);
  const draft = projection.draft;
  const binding = companion.snapshot.binding;
  const steward = binding?.steward;
  const setupReady = projection.world?.setupState === "ready";

  useEffect(() => {
    setForm(initialForm);
    setFeedback("");
  }, [companion.agentId, initialForm]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanCompanions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanSnapshot(companion.agentId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.agentPlugins(companion.agentId) }),
    ]);
  };

  const draftMutation = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error(lang === "zh" ? "生活草案尚未生成。" : "The life draft is not ready.");
      return updateVirtualHumanLifeDraft(companion.agentId, {
        agentId: companion.agentId,
        draftId: draft.draftId,
        expectedRevision: draft.revision,
        idempotencyKey: actionKey("life-draft-save", draft.draftId, draft.revision),
        patch: {
          identity: { roleTitle: form.roleTitle, stage: form.stage },
          affiliations: [{
            name: form.affiliationName,
            department: form.affiliationDepartment,
            role: form.affiliationRole,
          }],
          items: draft.payload.items.map((item) => (
            item.category === "phone"
              ? { brand: form.phoneBrand, model: form.phoneModel }
              : item.category === "computer"
                ? { brand: form.computerBrand, model: form.computerModel }
                : {}
          )),
        },
      });
    },
    onMutate: () => setFeedback(""),
    onSuccess: async () => {
      setFeedback(lang === "zh" ? "草案已保存，可以确认这份生活档案了。" : "Draft saved. This life profile is ready for confirmation.");
      await refresh();
    },
    onError: (error) => setFeedback(error instanceof Error ? error.message : (lang === "zh" ? "草案保存失败。" : "Draft save failed.")),
  });

  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!draft || !binding) throw new Error(lang === "zh" ? "生活草案尚未就绪。" : "The life draft is not ready.");
      return confirmVirtualHumanLifeWorld(companion.agentId, {
        agentId: companion.agentId,
        draftId: draft.draftId,
        expectedDraftRevision: draft.revision,
        expectedBindingVersion: binding.configVersion,
        idempotencyKey: actionKey("life-world-confirm", draft.draftId, draft.revision),
      });
    },
    onMutate: () => setFeedback(""),
    onSuccess: async () => {
      setFeedback(lang === "zh" ? "生活档案已确认，生活管家也已准备好。" : "Life profile confirmed and the life steward is ready.");
      await refresh();
    },
    onError: (error) => setFeedback(error instanceof Error ? error.message : (lang === "zh" ? "生活档案确认失败。" : "Life profile confirmation failed.")),
  });

  if (!projection.world || projection.world.setupState === "missing") {
    return (
      <section className={styles.card} aria-label={lang === "zh" ? "生活档案" : "Life profile"}>
        <div className={styles.header}>
          <div className={styles.title}><span><BriefcaseBusiness size={16} aria-hidden="true" /></span><div><p>Life profile</p><h3>{lang === "zh" ? "等待生活草案" : "Waiting for life draft"}</h3></div></div>
          <VStatusChip tone="warning">{lang === "zh" ? "未建立" : "Not set"}</VStatusChip>
        </div>
        <p className={styles.lead}>{lang === "zh" ? "请先在 Agent 插件设置中选择居住城市和身份。" : "Choose a home city and identity in the Agent plugin settings first."}</p>
      </section>
    );
  }

  return (
    <section className={styles.card} aria-label={lang === "zh" ? `${companion.displayName} 的生活档案` : `${companion.displayName} life profile`}>
      <div className={styles.header}>
        <div className={styles.title}>
          <span><BriefcaseBusiness size={16} aria-hidden="true" /></span>
          <div><p>Life profile</p><h3>{projection.identity?.roleTitle || (lang === "zh" ? "她的生活档案" : "Her life profile")}</h3></div>
        </div>
        <VStatusChip tone={setupReady ? "success" : "warning"}>
          {setupReady ? (lang === "zh" ? "已确认" : "Confirmed") : (lang === "zh" ? "待确认" : "Draft")}
        </VStatusChip>
      </div>

      <p className={styles.lead}>
        {projection.location?.cityName || (lang === "zh" ? "城市未记录" : "City not recorded")}
        {projection.identity ? ` · ${identityLabel(projection.identity.kind, lang)}` : ""}
        {projection.routines.length ? ` · ${projection.routines.length} ${lang === "zh" ? "段固定作息" : "routine blocks"}` : ""}
      </p>

      <div className={styles.identityGrid}>
        <div className={styles.identityFact}><span>{lang === "zh" ? "学校 / 单位" : "School / workplace"}</span><strong>{projection.affiliation?.name || (lang === "zh" ? "未设置" : "Not set")}</strong></div>
        <div className={styles.identityFact}><span>{lang === "zh" ? "角色" : "Role"}</span><strong>{projection.affiliation?.role || projection.identity?.stage || (lang === "zh" ? "未设置" : "Not set")}</strong></div>
      </div>

      <div className={styles.assetList} aria-label={lang === "zh" ? "手头物品" : "Belongings"}>
        {projection.items.slice(0, 4).map((item) => (
          <span className={styles.asset} key={item.itemId}>
            {item.category === "phone" ? <Smartphone size={12} aria-hidden="true" /> : <Laptop size={12} aria-hidden="true" />}
            <span>{[item.brand, item.model].filter(Boolean).join(" ") || item.name}</span>
          </span>
        ))}
      </div>

      <div className={styles.moneyList} aria-label={lang === "zh" ? "虚构资产" : "Fictional finances"}>
        {projection.accounts.slice(0, 3).map((account) => (
          <div className={styles.moneyRow} key={account.accountId}><span>{account.name}</span><strong>{formatMoney(account.balanceMinor, account.currency, lang)}</strong></div>
        ))}
        {projection.recurringRules.slice(0, 2).map((rule) => (
          <div className={styles.moneyRow} key={rule.ruleId}><span>{rule.title}</span><strong>{formatMoney(rule.amountMinor, rule.currency, lang)} / {lang === "zh" ? "月" : "month"}</strong></div>
        ))}
      </div>

      {!setupReady && draft ? (
        <details className={styles.disclosure}>
          <summary className={styles.summary}>{lang === "zh" ? "调整草案" : "Edit draft"}</summary>
          <div className={styles.form}>
            <label className={styles.field}><span>{lang === "zh" ? "身份称呼" : "Role title"}</span><VInput value={form.roleTitle} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, roleTitle: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "阶段" : "Stage"}</span><VInput value={form.stage} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, stage: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "学校 / 单位" : "School / workplace"}</span><VInput value={form.affiliationName} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, affiliationName: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "院系 / 部门" : "Department"}</span><VInput value={form.affiliationDepartment} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, affiliationDepartment: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "身份 / 职位" : "Affiliation role"}</span><VInput value={form.affiliationRole} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, affiliationRole: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "手机品牌" : "Phone brand"}</span><VInput value={form.phoneBrand} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, phoneBrand: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "手机型号" : "Phone model"}</span><VInput value={form.phoneModel} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, phoneModel: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "电脑品牌" : "Computer brand"}</span><VInput value={form.computerBrand} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, computerBrand: event.target.value }))} /></label>
            <label className={styles.field}><span>{lang === "zh" ? "电脑型号" : "Computer model"}</span><VInput value={form.computerModel} disabled={draftMutation.isPending || confirmMutation.isPending} onChange={(event) => setForm((current) => ({ ...current, computerModel: event.target.value }))} /></label>
            <div className={styles.actions}>
              <VButton icon={<Save size={13} />} isPending={draftMutation.isPending} isDisabled={!dirty || confirmMutation.isPending} onPress={() => draftMutation.mutate()}>{lang === "zh" ? "保存草案" : "Save draft"}</VButton>
            </div>
          </div>
        </details>
      ) : null}

      {!setupReady && draft ? (
        <div className={styles.draftActions}>
          <VButton variant="primary" isPending={confirmMutation.isPending} isDisabled={dirty || draftMutation.isPending} onPress={() => confirmMutation.mutate()}>{lang === "zh" ? "确认并创建生活管家" : "Confirm and create steward"}</VButton>
        </div>
      ) : null}

      {steward?.enabled && steward.provisioningState === "ready" && steward.sessionId ? (
        <VButton
          variant="primary"
          icon={<MessageCircleMore size={14} />}
          onPress={() => onOpenSteward(steward.sessionId)}
        >
          {lang === "zh" ? "生活管理" : "Life management"}
        </VButton>
      ) : null}
      {feedback ? <p className={styles.notice} role="status">{feedback}</p> : null}
      <p className={styles.disclaimer}>{projection.world.draft?.payload.disclaimer || (lang === "zh" ? "学校、单位、物品和金额均为虚构人物的世界内数据。" : "School, workplace, belongings, and money are fictional in-world data.")}</p>
    </section>
  );
}
