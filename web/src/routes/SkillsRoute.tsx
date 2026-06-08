import { useQuery } from "@tanstack/react-query";
import { Ban, BookOpen, CheckSquare, Copy, FileText, RefreshCw, Search, Sparkles, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { SkillLibraryDetail, SkillLibraryItem, SkillLibraryPayload } from "../api/types";
import { useShellI18n } from "../i18n/useShellI18n";
import { AgentManagementNav } from "./AgentManagementNav";
import styles from "./SkillsRoute.module.css";

type SkillSourceFilter = "all" | "codex" | "agents" | "other";

const SOURCE_FILTERS: SkillSourceFilter[] = ["all", "codex", "agents", "other"];

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
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1>{copy.title}</h1>
          <p>{copy.subtitle}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={() => libraryQuery.refetch()} disabled={libraryQuery.isFetching}>
          <RefreshCw size={15} />
          <span>{copy.refresh}</span>
        </button>
      </header>

      <div className={styles.controlStrip}>
        <AgentManagementNav active="skills" className={styles.managementNav} />

        <div className={styles.summaryGrid}>
          <section className={styles.summaryCard}>
            <span>Total</span>
            <strong>{counts.total}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>Codex</span>
            <strong>{counts.codex}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>Agents</span>
            <strong>{counts.agents}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.readOnly}</span>
            <strong>{libraryQuery.data?.mode ?? "read_only"}</strong>
          </section>
        </div>
      </div>

      <main className={styles.workspace}>
        <aside className={styles.listPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.listTitle}</p>
              <h2>{filteredSkills.length} / {skills.length}</h2>
            </div>
            <Sparkles size={17} />
          </div>

          <label className={styles.searchBox}>
            <Search size={14} />
            <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={copy.search} />
          </label>

          <div className={styles.filterRow}>
            {SOURCE_FILTERS.map((filter) => (
              <button
                key={filter}
                type="button"
                className={sourceFilter === filter ? styles.filterButtonActive : styles.filterButton}
                onClick={() => setSourceFilter(filter)}
              >
                {sourceFilterLabel(filter, lang)}
              </button>
            ))}
          </div>

          <section className={styles.bulkActionBar} aria-label={copy.bulkSelected}>
            <div className={styles.bulkSummary}>
              <CheckSquare size={15} />
              <strong>{copy.bulkSelected}</strong>
              <span>{selectedSkills.length} / {filteredSkills.length}</span>
            </div>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={!selectedSkills.length}
              onClick={copySelectedSkillCommands}
            >
              <Copy size={14} />
              <span>{copy.bulkCopyCommands}</span>
            </button>
            <button
              type="button"
              className={styles.filterButton}
              disabled={!filteredSkills.length}
              onClick={allVisibleSkillsSelected ? clearSelectedSkills : selectVisibleSkills}
            >
              {allVisibleSkillsSelected ? <Square size={14} /> : <CheckSquare size={14} />}
              <span>{allVisibleSkillsSelected ? copy.bulkClear : copy.bulkSelectVisible}</span>
            </button>
            <button type="button" className={styles.filterButton} disabled title={copy.bulkReadOnlyReason}>
              <Ban size={14} />
              <span>{copy.bulkEdit}</span>
            </button>
            <button type="button" className={styles.filterButton} disabled title={copy.bulkReadOnlyReason}>
              <Ban size={14} />
              <span>{copy.bulkDelete}</span>
            </button>
          </section>

          <div className={styles.skillList}>
            {libraryQuery.isError ? (
              <p className={styles.emptyState}>{copy.loadFailed}</p>
            ) : libraryQuery.isPending ? (
              <p className={styles.emptyState}>{copy.loading}</p>
            ) : filteredSkills.length === 0 ? (
              <p className={styles.emptyState}>{copy.emptyList}</p>
            ) : (
              filteredSkills.map((skill) => {
                const selected = selectedSkillCommands.has(skill.command);
                return (
                  <div key={`${skill.path}-${skill.hash}`} className={styles.selectableRow}>
                    <label className={styles.rowSelect} title={`${copy.bulkSelected}: ${skill.name}`}>
                      <input
                        type="checkbox"
                        checked={selected}
                        aria-label={`${copy.bulkSelected}: ${skill.name}`}
                        onChange={(event) => toggleSkillSelection(skill.command, event.target.checked)}
                      />
                      {selected ? <CheckSquare size={15} /> : <Square size={15} />}
                    </label>
                    <button
                      type="button"
                      className={activeCommand === skill.command ? styles.skillButtonActive : styles.skillButton}
                      onClick={() => setActiveCommand(skill.command)}
                    >
                      <span className={styles.sourceDot} data-source={skill.source} />
                      <span className={styles.skillCopy}>
                        <strong>{skill.name}</strong>
                        <span>{skill.description || skill.command}</span>
                      </span>
                      <span className={styles.sourcePill}>{sourceLabel(skill.source, lang)}</span>
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        <section className={styles.detailPanel}>
          {activeSkill ? (
            <>
              <div className={styles.detailHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.detailTitle}</p>
                  <h2>{activeSkill.name}</h2>
                  <p>{activeSkill.description || activeSkill.directoryName}</p>
                </div>
                <button type="button" className={styles.primaryButton} onClick={() => copyCommand(activeSkill.command)}>
                  <Copy size={15} />
                  <span>{copy.copyCommand}</span>
                </button>
              </div>

              <div className={styles.commandPanel}>
                <BookOpen size={17} />
                <div>
                  <span>{copy.command}</span>
                  <code>{activeSkill.command} </code>
                </div>
                {copyState ? <strong>{copyState}</strong> : null}
              </div>

              <div className={styles.metaGrid}>
                <span>{copy.aliases}</span>
                <strong>{activeSkill.aliases.join(", ") || "-"}</strong>
                <span>{copy.path}</span>
                <strong title={activeSkill.path}>{activeSkill.path}</strong>
                <span>{copy.hash}</span>
                <strong>{activeSkill.hash}</strong>
                <span>{copy.size}</span>
                <strong>{formatBytes(activeSkill.contentLength, lang)}</strong>
              </div>

              <section className={styles.contentPanel}>
                <div className={styles.contentHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{detailQuery.data ? copy.fullContent : copy.preview}</p>
                    <h3>SKILL.md</h3>
                  </div>
                  <FileText size={17} />
                </div>
                <pre>{detailQuery.data?.content ?? activeSkill.preview}</pre>
                {detailQuery.data?.contentTruncated || activeSkill.previewTruncated ? (
                  <p className={styles.truncatedNotice}>{copy.truncated}</p>
                ) : null}
              </section>

              <section className={styles.rootsPanel}>
                <p className={styles.panelEyebrow}>{copy.rootPaths}</p>
                {(libraryQuery.data?.roots ?? []).map((root) => (
                  <div key={root.path} className={styles.rootRow}>
                    <span>{sourceLabel(root.source, lang)}</span>
                    <code>{root.path}</code>
                  </div>
                ))}
              </section>
            </>
          ) : (
            <div className={styles.emptyDetail}>
              <Sparkles size={20} />
              <p>{copy.emptyDetail}</p>
            </div>
          )}
        </section>
      </main>
    </section>
  );
}
