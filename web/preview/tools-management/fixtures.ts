export type Mode = "inherited" | "allowed" | "blocked";
export type Tool = { name: string; summary: string; bundle: string; risk: "低风险" | "中风险" | "高风险"; source: "内置" | "生成"; llm: boolean; safeTest: boolean; args: Record<string, unknown> };
export const bundles = ["团队协作工具包", "代码修改包", "会话 Agent 基础包", "记忆平台工具包", "科研工具包", "媒体生成工具包", "挑战杯迭代账本包", "挑战杯实验账本包", "行情与财报研究包", "虚拟人生活工具包", "运维诊断工具包", "知识库管理员审核包", "资料搜集阶段包", "未归入工具包"];
// Real identifiers from the current page/source; statuses and permissions are deterministic examples.
export const tools: Tool[] = [
  {name:"agent_archive_tool",summary:"归档一个 Agent（非删除），走完整 archive lifecycle。受保护 Agent 或有关联中的 Session 时会失败。",bundle:bundles[0],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{agent_id:{type:"string",description:"要归档的 Agent ID"}}},
  {name:"financial_report_query_tool",summary:"查询财报资料与研究记录。",bundle:bundles[8],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{query:{type:"string"}}},
  {name:"financial_evidence_search_tool",summary:"检索金融研究的来源与证据。",bundle:bundles[8],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{query:{type:"string"}}},
  {name:"financial_evidence_stage_tool",summary:"将研究证据提交到暂存阶段。",bundle:bundles[8],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{evidence_id:{type:"string"}}},
  {name:"financial_evidence_withdraw_tool",summary:"撤回已暂存的研究证据。",bundle:bundles[8],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{evidence_id:{type:"string"}}},
  {name:"financial_market_snapshot_tool",summary:"读取行情快照。",bundle:bundles[8],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{symbol:{type:"string"}}},
  {name:"financial_market_screen_tool",summary:"按研究条件筛选市场数据。",bundle:bundles[8],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{criteria:{type:"object"}}},
  {name:"financial_index_context_tool",summary:"查看指数及市场背景。",bundle:bundles[8],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{index:{type:"string"}}},
  {name:"virtual_human_status_tool",summary:"查看虚拟人的当前状态。",bundle:bundles[9],risk:"低风险",source:"内置",llm:true,safeTest:true,args:{action:{type:"string",default:"status"}}},
  {name:"virtual_human_schedule_tool",summary:"查看和管理虚拟人的日程。",bundle:bundles[9],risk:"低风险",source:"内置",llm:true,safeTest:true,args:{action:{type:"string",default:"list"}}},
  {name:"virtual_human_activity_tool",summary:"记录虚拟人的生活活动。",bundle:bundles[9],risk:"中风险",source:"内置",llm:true,safeTest:false,args:{action:{type:"string"}}},
  {name:"virtual_human_diary_tool",summary:"查看和记录虚拟人的日记。",bundle:bundles[9],risk:"中风险",source:"内置",llm:true,safeTest:false,args:{action:{type:"string"}}},
  {name:"image2",summary:"使用配置的图像模型生成与编辑图片。",bundle:bundles[5],risk:"高风险",source:"内置",llm:true,safeTest:false,args:{prompt:{type:"string"}}},
  {name:"web_search_tool",summary:"搜索网页并返回来源。",bundle:bundles[12],risk:"中风险",source:"内置",llm:true,safeTest:false,args:{query:{type:"string"}}},
  {name:"generated_summary_example",summary:"生成工具示例，用于检查启用、停用与批量操作的布局。",bundle:bundles[13],risk:"低风险",source:"生成",llm:true,safeTest:true,args:{text:{type:"string"}}},
];
export const agents = [{value:"a110",label:"A110 · 洛天依的自主行动"},{value:"research",label:"研究助手"},{value:"long",label:"Agent · 长名称示例：资料搜集与研究证据审核助手"}];
export const initialModes: Record<string, Mode> = {virtual_human_status_tool:"allowed",virtual_human_schedule_tool:"allowed",virtual_human_activity_tool:"allowed",virtual_human_diary_tool:"allowed"};
