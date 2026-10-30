import "../design/route-css/workbench-secondary.tailwind.css";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getLauncherBranchInstances, isLauncherProjectNotSelected, selectLauncherProject } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { VButton, VDenseOpsPage, VStateSurface } from "../components/vui";
import { useLauncherLanguage } from "../i18n/useLauncherLanguage";
import { LauncherRoute } from "./LauncherRoute";
import styles from "./LauncherProjectRoute.styles";

/** A project is selected independently of the resident assistant and its window. */
export function LauncherProjectRoute() {
  const lang = useLauncherLanguage();
  const client = useQueryClient();
  const projects = useQuery({ queryKey:queryKeys.launcherBranchInstances(), queryFn:()=>getLauncherBranchInstances(), retry:false });
  const [pending,setPending] = useState(false);
  const [error,setError] = useState("");
  async function selectProject() {
    if(pending) return;
    setPending(true);setError("");
    try { const result=await selectLauncherProject(); if(result.connected) await Promise.all([client.invalidateQueries({queryKey:queryKeys.launcherBranchInstances()}),client.invalidateQueries({queryKey:queryKeys.launcherStatus()})]); }
    catch(error) { setError(error instanceof Error ? error.message : String(error)); } finally {setPending(false);}
  }
  if(projects.isPending) return <VStateSurface fill tone="loading" title={lang === "zh" ? "正在读取项目…" : "Loading project…"}/>;
  if(!isLauncherProjectNotSelected(projects.error)) return <LauncherRoute/>;
  return <VDenseOpsPage title={lang === "zh" ? "项目与分支" : "Projects & branches"} className={styles.page} bodyClassName={styles.body}>
    <VStateSurface tone="empty" title={lang === "zh" ? "选择一个本地项目" : "Select a local project"}
      actions={<VButton variant="primary" isPending={pending} onClick={()=>void selectProject()}>{lang === "zh" ? "选择项目" : "Select project"}</VButton>}>
      {lang === "zh" ? "助理可以独立使用。选择项目后，再管理它的分支和工作区。" : "The assistant works independently. Select a project to manage its branches and workspaces."}
    </VStateSurface>{error ? <VStateSurface tone="error" title={error}/> : null}
  </VDenseOpsPage>;
}
