import { useQuery } from "@tanstack/react-query";
import { Ban, BookOpen, CheckSquare, Copy, FileText, RefreshCw, Search, Sparkles, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { SkillLibraryDetail, SkillLibraryItem, SkillLibraryPayload } from "../api/types";
import { VButton, VIconButton, VRouteHeader } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { AgentManagementNav } from "./AgentManagementNav";

type SkillSourceFilter = "all" | "codex" | "agents" | "other";

const SOURCE_FILTERS: SkillSourceFilter[] = ["all", "codex", "agents", "other"];

const routeClass = "grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] bg-[color-mix(in_srgb,var(--surface-page)_94%,var(--bg-canvas))]";
const headerClass = "mx-2.5 mt-2 min-h-9 min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-gradient-route-soft),color-mix(in_srgb,var(--surface-panel)_86%,transparent)] shadow-[var(--vui-shadow-hairline)]";
const refreshButtonClass = "h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-h-[26px] rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card)] p-0 text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary disabled:opacity-55";
const controlStripClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-1.5 px-3 pt-1 max-[920px]:grid-cols-1";
const managementNavClass = "m-0";
const summaryGridClass = "grid min-w-0 grid-cols-4 overflow-hidden rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--border-soft)_78%,transparent)] bg-[color-mix(in_srgb,var(--surface-panel)_90%,var(--surface-card))] max-[920px]:grid-cols-1";
const summaryCardClass = "grid min-h-[26px] min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-[5px] border-0 border-r border-[color-mix(in_srgb,var(--border-soft)_58%,transparent)] bg-transparent px-2 py-[3px] last:border-r-0";
const summaryLabelClass = "text-[0.61rem] text-vui-fg-tertiary";
const summaryValueClass = "min-w-0 truncate text-[0.8rem] text-vui-fg-primary";
const workspaceClass = "grid min-h-0 grid-cols-[minmax(260px,340px)_minmax(440px,1fr)] gap-1.5 px-2.5 pb-2 pt-1.5 max-[920px]:grid-cols-1 max-[920px]:content-start max-[920px]:overflow-auto";
const panelClass = "grid min-h-0 min-w-0 content-start gap-[9px] rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2.5";
const listPanelClass = `${panelClass} grid-rows-[auto_auto_auto_minmax(0,1fr)]`;
const detailPanelClass = `${panelClass} overflow-auto`;
const panelHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const panelEyebrowClass = "m-0 mb-px text-[0.61rem] uppercase tracking-[0.07em] text-vui-fg-tertiary";
const panelTitleClass = "m-0 font-[var(--font-display)] text-base leading-[1.2] text-vui-fg-primary";
const detailDescriptionClass = "m-0 mt-[3px] text-[0.78rem] leading-[1.32] text-vui-fg-secondary";
const searchBoxClass = "flex min-h-8 items-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-input-strong)] px-2 text-vui-fg-tertiary";
const searchInputClass = "min-w-0 w-full border-0 bg-transparent text-vui-fg-primary outline-0";
const filterRowClass = "flex flex-wrap gap-[5px]";
const filterButtonClass = "min-h-[26px] rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card)] px-2 py-[3px] text-[0.78rem] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const filterButtonActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] text-[var(--accent-warm-2)]";
const primaryButtonClass = "min-h-[26px] rounded-[var(--radius-control)] border border-vui-border-soft bg-[var(--surface-card)] px-2 py-[3px] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-hover)] hover:text-vui-fg-primary";
const bulkActionBarClass = "flex min-w-0 flex-wrap items-center gap-[7px] rounded-lg border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-panel)_86%,var(--surface-card))] p-[7px]";
const bulkSummaryClass = "inline-flex min-h-7 items-center gap-1.5 text-[0.75rem] text-vui-fg-secondary";
const bulkSummaryTitleClass = "text-vui-fg-primary";
const bulkReadOnlyNoteClass = "inline-flex min-h-7 max-w-[min(420px,100%)] items-center text-[0.75rem] leading-[1.35] text-vui-fg-tertiary";
const skillListClass = "grid min-h-0 content-start gap-1.5 overflow-auto pr-1";
const selectableRowClass = "grid min-w-0 grid-cols-[28px_minmax(0,1fr)] items-center gap-[5px]";
const rowSelectClass = "grid h-9 w-7 cursor-pointer place-items-center rounded-lg border border-vui-border-soft bg-[var(--surface-card)] text-vui-fg-secondary hover:border-[var(--border-strong)] hover:text-[var(--accent-warm-2)]";
const hiddenCheckboxClass = "pointer-events-none absolute h-px w-px opacity-0";
const skillButtonBaseClass = [
  "block w-full rounded-lg border border-vui-border-soft bg-[var(--surface-panel-muted)] p-2 text-left text-vui-fg-primary hover:border-[var(--border-strong)] hover:bg-[var(--surface-panel-strong)]",
  "[&_[data-slot=vui-button-content]]:w-full",
  "[&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:grid-cols-[10px_minmax(0,1fr)_auto] [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-2",
].join(" ");
const skillButtonActiveClass = "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[var(--surface-active-neutral)] shadow-[var(--vui-shadow-inset-accent)]";
const sourceDotClass = "h-2 w-2 rounded-full bg-[var(--accent-cool)] data-[source=agents]:bg-[var(--accent-warm)] data-[source=other]:bg-vui-fg-tertiary";
const skillCopyClass = "grid min-w-0 gap-0.5";
const skillNameClass = "min-w-0 truncate text-vui-fg-primary";
const skillDescriptionClass = "m-0 min-w-0 truncate text-[0.76rem] leading-[1.3] text-vui-fg-secondary";
const sourcePillClass = "inline-flex min-h-[21px] items-center justify-center whitespace-nowrap rounded-full border border-vui-border-soft px-1.5 text-[0.72rem] text-vui-fg-secondary";
const emptyStateClass = "m-0 text-[0.76rem] leading-[1.3] text-vui-fg-secondary";
const detailHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const commandPanelClass = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2.5";
const commandBodyClass = "grid min-w-0 gap-1";
const commandLabelClass = "text-[0.61rem] text-vui-fg-tertiary";
const commandCodeClass = "min-w-0 truncate text-[0.98rem] text-[var(--accent-warm-2)]";
const commandFeedbackClass = "text-[0.78rem] text-[var(--state-success)]";
const metaGridClass = "grid grid-cols-[110px_minmax(0,1fr)] gap-x-2.5 gap-y-1.5 rounded-lg border border-vui-border-soft bg-[var(--surface-card)] p-2.5";
const metaLabelClass = "text-[0.61rem] text-vui-fg-tertiary";
const metaValueClass = "min-w-0 truncate text-[0.8rem] text-vui-fg-primary";
const surfacePanelClass = "grid gap-2 rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-2.5";
const contentHeaderClass = "flex min-w-0 items-start justify-between gap-3";
const contentPreClass = "m-0 max-h-[48vh] overflow-auto rounded-lg border border-vui-border-soft bg-[var(--surface-input-strong)] p-2.5 text-[0.78rem] leading-[1.48] text-vui-fg-primary whitespace-pre-wrap break-words";
const truncatedNoticeClass = "m-0 text-[0.76rem] leading-[1.3] text-vui-fg-secondary";
const rootRowClass = "grid min-w-0 grid-cols-[90px_minmax(0,1fr)] items-center gap-2.5";
const rootSourceClass = "text-[0.76rem] text-vui-fg-tertiary";
const rootPathClass = "min-w-0 truncate";
const emptyDetailClass = "grid min-h-[190px] place-items-center rounded-lg border border-vui-border-soft bg-[var(--surface-panel)] p-[18px] text-center max-[920px]:min-h-24 max-[920px]:p-3";
const emptyDetailTextClass = "m-0 text-[0.76rem] leading-[1.3] text-vui-fg-secondary";

function normalizeCommand(command: string) {
  return String(command || "").replace(/^\/+/, "").trim();
}

function sourceLabel(source: string, lang: string) {
  if (source === "codex") {
    return "Codex";
  }
  if (source === "agents") {
    return lang === "zh" ? "Agents 技能" : "Agents";
  }
  if (source === "other") {
    return lang === "zh" ? "其他" : "Other";
  }
  return source || (lang === "zh" ? "未知" : "Unknown");
}

function sourceFilterLabel(filter: SkillSourceFilter, lang: string) {
  if (filter === "all") {
    return lang === "zh" ? "全部" : "All";
  }
  return sourceLabel(filter, lang);
}

function formatBytes(value: number, lang: string) {
  const size = Number.isFinite(value) ? Math.max(0, value) : 0;
  if (size < 1024) {
    return lang === "zh" ? `${size} 字符` : `${size} chars`;
  }
  return `${(size / 1024).toFixed(size >= 10 * 1024 ? 0 : 1)}k`;
}

function skillSearchText(skill: SkillLibraryItem) {
  return [
    skill.name,
    skill.command,
    skill.description,
    skill.directoryName,
    skill.path,
    ...(skill.aliases ?? []),
  ].join(" ").toLowerCase();
}

function copyFor(lang: string) {
  return lang === "zh"
    ? {
        title: "Skill Library",
        eyebrow: "本地技能",
        subtitle: "查看本机可通过斜杠指令调用的 SKILL.md，不在这里安装、编辑或删除。",
        refresh: "刷新",
        search: "搜索技能、别名或路径",
        listTitle: "可用 Skill",
        detailTitle: "Skill 详情",
        emptyList: "没有匹配的 skill。",
        emptyDetail: "选择一个 skill 查看调用方式和 SKILL.md 预览。",
        rootPaths: "扫描根目录",
        command: "斜杠指令",
        aliases: "别名",
        path: "路径",
        hash: "内容哈希",
        size: "大小",
        preview: "SKILL.md 预览",
        fullContent: "完整内容",
        loading: "加载中...",
        loadFailed: "加载失败",
        copied: "已复制",
        copyCommand: "复制指令",
        bulkSelected: "已选",
        bulkSelectVisible: "选择当前列表",
        bulkClear: "清空",
        bulkCopyCommands: "批量复制指令",
        bulkEdit: "批量编辑",
        bulkDelete: "批量删除",
        bulkReadOnlyReason: "技能库当前是只读索引；本页不直接编辑或删除本机 SKILL.md。",
        bulkNoSelection: "请先选择 skill。",
        readOnly: "只读",
        truncated: "内容已截断",
      }
    : {
        title: "Skill Library",
        eyebrow: "Local skills",
        subtitle: "Browse local SKILL.md files callable through slash commands. Install, edit, and delete are out of this page.",
        refresh: "Refresh",
        search: "Search skills, aliases, or paths",
        listTitle: "Available Skills",
        detailTitle: "Skill Detail",
        emptyList: "No matching skills.",
        emptyDetail: "Select a skill to inspect its slash command and SKILL.md preview.",
        rootPaths: "Scan roots",
        command: "Slash command",
        aliases: "Aliases",
        path: "Path",
        hash: "Content hash",
        size: "Size",
        preview: "SKILL.md preview",
        fullContent: "Full content",
        loading: "Loading...",
        loadFailed: "Load failed",
        copied: "Copied",
        copyCommand: "Copy command",
        bulkSelected: "Selected",
        bulkSelectVisible: "Select visible",
        bulkClear: "Clear",
        bulkCopyCommands: "Copy commands",
        bulkEdit: "Bulk edit",
        bulkDelete: "Bulk delete",
        bulkReadOnlyReason: "The skill library is a read-only index; this page does not edit or delete local SKILL.md files.",
        bulkNoSelection: "Select skills first.",
        readOnly: "Read-only",
        truncated: "Content truncated",
      };
}

export function SkillsRoute() {
  const { lang } = useShellI18n();
  const copy = useMemo(() => copyFor(lang), [lang]);
  const [searchText, setSearchText] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SkillSourceFilter>("all");
  const [activeCommand, setActiveCommand] = useState("");
  const [copyState, setCopyState] = useState("");
  const [selectedSkillCommands, setSelectedSkillCommands] = useState<Set<string>>(() => new Set());

  const libraryQuery = useQuery({
    queryKey: queryKeys.skills(),
    queryFn: () => fetchJson<SkillLibraryPayload>("/api/skills"),
  });
  const skills = libraryQuery.data?.skills ?? [];
  const filteredSkills = useMemo(() => {
    const term = searchText.trim().toLowerCase();
    return skills.filter((skill) => {
      if (sourceFilter !== "all" && skill.source !== sourceFilter) {
        return false;
      }
      return !term || skillSearchText(skill).includes(term);
    });
  }, [searchText, skills, sourceFilter]);
  const selectedSkills = useMemo(
    () => filteredSkills.filter((skill) => selectedSkillCommands.has(skill.command)),
    [filteredSkills, selectedSkillCommands],
  );
  const allVisibleSkillsSelected = filteredSkills.length > 0 && selectedSkills.length === filteredSkills.length;

  useEffect(() => {
    if (activeCommand && skills.some((skill) => skill.command === activeCommand)) {
      return;
    }
    setActiveCommand(filteredSkills[0]?.command ?? "");
  }, [activeCommand, filteredSkills, skills]);

  useEffect(() => {
    setSelectedSkillCommands((current) => {
      const visibleCommands = new Set(filteredSkills.map((skill) => skill.command));
      const next = new Set(Array.from(current).filter((command) => visibleCommands.has(command)));
      return next.size === current.size ? current : next;
    });
  }, [filteredSkills]);

  const detailQuery = useQuery({
    queryKey: queryKeys.skill(activeCommand),
    queryFn: () => fetchJson<SkillLibraryDetail>(`/api/skills/${encodeURIComponent(normalizeCommand(activeCommand))}`),
    enabled: Boolean(activeCommand),
  });
  const activeSkill = detailQuery.data ?? filteredSkills.find((skill) => skill.command === activeCommand) ?? null;
  const counts = libraryQuery.data?.counts ?? { total: 0, codex: 0, agents: 0, other: 0 };

  async function copyCommand(command: string) {
    const text = `${command} `;
    try {
      await navigator.clipboard?.writeText(text);
      setCopyState(copy.copied);
    } catch {
      setCopyState(text);
    }
  }

  function toggleSkillSelection(command: string, selected: boolean) {
    setSelectedSkillCommands((current) => {
      const next = new Set(current);
      if (selected) {
        next.add(command);
      } else {
        next.delete(command);
      }
      return next;
    });
  }

  function selectVisibleSkills() {
    setSelectedSkillCommands(new Set(filteredSkills.map((skill) => skill.command)));
  }

  function clearSelectedSkills() {
    setSelectedSkillCommands(new Set());
  }

  async function copySelectedSkillCommands() {
    if (!selectedSkills.length) {
      setCopyState(copy.bulkNoSelection);
      return;
    }
    const text = selectedSkills.map((skill) => `${skill.command} `).join("\n");
    try {
      await navigator.clipboard?.writeText(text);
      setCopyState(copy.copied);
    } catch {
      setCopyState(text);
    }
  }

  return (
    <section className={routeClass}>
      <VRouteHeader
        className={headerClass}
        eyebrow={copy.eyebrow}
        title={copy.title}
        meta={copy.subtitle}
        actions={(
          <VIconButton
            type="button"
            className={refreshButtonClass}
            label={copy.refresh}
            icon={<RefreshCw size={15} />}
            isDisabled={libraryQuery.isFetching}
            onPress={() => libraryQuery.refetch()}
          />
        )}
      />

      <div className={controlStripClass}>
        <AgentManagementNav active="skills" className={managementNavClass} />

        <div className={summaryGridClass}>
          <section className={summaryCardClass}>
            <span className={summaryLabelClass}>Total</span>
            <strong className={summaryValueClass}>{counts.total}</strong>
          </section>
          <section className={summaryCardClass}>
            <span className={summaryLabelClass}>Codex</span>
            <strong className={summaryValueClass}>{counts.codex}</strong>
          </section>
          <section className={summaryCardClass}>
            <span className={summaryLabelClass}>Agents</span>
            <strong className={summaryValueClass}>{counts.agents}</strong>
          </section>
          <section className={summaryCardClass}>
            <span className={summaryLabelClass}>{copy.readOnly}</span>
            <strong className={summaryValueClass}>{libraryQuery.data?.mode ?? "read_only"}</strong>
          </section>
        </div>
      </div>

      <main className={workspaceClass}>
        <aside className={listPanelClass}>
          <div className={panelHeaderClass}>
            <div>
              <p className={panelEyebrowClass}>{copy.listTitle}</p>
              <h2 className={panelTitleClass}>{filteredSkills.length} / {skills.length}</h2>
            </div>
            <Sparkles size={17} />
          </div>

          <label className={searchBoxClass}>
            <Search size={14} />
            <input className={searchInputClass} value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={copy.search} />
          </label>

          <div className={filterRowClass}>
            {SOURCE_FILTERS.map((filter) => (
              <VButton
                key={filter}
                type="button"
                className={sourceFilter === filter ? `${filterButtonClass} ${filterButtonActiveClass}` : filterButtonClass}
                onPress={() => setSourceFilter(filter)}
              >
                {sourceFilterLabel(filter, lang)}
              </VButton>
            ))}
          </div>

          <section className={bulkActionBarClass} aria-label={copy.bulkSelected}>
            <div className={bulkSummaryClass}>
              <CheckSquare size={15} />
              <strong className={bulkSummaryTitleClass}>{copy.bulkSelected}</strong>
              <span>{selectedSkills.length} / {filteredSkills.length}</span>
            </div>
            <VButton
              type="button"
              className={primaryButtonClass}
              icon={<Copy size={14} />}
              isDisabled={!selectedSkills.length}
              onPress={copySelectedSkillCommands}
            >
              {copy.bulkCopyCommands}
            </VButton>
            <VButton
              type="button"
              className={filterButtonClass}
              icon={allVisibleSkillsSelected ? <Square size={14} /> : <CheckSquare size={14} />}
              isDisabled={!filteredSkills.length}
              onPress={allVisibleSkillsSelected ? clearSelectedSkills : selectVisibleSkills}
            >
              {allVisibleSkillsSelected ? copy.bulkClear : copy.bulkSelectVisible}
            </VButton>
            <span className={bulkReadOnlyNoteClass}>{copy.bulkReadOnlyReason}</span>
            <VButton
              type="button"
              className={filterButtonClass}
              icon={<Ban size={14} />}
              isDisabled
              title={copy.bulkReadOnlyReason}
            >
              {copy.bulkEdit}
            </VButton>
            <VButton
              type="button"
              className={filterButtonClass}
              icon={<Ban size={14} />}
              isDisabled
              title={copy.bulkReadOnlyReason}
            >
              {copy.bulkDelete}
            </VButton>
          </section>

          <div className={skillListClass}>
            {libraryQuery.isError ? (
              <p className={emptyStateClass}>{copy.loadFailed}</p>
            ) : libraryQuery.isPending ? (
              <p className={emptyStateClass}>{copy.loading}</p>
            ) : filteredSkills.length === 0 ? (
              <p className={emptyStateClass}>{copy.emptyList}</p>
            ) : (
              filteredSkills.map((skill) => {
                const selected = selectedSkillCommands.has(skill.command);
                return (
                  <div key={`${skill.path}-${skill.hash}`} className={selectableRowClass}>
                    <label className={rowSelectClass} title={`${copy.bulkSelected}: ${skill.name}`}>
                      <input
                        className={hiddenCheckboxClass}
                        type="checkbox"
                        checked={selected}
                        aria-label={`${copy.bulkSelected}: ${skill.name}`}
                        onChange={(event) => toggleSkillSelection(skill.command, event.target.checked)}
                      />
                      {selected ? <CheckSquare size={15} /> : <Square size={15} />}
                    </label>
                    <VButton
                      type="button"
                      className={activeCommand === skill.command ? `${skillButtonBaseClass} ${skillButtonActiveClass}` : skillButtonBaseClass}
                      onPress={() => setActiveCommand(skill.command)}
                    >
                      <span className={sourceDotClass} data-source={skill.source} />
                      <span className={skillCopyClass}>
                        <strong className={skillNameClass}>{skill.name}</strong>
                        <span className={skillDescriptionClass}>{skill.description || skill.command}</span>
                      </span>
                      <span className={sourcePillClass}>{sourceLabel(skill.source, lang)}</span>
                    </VButton>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        <section className={detailPanelClass}>
          {activeSkill ? (
            <>
              <div className={detailHeaderClass}>
                <div>
                  <p className={panelEyebrowClass}>{copy.detailTitle}</p>
                  <h2 className={panelTitleClass}>{activeSkill.name}</h2>
                  <p className={detailDescriptionClass}>{activeSkill.description || activeSkill.directoryName}</p>
                </div>
                <VButton
                  type="button"
                  className={primaryButtonClass}
                  icon={<Copy size={15} />}
                  onPress={() => copyCommand(activeSkill.command)}
                >
                  {copy.copyCommand}
                </VButton>
              </div>

              <div className={commandPanelClass}>
                <BookOpen size={17} />
                <div className={commandBodyClass}>
                  <span className={commandLabelClass}>{copy.command}</span>
                  <code className={commandCodeClass}>{activeSkill.command} </code>
                </div>
                {copyState ? <strong className={commandFeedbackClass}>{copyState}</strong> : null}
              </div>

              <div className={metaGridClass}>
                <span className={metaLabelClass}>{copy.aliases}</span>
                <strong className={metaValueClass}>{activeSkill.aliases.join(", ") || "-"}</strong>
                <span className={metaLabelClass}>{copy.path}</span>
                <strong className={metaValueClass} title={activeSkill.path}>{activeSkill.path}</strong>
                <span className={metaLabelClass}>{copy.hash}</span>
                <strong className={metaValueClass}>{activeSkill.hash}</strong>
                <span className={metaLabelClass}>{copy.size}</span>
                <strong className={metaValueClass}>{formatBytes(activeSkill.contentLength, lang)}</strong>
              </div>

              <section className={surfacePanelClass}>
                <div className={contentHeaderClass}>
                  <div>
                    <p className={panelEyebrowClass}>{detailQuery.data ? copy.fullContent : copy.preview}</p>
                    <h3 className={panelTitleClass}>SKILL.md</h3>
                  </div>
                  <FileText size={17} />
                </div>
                <pre className={contentPreClass}>{detailQuery.data?.content ?? activeSkill.preview}</pre>
                {detailQuery.data?.contentTruncated || activeSkill.previewTruncated ? (
                  <p className={truncatedNoticeClass}>{copy.truncated}</p>
                ) : null}
              </section>

              <section className={surfacePanelClass}>
                <p className={panelEyebrowClass}>{copy.rootPaths}</p>
                {(libraryQuery.data?.roots ?? []).map((root) => (
                  <div key={root.path} className={rootRowClass}>
                    <span className={rootSourceClass}>{sourceLabel(root.source, lang)}</span>
                    <code className={rootPathClass}>{root.path}</code>
                  </div>
                ))}
              </section>
            </>
          ) : (
            <div className={emptyDetailClass}>
              <Sparkles size={20} />
              <p className={emptyDetailTextClass}>{copy.emptyDetail}</p>
            </div>
          )}
        </section>
      </main>
    </section>
  );
}
