// Deterministic presentation data only. No operator config, private memories, credentials or live records.
import type { KnowledgeRagRetrievalPayload, KnowledgeSearchPayload, MemoryItem, MemoryOverview, MemoryUsageContractPayload, SkillLibraryPayload } from "../../src/api/types";
const updatedAt = "2026-10-14T08:00:00Z";
const skills: SkillLibraryPayload = {
  schemaVersion: 1, mode: "read_only", roots: [{path:"C:/preview/skills",source:"agents",exists:true}],
  counts: {total:6,codex:2,agents:3,other:1},
  skills: [
    ["代码审查", "code-review", "agents", "检查改动的正确性、边界和回归风险。"],
    ["前端设计", "frontend-design", "codex", "沿用公共设计系统，检查层级、交互与响应式布局。"],
    ["文档整理", "documents", "agents", "整理来源与文档内容，保留可核对的引用。"],
    ["运行诊断", "runtime-review", "agents", "核对运行实例、服务健康和实际版本。"],
    ["数据分析", "data-analysis", "codex", "读取数据并生成可复核的分析结果。"],
    ["团队协作", "team-work", "other", "帮助团队分工与记录进展。"],
  ].map(([name,command,source,description]) => ({ name,command,source,description,aliases:[],rootPath:"C:/preview/skills",path:`C:/preview/skills/${command}/SKILL.md`,directoryName:command,hash:"preview-hash",contentLength:200,preview:`# ${name}\n\n${description}\n\n## 工作流程\n\n1. 阅读当前任务与已有实现。\n2. 核对边界，保留原有内容。\n3. 执行必要验证并记录结果。\n\n所有内容均为隔离验收样例，不对应真实技能文件。`,previewTruncated:false })),
};
const categoryNames = ["项目记忆","运行时记忆","会话记忆","团队知识库","开源项目索引"];
function item(section: number,index: number): MemoryItem {
  return {id:`item-${section}-${index}`,title:["工作台使用约定","设计与交互规则","验证记录"][index],kind:"markdown",source:"preview",path:`C:/preview/memory/${section}/${index}.md`,updatedAt,agentVisible:true,inPrompt:false,visibilityClass:"agent_visible",channels:["explicit_read"],usedBy:["Preview Agent"],summary:"隔离验收样例。保留已有任务内容与来源记录。",content:"这是一条用于界面验收的样例记忆。\n\n界面使用统一的灰色侧栏和白色内容面板，来源、状态与正文保持清晰的层级。\n\n- 保留原有查询与权限语义\n- 通过公共组件展示内容\n- 在正式实例刷新后验收真实页面",contentType:"markdown",contentTruncated:false,exists:true,managedState:{editable:true,deletable:true,restorable:false,disabled:false,userManaged:true,overridden:false,actionHint:""}};
}
const overview: MemoryOverview = {schemaVersion:1,generatedAt:updatedAt,projectRoot:"C:/preview",summary:{sectionCount:5,itemCount:15,agentVisibleCount:15,runtimeInjectedCount:0,warnings:[]},sections:categoryNames.map((title,index)=>({id:`section-${index}`,title,sourceKind:"preview",visibility:"agent_visible",agentVisibility:"explicit_read",sourcePath:"C:/preview/memory",sourceApi:"",updatedAt,summary:"安全样例",items:[0,1,2].map(i=>item(index,i))}))};
const inventoryAgents = ["代码助手","研究助手","文档助手"].map((displayName,index)=>({agentId:`preview-agent-${index}`,agentCode:`A00${index+1}`,displayName,status:"idle",primaryMode:"chat",hasPrivateMemory:index<2,workspacePath:`C:/preview/agents/${index}`,privateMemoryRoot:`C:/preview/agents/${index}/memory`,fileCount:index<2?2:0,knowledgeSummary:{knowledgeBaseCount:0,itemCount:0,knowledgeBases:[]},items:index<2?[0,1].map(i=>({id:`private-${index}-${i}`,relativePath:`${i?"context":"preferences"}.md`,title:i?"工作上下文":"稳定偏好",updatedAt,path:`C:/preview/agents/${index}/memory/${i}.md`,summary:"隔离样例记忆",sizeBytes:256,revision:"sample-v1",contentType:"markdown",contentTruncated:false,content:"# 稳定偏好\n\n本页仅使用安全样例展示记忆阅读体验。\n\n- 先说明结果\n- 保留来源与证据\n- 使用统一页面组件"})):[]}));
const inventory = {agents:inventoryAgents,generatedAt:updatedAt,summary:{agentCount:3,privateFileCount:4,privateByteCount:1024,formalKnowledgeItemCount:0,formalKnowledgeBaseCount:0,warningCount:0,warnings:[]}};
const agents = inventoryAgents.map(a=>({agentId:a.agentId,agentCode:a.agentCode,displayName:a.displayName,status:a.status,kind:"chat",primaryMode:"chat",origin:"preview",toolPolicy:{allowedTools:[],preferredTools:[],blockedTools:[]}}));
const base = {knowledgeBaseId:"preview-kb",scopedKnowledgeBaseId:"preview-kb",teamId:"preview-team",teamName:"示例团队",name:"设计与研发知识库",description:"团队共享的正式知识",status:"active",acl:{},createdAt:updatedAt,updatedAt,stats:{sourceArtifactCount:0,pendingProposalCount:0,proposalCount:0,itemCount:1,batchCount:0},pendingProposals:[],permissions:{canRead:true,canPropose:false,canReview:false,canRate:false}};
const knowledgeItem = {knowledgeItemId:"preview-knowledge",teamId:"preview-team",knowledgeBaseId:"preview-kb",batchId:"",sourceArtifactIds:[],centralSourceIds:[],title:"统一工作台设计规则",summary:"统一侧栏、面板与交互反馈。",content:"灰色侧栏承载导航，白色圆角面板承载正文。相同角色的控件复用同一组设计 token。",tags:["设计"],importanceLevel:"normal",confidence:0.9,stability:"stable",scope:"team",reviewPriority:"normal",createdAt:updatedAt,updatedAt,reviewedAt:updatedAt,appliedAt:updatedAt,reviewedByAgentId:"preview-agent-0",markedBy:"",markedAt:"",markingReason:"",knowledgeState:"active",revision:1,contentSha256:"preview"};
export const workspaceFixtures: Record<string,unknown> = {
  "/api/config/public": {language:"zh"},
  "/api/control-token": {header:"X-Vibelution-Control-Token",controlToken:"isolated-workspace-preview"},
  "/api/skills": skills,
  "/api/agents": agents,
  "/api/memory/overview": overview,
  "/api/memory/agents": inventory,
  "/api/memory/knowledge-graph": {schemaVersion:1,mode:"read_only_project_memory_graph",agentId:"preview-agent-0",summary:{nodeCount:3,edgeCount:2,truncated:false,nodeTypeCounts:{agent_private_memory:3},edgeTypeCounts:{related:2},elapsedMs:1},nodes:["工作台规则","设计记录","验证记录"].map((label,index)=>({id:`preview-node-${index}`,type:"agent_private_memory",label,summary:"安全样例图谱节点",status:"active",createdAt:updatedAt,updatedAt,metadata:{},responsibilityQuestion:"",visual:{},childNodeIds:[],contentItems:[]})),edges:[0,1].map(i=>({id:`preview-edge-${i}`,source:`preview-node-${i}`,target:`preview-node-${i+1}`,type:"related",label:"相关",weight:1,metadata:{}})),filters:{include:["privateMemory"]},operatingBoundary:{readOnly:true,gpuPreferred:true,layoutWorker:true,honorsKnowledgeAcl:true,fullContentIncluded:false,canEditGraph:false,canApplyKnowledge:false}},
  "/api/memory/usage-contract": {schemaVersion:1,generatedAt:updatedAt,projectRoot:"C:/preview",principles:[],domains:[],flow:[],forbiddenActions:[],runtimeAccess:{summaryInPromptAllowed:false,knowledgeBodiesInPromptByDefault:false,explicitReadChannels:[],agentToolBoundary:{}},currentState:{knowledge:{},operationsHealth:{},governancePlan:{},operatingBoundary:{}}} satisfies MemoryUsageContractPayload,
  "/api/memory/github-projects": {schemaVersion:1,root:"C:/preview/references",indexPath:"",registryPath:"",reposPath:"",summary:{projectCount:2,readyCount:2,archivedCount:0,maxProjects:100,maxRepoSizeKb:1000},projects:[{projectId:"shadcn",name:"shadcn/ui",fullName:"shadcn-ui/ui",status:"ready",license:"MIT",description:"公共组件与一致的交互模式。"},{projectId:"opencode",name:"OpenCode",fullName:"anomalyco/opencode",status:"ready",license:"MIT",description:"Agent 工作台与会话界面参考。"}],updatedAt},
  "/api/knowledge/dashboard-snapshot": {schemaVersion:1,agentId:"preview-agent-0",overview:{schemaVersion:1,agentId:"preview-agent-0",summary:{knowledgeBaseCount:1,pendingProposalCount:0,itemCount:1,sourceArtifactCount:0},knowledgeBases:[base],updatedAt},steward:null,recommendations:{recommendations:[],operatingBoundary:{recommendationsOnly:true}},workbench:null,operationsHealth:null,governancePlan:null,updatedAt},
  "/api/knowledge-bases/preview-kb/items": {schemaVersion:1,knowledgeBase:base,items:[knowledgeItem],summary:{itemCount:1},updatedAt},
  "/api/knowledge-bases/preview-kb/rating-suggestions": {suggestions:[],summary:{pendingSuggestionCount:0}},
  "/api/knowledge/permissions/audit": {schemaVersion:1,agentId:"preview-agent-0",tools:{},knowledgeBases:[],summary:{knowledgeBaseCount:1},updatedAt},
  "/api/knowledge/governance/tasks": {tasks:[],summary:{taskCount:0,openTaskCount:0,proposalReviewCount:0,ratingReviewCount:0,sourceNeedsProposalCount:0}},
  "/api/knowledge/ingestion-adapters": {adapters:[]},
  "/api/knowledge/sources/inbox": {sources:[],summary:{sourceCount:0}},
  "/api/knowledge/sources/registry": {sources:[],summary:{sourceCount:0}},
  "/api/knowledge/search": {schemaVersion:1,agentId:"preview-agent-0",filters:{},results:[],summary:{resultCount:0,scannedKnowledgeBaseCount:1},updatedAt} satisfies KnowledgeSearchPayload,
  "/api/knowledge/rag/health": {status:"ready",available:true,providers:[{provider:"local",status:"ready",available:true}],retrievalPolicy:{}},
  "/api/knowledge/semantic-index/health": {status:"ready",indexedItemCount:1,indexableItemCount:1},
  "/api/knowledge/rag/retrieve": {schemaVersion:1,agentId:"preview-agent-0",request:{queryLength:0,teamId:"preview-team",knowledgeBaseId:"preview-kb",tags:[],retrievalMode:"hybrid",provider:"local",topK:5,maxContextChars:4000},summary:{candidateCount:0,contextCount:0,citationCount:0,scannedKnowledgeBaseCount:1},contexts:[],citations:[],retrievalPolicy:{provider:"local",injectsPromptByDefault:false,honorsKnowledgeAcl:true,honorsMemoryPolicy:true,mutatesFormalKnowledge:false},updatedAt} satisfies KnowledgeRagRetrievalPayload,
  "/api/user-content/markdown-spaces": {spaces:[],summary:{spaceCount:0,pageCount:0}},
};
for (const skill of skills.skills) workspaceFixtures[`/api/skills/${skill.command}`] = {...skill,content:skill.preview,contentTruncated:false};
for (const agent of inventoryAgents) workspaceFixtures[`/api/memory/agents/${agent.agentId}`] = {...inventory,selectedAgent:agent};
for (const section of overview.sections) for(const memoryItem of section.items) workspaceFixtures[`/api/memory/items/${section.id}/${memoryItem.id}`]={schemaVersion:1,generatedAt:updatedAt,sectionId:section.id,item:memoryItem};
