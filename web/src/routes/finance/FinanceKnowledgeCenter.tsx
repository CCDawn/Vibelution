import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, RefreshCw } from "lucide-react";
import { fetchMemoryAgentDetail } from "../../api/memory";
import { queryKeys } from "../../api/queryKeys";
import { fetchSkillLibrary, fetchSkillLibraryDetail } from "../../api/skills";
import { fetchFinancialPreferences, financialPreferenceKeys, removeFinancialPreference, saveFinancialPreference } from "../../api/financialPreferences";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { StockIdentity } from "../../api/financialMarket";
import { VButton, VInput, VStateSurface, VSurface, VTextarea } from "../../components/vui";
import type { AgentMemoryInventoryPayload } from "../memory/agentMemoryView";
import { FINANCE_GUIDES, FINANCE_LESSONS } from "./financeLearning";
import styles from "./FinanceKnowledgeCenter.styles";

type CenterProps = { assistant: FinancialAssistant; stock: StockIdentity; zh: boolean; onResearchPrompt: (text: string) => void };
export function FinanceKnowledgeCenter({ mode, ...props }: CenterProps & { mode: "memory" | "skills" | "learning" }) {
  return mode === "learning" ? <Learning {...props} /> : mode === "memory" ? <Memory {...props} /> : <Skills {...props} />;
}

function Memory({ assistant, zh, onResearchPrompt }: CenterProps) {
  const [selectedId, setSelectedId] = useState("");
  const [preference, setPreference] = useState("");
  const [saved, setSaved] = useState(false);
  const client = useQueryClient();
  const gate = useRef(false);
  const pendingRequest = useRef<{ text: string; id: string } | null>(null);
  const preferences = useQuery({ queryKey: financialPreferenceKeys.agent(assistant.agentId), queryFn: ({ signal }) => fetchFinancialPreferences(assistant.agentId, { signal }), staleTime: 15_000, retry: false });
  const save = useMutation({ mutationFn: ({ text, id }: { text: string; id: string }) => saveFinancialPreference(assistant.agentId, text, id), onSuccess: async () => { pendingRequest.current = null; setPreference(""); setSaved(true); await client.invalidateQueries({ queryKey: financialPreferenceKeys.agent(assistant.agentId) }); } });
  const remove = useMutation({ mutationFn: (id: string) => removeFinancialPreference(assistant.agentId, id), onSuccess: () => client.invalidateQueries({ queryKey: financialPreferenceKeys.agent(assistant.agentId) }) });
  async function savePreference() {
    const text = preference.trim();
    if (!text || gate.current || preferences.data?.memoryEnabled !== true) return;
    if (pendingRequest.current?.text !== text) pendingRequest.current = { text, id: crypto.randomUUID() };
    gate.current = true;
    try { await save.mutateAsync(pendingRequest.current); } catch { /* mutation owns the visible error */ }
    finally { gate.current = false; }
  }
  async function removePreference(id: string) {
    if (gate.current) return;
    gate.current = true;
    try { await remove.mutateAsync(id); } catch { /* mutation owns the visible error */ }
    finally { gate.current = false; }
  }
  const query = useQuery({ queryKey: queryKeys.memoryAgentDetail(assistant.agentId, "finance"), queryFn: ({ signal }) => fetchMemoryAgentDetail<AgentMemoryInventoryPayload>(assistant.agentId, { actorAgentId: assistant.agentId, includeContent: true, signal }), staleTime: 15_000, retry: false });
  const agent = query.data?.selectedAgent?.agentId === assistant.agentId ? query.data.selectedAgent : undefined;
  const items = agent?.items ?? [];
  const selected = items.find((item) => item.id === selectedId);
  return <div className={styles.page} data-finance-memory><div className={styles.toolbar}><h1 className={styles.heading}>{zh ? "研究记忆" : "Research memory"}</h1><VButton icon={<RefreshCw size={14} />} isPending={query.isFetching || preferences.isFetching} onPress={() => { void query.refetch(); void preferences.refetch(); }}>{zh ? "刷新" : "Refresh"}</VButton></div>
    <VSurface className={styles.card}><label className={styles.field}>{zh ? "让助手记住" : "Remember a preference"}<VTextarea value={preference} maxLength={1000} minRows={3} placeholder={zh ? "例如：只研究A股，先看现金流，重点关注风险" : "Research preferences"} onChange={(event) => { setPreference(event.target.value); setSaved(false); }} /></label><div className={styles.actions}><VButton isPending={save.isPending} isDisabled={!preference.trim() || preferences.data?.memoryEnabled !== true || remove.isPending} onPress={() => void savePreference()}>{zh ? "保存偏好" : "Save preference"}</VButton>{saved ? <span role="status" className={styles.success}>{zh ? "已保存" : "Saved"}</span> : null}</div>{preferences.data?.memoryEnabled === false ? <p className={styles.warning}>{zh ? "此助手的个人记忆已关闭" : "Personal memory is disabled"}</p> : null}{preferences.isError || save.isError || remove.isError ? <p role="alert" className={styles.warning}>{preferences.error?.message || save.error?.message || remove.error?.message}</p> : null}</VSurface>
    {preferences.data?.items.length ? <VSurface className={styles.card}><div className={styles.toolbar}><h2 className={styles.title}>{zh ? "已保存偏好" : "Saved preferences"}</h2><VButton variant="ghost" onPress={() => onResearchPrompt("请核对你当前已加载的个人研究偏好，并说明这些偏好如何影响本次研究。没有已加载记忆时明确说明。")}>{zh ? "向助手核对" : "Check with assistant"}</VButton></div>{preferences.data.items.map((item) => <div key={item.id} className={styles.toolbar}><p className={styles.text}>{item.text}</p><VButton variant="ghost" isDisabled={save.isPending || remove.isPending} onPress={() => void removePreference(item.id)}>{zh ? "移除" : "Remove"}</VButton></div>)}</VSurface> : null}
    {query.isPending ? <VStateSurface tone="loading" busy title={zh ? "加载记忆" : "Loading memory"} /> : query.isError || !agent ? <VStateSurface tone="error" title={zh ? "记忆不可用" : "Memory unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error?.message}</VStateSurface> : !items.length ? preferences.data?.items.length ? null : <VStateSurface tone="empty" title={zh ? "暂无已保存记忆" : "No saved memory"} /> : <div className={styles.columns}><div className={styles.list}>{items.map((item) => <VButton key={item.id} variant="secondary" className={[styles.listItem, item.id === selectedId ? styles.selected : ""].join(" ")} onPress={() => setSelectedId(item.id)}><span className={styles.skill}><strong>{item.title || item.relativePath || item.id}</strong><span className={styles.small}>{item.updatedAt ? new Date(item.updatedAt).toLocaleString() : ""}</span></span></VButton>)}</div><VSurface className={styles.card}>{selected ? <><h2 className={styles.title}>{selected.title || selected.relativePath}</h2><p className={styles.content}>{selected.content || selected.summary || (zh ? "此条目没有可显示正文" : "No readable body")}</p>{selected.contentTruncated ? <p className={styles.small}>{zh ? "正文为服务端提供的部分内容" : "Body is truncated by the service"}</p> : null}</> : <p className={styles.small}>{zh ? "选择一条记忆查看" : "Select a memory"}</p>}</VSurface></div>}
  </div>;
}

function Skills({ stock, zh, onResearchPrompt }: CenterProps) {
  const [search, setSearch] = useState("");
  const [command, setCommand] = useState("");
  const library = useQuery({ queryKey: queryKeys.skills(), queryFn: fetchSkillLibrary, staleTime: 60_000, retry: false });
  const skillName = command.replace(/^\/+/, "").trim();
  const detail = useQuery({ queryKey: queryKeys.skill(skillName), queryFn: () => fetchSkillLibraryDetail(skillName), enabled: Boolean(skillName), staleTime: 60_000, retry: false });
  const seenCommands = new Set<string>();
  const searchText = search.toLocaleLowerCase();
  const skills = (library.data?.skills ?? []).filter((skill) => {
    if (!`${skill.name} ${skill.description} ${skill.command}`.toLocaleLowerCase().includes(searchText)) return false;
    if (seenCommands.has(skill.command)) return false;
    seenCommands.add(skill.command);
    return true;
  });
  return <div className={styles.page} data-finance-skills><h1 className={styles.heading}>{zh ? "技能中心" : "Skill center"}</h1><VInput value={search} maxLength={100} aria-label={zh ? "搜索技能" : "Search skills"} placeholder={zh ? "搜索已安装技能" : "Search installed skills"} onChange={(event) => setSearch(event.target.value)} />
    {library.isPending ? <VStateSurface tone="loading" busy title={zh ? "加载技能" : "Loading skills"} /> : library.isError ? <VStateSurface tone="error" title={zh ? "技能加载失败" : "Skills unavailable"} actions={<VButton onPress={() => void library.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : <div className={styles.columns}><div className={styles.list}>{skills.length ? skills.map((skill) => <VButton key={`${skill.source}:${skill.command}`} variant="secondary" className={[styles.listItem, command === skill.command ? styles.selected : ""].join(" ")} onPress={() => setCommand(skill.command)}><span className={styles.skill}><strong>{skill.name}</strong><span className={styles.description}>{skill.description}</span></span></VButton>) : <VStateSurface tone="empty" title={zh ? "没有匹配技能" : "No matching skills"} />}</div><VSurface className={styles.card}>{!command ? <p className={styles.small}>{zh ? "选择技能查看使用方法" : "Select a skill"}</p> : detail.isPending ? <VStateSurface tone="loading" busy title={zh ? "加载使用方法" : "Loading instructions"} /> : detail.isError ? <VStateSurface tone="error" title={zh ? "技能详情不可用" : "Skill unavailable"} actions={<VButton onPress={() => void detail.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : detail.data ? <><h2 className={styles.title}>{detail.data.name}</h2><p className={styles.content}>{detail.data.content}</p><VButton icon={<BookOpen size={14} />} onPress={() => onResearchPrompt(`${detail.data.command}\n请先核实此技能在当前会话可用，再按其适用范围研究 ${stock.name}（${stock.ticker}）；不能使用时说明原因，不虚构技能执行。`)}>{zh ? "用此技能研究当前股票" : "Use for selected stock"}</VButton></> : null}</VSurface></div>}
  </div>;
}

function Learning({ stock, zh, onResearchPrompt }: CenterProps) {
  const [lessonId, setLessonId] = useState<string>(FINANCE_LESSONS[0].id);
  const [answer, setAnswer] = useState<number | null>(null);
  const lesson = FINANCE_LESSONS.find((item) => item.id === lessonId) ?? FINANCE_LESSONS[0];
  return <div className={styles.page} data-finance-learning><h1 className={styles.heading}>{zh ? "学习中心" : "Learning center"}</h1><div className={styles.columns}><div className={styles.list}>{FINANCE_LESSONS.map((item) => <VButton key={item.id} variant="secondary" className={[styles.listItem, lessonId === item.id ? styles.selected : ""].join(" ")} onPress={() => { setLessonId(item.id); setAnswer(null); }}>{item.title}</VButton>)}</div><VSurface className={styles.card}><h2 className={styles.title}>{lesson.title}</h2><p className={styles.text}>{lesson.body}</p><strong className={styles.title}>{lesson.question}</strong>{lesson.options.map((option, index) => <VButton key={option} variant="secondary" className={[styles.example, answer === index ? styles.selected : ""].join(" ")} aria-pressed={answer === index} onPress={() => setAnswer(index)}>{option}</VButton>)}{answer !== null ? <p role="status" className={answer === lesson.correct ? styles.success : styles.warning}>{answer === lesson.correct ? "回答正确。" : "再核对一下。"}{lesson.explanation}</p> : null}<VButton onPress={() => onResearchPrompt(`请以 ${stock.name}（${stock.ticker}）为例，带我练习：${lesson.exercise}。只使用可核对的真实数据与来源。`)}>{zh ? "用当前股票练习" : "Practice with selected stock"}</VButton></VSurface></div><h2 className={styles.title}>{zh ? "研究指南" : "Research guides"}</h2><div className={styles.examples}>{FINANCE_GUIDES.map((guide) => <VButton key={guide.id} variant="secondary" className={styles.example} onPress={() => onResearchPrompt(`请以 ${stock.name}（${stock.ticker}）为例，${guide.prompt}。`) }>{guide.title}</VButton>)}</div></div>;
}
