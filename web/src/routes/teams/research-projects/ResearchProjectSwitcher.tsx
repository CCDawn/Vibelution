import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Pencil, Plus, Save } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { fetchJson } from "../../../api/client";
import type {
  ExperimentMethodId,
  TeamResearchProject,
  TeamResearchProjectListPayload,
} from "../../../api/types";
import {
  VButton,
  VDialog,
  VNativeInput,
  VNativeSelect,
  VStatusChip,
  type VStatusTone,
} from "../../../components/vui";

import styles from "./ResearchProjectSwitcher.module.css";

type ProjectDraft = {
  name: string;
  topic: string;
};

type ResearchProjectSwitcherProps = {
  teamId: string;
  lang: "zh" | "en";
  currentTopic: string;
  currentExperimentMethod: ExperimentMethodId | "";
  onProjectActivated: (project: TeamResearchProject) => void;
  variant?: "compact" | "hero";
  statusLabel?: string;
  statusTone?: "neutral" | "active" | "ready" | "warning";
  primaryActionHref?: string;
  primaryActionLabel?: string;
};

const EMPTY_DRAFT: ProjectDraft = { name: "", topic: "" };

function projectStatusTone(tone: NonNullable<ResearchProjectSwitcherProps["statusTone"]>): VStatusTone {
  if (tone === "active") return "accent";
  if (tone === "ready") return "success";
  if (tone === "warning") return "warning";
  return "neutral";
}

export function researchProjectQueryKey(teamId: string) {
  return ["teams", teamId, "research-projects"] as const;
}

export function projectDraftFromProject(project: TeamResearchProject | null): ProjectDraft {
  return project ? { name: project.name, topic: project.topic } : EMPTY_DRAFT;
}

export function ResearchProjectSwitcher({
  teamId,
  lang,
  currentTopic,
  currentExperimentMethod,
  onProjectActivated,
  variant = "compact",
  statusLabel = "",
  statusTone = "neutral",
  primaryActionHref = "",
  primaryActionLabel = "",
}: ResearchProjectSwitcherProps) {
  const queryClient = useQueryClient();
  const [dialogMode, setDialogMode] = useState<"create" | "edit" | null>(null);
  const [draft, setDraft] = useState<ProjectDraft>(EMPTY_DRAFT);
  const [message, setMessage] = useState("");
  const lastAppliedProjectIdRef = useRef("");
  const projectsQuery = useQuery({
    queryKey: researchProjectQueryKey(teamId),
    queryFn: () =>
      fetchJson<TeamResearchProjectListPayload>(
        `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects`,
      ),
    enabled: Boolean(teamId),
  });
  const activeProject = useMemo(
    () =>
      projectsQuery.data?.projects.find(
        (project) => project.projectId === projectsQuery.data?.activeProjectId,
      ) ?? null,
    [projectsQuery.data],
  );

  useEffect(() => setMessage(""), [teamId]);
  useEffect(() => {
    if (!activeProject || lastAppliedProjectIdRef.current === activeProject.projectId) {
      return;
    }
    lastAppliedProjectIdRef.current = activeProject.projectId;
    onProjectActivated(activeProject);
  }, [activeProject, onProjectActivated]);

  const refreshWorkflowQueries = async () => {
    await queryClient.invalidateQueries({
      predicate: (query) => query.queryKey.some((part) => part === teamId),
    });
  };

  const activateMutation = useMutation({
    mutationFn: (projectId: string) =>
      fetchJson<TeamResearchProjectListPayload>(
        `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects/${encodeURIComponent(projectId)}/activate`,
        { method: "POST" },
      ),
    onSuccess: async (payload) => {
      queryClient.setQueryData(researchProjectQueryKey(teamId), payload);
      if (payload.project) {
        onProjectActivated(payload.project);
      }
      await refreshWorkflowQueries();
      setMessage(lang === "zh" ? "已切换项目，三阶段数据已隔离刷新。" : "Project switched; stage data refreshed.");
    },
  });

  const createMutation = useMutation({
    mutationFn: () =>
      fetchJson<TeamResearchProjectListPayload>(
        `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: draft.name.trim(),
            topic: draft.topic.trim(),
            experimentMethod: currentExperimentMethod,
          }),
        },
      ),
    onSuccess: async (payload) => {
      queryClient.setQueryData(researchProjectQueryKey(teamId), payload);
      setDialogMode(null);
      setDraft(EMPTY_DRAFT);
      if (payload.project) {
        await activateMutation.mutateAsync(payload.project.projectId);
      }
    },
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      fetchJson<TeamResearchProjectListPayload>(
        `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/research-projects/${encodeURIComponent(activeProject?.projectId || "")}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...(activeProject?.nameLocked ? {} : { name: draft.name.trim() }),
            topic: draft.topic.trim(),
            experimentMethod: currentExperimentMethod,
          }),
        },
      ),
    onSuccess: (payload) => {
      queryClient.setQueryData(researchProjectQueryKey(teamId), payload);
      if (payload.project) {
        onProjectActivated(payload.project);
      }
      setDialogMode(null);
      setMessage(lang === "zh" ? "项目设置已保存。" : "Project settings saved.");
    },
  });

  const pending = activateMutation.isPending || createMutation.isPending || updateMutation.isPending;
  const error = activateMutation.error || createMutation.error || updateMutation.error || projectsQuery.error;
  const openDialog = (mode: "create" | "edit") => {
    setDialogMode(mode);
    setDraft(mode === "edit" ? projectDraftFromProject(activeProject) : { name: "", topic: currentTopic });
  };

  return (
    <section className={`${styles.root} ${variant === "hero" ? styles.hero : ""}`} aria-label={lang === "zh" ? "研究项目" : "Research projects"}>
      <div className={styles.identity}>
        <FolderKanban size={16} aria-hidden="true" />
        <div>
          <span>{lang === "zh" ? "当前研究项目" : "Current research project"}</span>
          <div className={styles.titleLine}>
            <strong>{activeProject?.name || (projectsQuery.isPending ? "…" : "—")}</strong>
            {statusLabel ? (
              <VStatusChip className={styles.status} tone={projectStatusTone(statusTone)}>
                {statusLabel}
              </VStatusChip>
            ) : null}
            {variant === "hero" ? <small>{lang === "zh" ? "已自动保存" : "Autosaved"}</small> : null}
          </div>
          {variant === "hero" ? (
            <p>{lang === "zh" ? "研究主题" : "Research topic"}：{activeProject?.topic || currentTopic || "—"}</p>
          ) : null}
        </div>
      </div>
      <label className={styles.projectSelect}>
        {variant === "hero" ? <span>{lang === "zh" ? "切换项目" : "Switch project"}</span> : null}
        <VNativeSelect
          value={projectsQuery.data?.activeProjectId || ""}
          onChange={(event) => activateMutation.mutate(event.target.value)}
          disabled={pending || projectsQuery.isPending}
          aria-label={lang === "zh" ? "切换研究项目" : "Switch research project"}
        >
          {(projectsQuery.data?.projects ?? []).map((project) => (
            <option key={project.projectId} value={project.projectId}>{project.name}</option>
          ))}
        </VNativeSelect>
      </label>
      <div className={styles.actions}>
        <VButton
          type="button"
          variant="secondary"
          density="compact"
          icon={<Pencil size={14} />}
          isDisabled={!activeProject || pending}
          onPress={() => openDialog("edit")}
        >
          {lang === "zh" ? "编辑" : "Edit"}
        </VButton>
        <VButton
          type="button"
          variant="primary"
          density="compact"
          icon={<Plus size={14} />}
          isDisabled={pending}
          onPress={() => openDialog("create")}
        >
          {lang === "zh" ? "新建项目" : "New project"}
        </VButton>
        {variant === "hero" && primaryActionHref && primaryActionLabel ? (
          <Link className={styles.primaryAction} to={primaryActionHref}>{primaryActionLabel}</Link>
        ) : null}
      </div>
      {message ? <p className={styles.message} role="status">{message}</p> : null}
      {error ? <p className={styles.error} role="alert">{lang === "zh" ? "项目操作失败，请重试。" : "Project operation failed."}</p> : null}
      <VDialog
        open={dialogMode !== null}
        onOpenChange={(open) => {
          if (!open && !pending) setDialogMode(null);
        }}
        title={dialogMode === "create"
          ? (lang === "zh" ? "新建研究项目" : "Create research project")
          : (lang === "zh" ? "编辑研究项目" : "Edit research project")}
        description={lang === "zh"
          ? "每个项目拥有独立的资料、实验设计和迭代数据。"
          : "Each project keeps independent evidence, experiment design, and iteration data."}
        size="sm"
        footer={(
          <>
            <VButton type="button" variant="secondary" density="compact" isDisabled={pending} onPress={() => setDialogMode(null)}>
              {lang === "zh" ? "取消" : "Cancel"}
            </VButton>
            <VButton
              type="button"
              variant="primary"
              density="compact"
              icon={<Save size={14} />}
              isDisabled={!draft.name.trim() || pending}
              onPress={() => dialogMode === "create" ? createMutation.mutate() : updateMutation.mutate()}
            >
              {pending ? (lang === "zh" ? "保存中…" : "Saving…") : (lang === "zh" ? "保存" : "Save")}
            </VButton>
          </>
        )}
      >
        <div className={styles.form}>
          <label>
            <span>{lang === "zh" ? "项目名称" : "Project name"}</span>
            <VNativeInput
              value={draft.name}
              onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              maxLength={160}
              disabled={dialogMode === "edit" && activeProject?.nameLocked === true}
              autoFocus
            />
            {dialogMode === "edit" && activeProject?.nameLocked ? (
              <small>
                {lang === "zh"
                  ? "首次实验任务已建立，项目名称已锁定；研究主题仍可继续修改。"
                  : "The name is locked after the first experiment task; the research topic remains editable."}
              </small>
            ) : null}
          </label>
          <label>
            <span>{lang === "zh" ? "研究主题" : "Research topic"}</span>
            <VNativeInput
              value={draft.topic}
              onChange={(event) => setDraft((current) => ({ ...current, topic: event.target.value }))}
              maxLength={1000}
            />
          </label>
        </div>
      </VDialog>
    </section>
  );
}
