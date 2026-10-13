import { useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { VuiProvider, VButton } from "../../src/components/vui";
import { AgentCoreConfigPanel, type AgentConfigDraft, type AgentCoreConfigLlmSlotView } from "../../src/routes/AgentCoreConfigPanel";
import { AgentPersonaProfilePanel, type AgentPersonaDraft } from "../../src/routes/AgentPersonaProfilePanel";
import { AgentTaskProfilePanel, type AgentTaskDraft } from "../../src/routes/AgentTaskProfilePanel";
import { AgentRuntimePolicyPanel } from "../../src/routes/AgentRuntimePolicyPanel";
import { AgentMemoryPolicyPanel, type AgentMemoryPolicyDraft } from "../../src/routes/AgentMemoryPolicyPanel";
import { agentsRouteCopy } from "../../src/routes/agents/agentsRouteCopy";
import { mergeAgentConfigDraftGroup, sameAgentConfigDraftGroup } from "../../src/routes/agents/agentRouteConfigGroupDraft";
import { FALLBACK_AGENT_LLM_SLOTS } from "../../src/routes/agents/agentRouteLlmModel";
import type { AgentModelChoice, AgentDelegationPolicy, AgentSupervisionPolicy } from "../../src/api/types";
import { initial } from "./fixtures";
import "./preview.css";
import "../../src/design/route-css/agents.tailwind.css";

// Real production components with local fixture state. Never route writes to a backend.
window.fetch = async () => { throw new Error("Production-component fixture has no backend connection"); };
document.documentElement.dataset.theme = "light";
const copy = agentsRouteCopy("zh");
const catalog = [
  { modelRef: "openai/gpt-5.4", label: "GPT-5.4", providerId: "openai", providerLabel: "OpenAI" },
  { modelRef: "anthropic/sonnet-4.6", label: "Claude Sonnet 4.6", providerId: "anthropic", providerLabel: "Anthropic" },
].map(m => ({ ...m, modelId: m.modelRef, modelKey: m.modelRef.split("/")[1], upstreamId: m.modelRef.split("/")[1], model: m.label,
  providerKind:"openai", providerBaseUrl:"https://example.invalid", transport:"responses", source:"pinned", runtimeSelectable:true, availability:"pinned", verificationStatus:"verified", catalogStale:false, providerStatus:"reachable",providerHealthy:true,
  slotCompatibility:Object.fromEntries(["dialogue","mental_model","summary","subagent_planning","subagent_execution","vision"].map(slot=>[slot,{allowed:true,reasonCode:""}])),capabilities:{},apiKeyEnv:"",apiKeyConfigured:true,apiKeyState:"configured",requiresApiKey:false,missingApiKey:false,capabilityStatus:"known",capabilitySource:"fixture",reasoningEffortValues:["low","high"]
} as AgentModelChoice));
const coreInitial: AgentConfigDraft = { displayName:"研究助手",status:"active",permissionPreset:"request_approval",llmBindings:{ dialogue:{modelId:catalog[0].modelRef} },reasoningEffortBySlot:{},promptTemplateId:"research",toolPolicyId:"research-tools",memoryPolicyId:"research-memory",contextCompressionPolicy:{...initial.basic,mode:"inherit"} };
const memoryInitial: AgentMemoryPolicyDraft = {...initial.memory,newReadGroup:"",newWriteGroup:"",newReadKnowledgeBaseId:"",newProposeKnowledgeBaseId:"",newReviewKnowledgeBaseId:"",newRateKnowledgeBaseId:""};
const delegationInitial: AgentDelegationPolicy = {allowSubagents:false,allowWakeMessages:false,allowedContextModes:["isolated"],maxConcurrent:2,maxDepth:1};
const supervisionInitial: AgentSupervisionPolicy = {supervisionEnabled:false,requiresReview:false,reviewMode:"advisory",evidenceLevel:"standard"};

function ProductionPanels() {
  const [active,setActive] = useState("models");
  const [draft,setDraft] = useState(coreInitial), [saved,setSaved] = useState(coreInitial);
  const [persona,setPersona] = useState<AgentPersonaDraft>(initial.persona), [personaSaved,setPersonaSaved] = useState(initial.persona);
  const [task,setTask] = useState<AgentTaskDraft>(initial.task), [taskSaved,setTaskSaved] = useState(initial.task);
  const [memory,setMemory] = useState(memoryInitial), [memorySaved,setMemorySaved] = useState(memoryInitial);
  const [delegation,setDelegation] = useState(delegationInitial), [supervision,setSupervision] = useState(supervisionInitial);
  const [runtimeSaved,setRuntimeSaved] = useState(JSON.stringify([delegationInitial,supervisionInitial]));
  const [notice,setNotice] = useState<{tone:"success";text:string}|null>(null);
  const same = (a:unknown,b:unknown) => JSON.stringify(a)===JSON.stringify(b);
  const dirty = {models:!sameAgentConfigDraftGroup(draft,saved,"models"),basic:!sameAgentConfigDraftGroup(draft,saved,"basic")};
  const slots: AgentCoreConfigLlmSlotView[] = FALLBACK_AGENT_LLM_SLOTS.map(slot=>({slot,selectedModelId:draft.llmBindings[slot.slot]?.modelId||"",candidates:catalog,supportsReasoningEffort:slot.slot==="dialogue",reasoningEffort:draft.reasoningEffortBySlot[slot.slot]||"",reasoningEffortOptions:[{value:"low",label:"低"},{value:"high",label:"高"}]}));
  const done = () => setNotice({tone:"success",text:"已保存（组件验证）"});
  return <div className="flex h-dvh flex-col bg-vui-surface-panel text-vui-fg-primary">
    <header className="border-b border-vui-border-subtle px-10 py-6 max-sm:px-4"><strong className="text-xl font-semibold">研究助手</strong><span className="ml-3 text-xs text-vui-fg-tertiary">正式组件 · 示例</span></header>
    <nav className="flex shrink-0 gap-6 overflow-x-auto border-b border-vui-border-subtle px-10 max-sm:px-4" aria-label="配置分类">{[["models","模型"],["basic","基本"],["persona","人物"],["task","任务"],["memory","工具与记忆"],["runtime","委派与监督"]].map(([id,label])=><VButton key={id} contentLayout="plain" variant="ghost" aria-pressed={active===id} className={`!h-11 !min-h-11 !shrink-0 !rounded-none !border-x-0 !border-t-0 !border-b-2 !px-0 !shadow-none ![background:transparent] ${active===id?"!border-vui-fg-primary":"!border-transparent !text-vui-fg-tertiary"}`} onPress={()=>{setActive(id);setNotice(null);}}>{label}</VButton>)}</nav>
    <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
      {active==="models"||active==="basic" ? <AgentCoreConfigPanel section={active} copy={copy} lang="zh" agentName={saved.displayName} draft={draft} dirty={dirty.models||dirty.basic} groupDirty={dirty} groupCanSave={dirty} configDraftDirty={false} canSave={dirty.models||dirty.basic} pending={false} notice={notice} title="Agent 配置" health={{tone:"ok",label:"正常",headline:"",nextStepLabel:"",nextStep:""}} llmSlots={slots} pendingModelRef="" promptTemplateOptions={[{value:"research",label:"研究任务 · 通用模板"}]} toolPolicyOptions={[{value:"research-tools",label:"研究工具策略"}]} toolPolicyTooltip="" memoryPolicyOptions={[{value:"research-memory",label:"研究助手私有记忆"}]} memoryPolicyTooltip="" contextCompressionTitle="" onDraftChange={patch=>{setDraft(d=>({...d,...patch}));setNotice(null);}} onLlmSlotModelChange={(slot,ref)=>setDraft(d=>({...d,llmBindings:{...d.llmBindings,[slot.slot]:{modelId:ref}}}))} onPromoteModel={()=>{throw new Error("Fixture models are already pinned");}} onReasoningEffortChange={(slot,value)=>setDraft(d=>({...d,reasoningEffortBySlot:{...d.reasoningEffortBySlot,[slot]:value}}))} onContextCompressionChange={patch=>setDraft(d=>({...d,contextCompressionPolicy:{...d.contextCompressionPolicy,...patch}}))} onOpenModelConfig={()=>{}} onOpenPromptConfig={()=>{}} onOpenContextConfig={()=>{}} onReset={()=>setDraft(saved)} onSave={()=>{setSaved(draft);done();}} onResetGroup={group=>setDraft(d=>mergeAgentConfigDraftGroup(d,saved,group))} onSaveGroup={group=>{setSaved(s=>mergeAgentConfigDraftGroup(s,draft,group));done();}}/>:null}
      {active==="persona"?<AgentPersonaProfilePanel copy={copy} lang="zh" summary="" draft={persona} dirty={!same(persona,personaSaved)} canSave={!same(persona,personaSaved)} pending={false} onDraftChange={patch=>setPersona(d=>({...d,...patch}))} onReset={()=>setPersona(personaSaved)} onSave={()=>setPersonaSaved(persona)}/>:null}
      {active==="task"?<AgentTaskProfilePanel copy={copy} lang="zh" summary="" draft={task} dirty={!same(task,taskSaved)} canSave={!same(task,taskSaved)} pending={false} onDraftChange={patch=>setTask(d=>({...d,...patch}))} onReset={()=>setTask(taskSaved)} onSave={()=>setTaskSaved(task)}/>:null}
      {active==="memory"?<AgentMemoryPolicyPanel copy={copy} lang="zh" policyId="research-memory" rootPath="fixture/memory" draft={memory} memoryGroupOptions={["研究团队","项目共享"]} dirty={!same(memory,memorySaved)} pending={false} canSave={!same(memory,memorySaved)} onDraftChange={patch=>setMemory(d=>({...d,...patch}))} onAddMemoryGroup={(field,value)=>setMemory(d=>({...d,[field]:[...new Set([...d[field],value])]}))} onRemoveMemoryGroup={(field,value)=>setMemory(d=>({...d,[field]:d[field].filter(v=>v!==value)}))} onAddKnowledgeBaseId={(field,value)=>setMemory(d=>({...d,[field]:[...new Set([...d[field],value])]}))} onRemoveKnowledgeBaseId={(field,value)=>setMemory(d=>({...d,[field]:d[field].filter(v=>v!==value)}))} onOpenMemoryPage={()=>{}} onReset={()=>setMemory(memorySaved)} onSave={()=>setMemorySaved(memory)}/>:null}
      {active==="runtime"?<AgentRuntimePolicyPanel copy={copy} lang="zh" roleLabel="研究助手" dirtyLabel="未保存" cleanLabel="已保存" isDirty={JSON.stringify([delegation,supervision])!==runtimeSaved} isPending={false} canSave={JSON.stringify([delegation,supervision])!==runtimeSaved} notice={null} delegationPolicyDraft={delegation} supervisionPolicyDraft={supervision} inboxPendingCount={0} groupContextEventCount={0} onUpdateDelegationPolicy={patch=>setDelegation(d=>({...d,...patch}))} onToggleDelegationContextMode={(mode,checked)=>setDelegation(d=>({...d,allowedContextModes:checked?[...new Set([...d.allowedContextModes,mode])]:d.allowedContextModes.filter(v=>v!==mode)}))} onMaxConcurrentChange={value=>setDelegation(d=>({...d,maxConcurrent:Number(value)}))} onMaxDepthChange={value=>setDelegation(d=>({...d,maxDepth:Number(value)}))} onUpdateSupervisionPolicy={patch=>setSupervision(d=>({...d,...patch}))} onReset={()=>{const [d,s]=JSON.parse(runtimeSaved);setDelegation(d);setSupervision(s);}} onSave={()=>setRuntimeSaved(JSON.stringify([delegation,supervision]))}/>:null}
    </main>
  </div>;
}
const root: Root = import.meta.hot?.data.root ?? createRoot(document.getElementById("root")!);
root.render(<VuiProvider><ProductionPanels/></VuiProvider>);
if (import.meta.hot) import.meta.hot.dispose(data => { data.root = root; });
