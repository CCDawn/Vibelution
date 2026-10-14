// 隔离交互预览的静态演示数据；不读取真实知识、财务或实验内容。

export type TopicId = 'finance' | 'engineering' | 'ai';
export type NodeKind = 'knowledge' | 'concept' | 'source' | 'conclusion' | 'agent' | 'team' | 'experiment';
export type RelationLayer = 'knowledge' | 'ownership' | 'evidence';

export interface Topic {
  id: TopicId;
  label: string;
  description: string;
  color: number;
  position: [number, number, number];
}

export interface GraphNode {
  id: string;
  topic: TopicId;
  kind: NodeKind;
  label: string;
  summary: string;
  owner: string;
  access: 'readable' | 'restricted';
}

export interface GraphEvidence {
  id: string;
  label: string;
  location: string;
  version: string;
  excerpt: string;
  accessible: boolean;
}

export interface GraphRelation {
  id: string;
  source: string;
  target: string;
  label: string;
  layer: RelationLayer;
  status: 'confirmed' | 'candidate';
  reason: string;
  evidenceIds: string[];
}

export const topics: Topic[] = [
  {
    id: 'finance',
    label: '财报与价值研究',
    description: '隔离演示主题：展示研究知识、概念、来源与结论之间的关系。',
    color: 0x83c7ae,
    position: [-6, 3, 0],
  },
  {
    id: 'engineering',
    label: '软件工程',
    description: '隔离演示主题：展示团队归属、工程知识与证据链。',
    color: 0x79b8ec,
    position: [0, -3, 3],
  },
  {
    id: 'ai',
    label: 'AI研究',
    description: '隔离演示主题：展示研究方法、实验计划与跨主题候选关系。',
    color: 0xad9bf0,
    position: [6, 3, -2],
  },
];

export const nodes: GraphNode[] = [
  {
    id: 'n-finance-team', topic: 'finance', kind: 'team', label: '演示研究小组',
    summary: '仅用于展示团队与Agent的归属关系。', owner: '演示组织', access: 'readable',
  },
  {
    id: 'n-finance-agent', topic: 'finance', kind: 'agent', label: '演示研究Agent',
    summary: '静态演示角色；不连接真实Agent或会话。', owner: '演示研究小组', access: 'readable',
  },
  {
    id: 'n-finance-reading', topic: 'finance', kind: 'knowledge', label: '研究口径记录卡',
    summary: '演示知识条目：先写清问题、假设与比较口径。', owner: '演示研究Agent', access: 'readable',
  },
  {
    id: 'n-finance-scenarios', topic: 'finance', kind: 'knowledge', label: '情景拆解卡',
    summary: '演示知识条目：用定性情景描述不确定因素，不含公司或财务数值。', owner: '演示研究Agent', access: 'readable',
  },
  {
    id: 'n-finance-scenario-concept', topic: 'finance', kind: 'concept', label: '情景范围',
    summary: '演示概念：用若干定性情景表达可能的边界。', owner: '演示研究小组', access: 'readable',
  },
  {
    id: 'n-finance-source-method', topic: 'finance', kind: 'source', label: '演示材料：研究方法卡',
    summary: '合成来源占位，仅包含明确标记为示例的文本。', owner: '演示研究小组', access: 'readable',
  },
  {
    id: 'n-finance-source-restricted', topic: 'finance', kind: 'source', label: '演示材料：受限来源占位项',
    summary: '权限边界演示节点；没有真实私有内容，来源不可读取。', owner: '演示研究小组', access: 'restricted',
  },
  {
    id: 'n-finance-conclusion', topic: 'finance', kind: 'conclusion', label: '演示结论：先核对研究口径',
    summary: '仅展示结论节点的表达方式，不构成投资判断或真实研究结果。', owner: '演示研究Agent', access: 'readable',
  },
  {
    id: 'n-finance-experiment', topic: 'finance', kind: 'experiment', label: '演示流程：情景对照练习',
    summary: '流程占位，不含真实数据、测量值或实验结果。', owner: '演示研究Agent', access: 'readable',
  },

  {
    id: 'n-engineering-team', topic: 'engineering', kind: 'team', label: '演示工程小组',
    summary: '仅用于展示团队与Agent的归属关系。', owner: '演示组织', access: 'readable',
  },
  {
    id: 'n-engineering-agent', topic: 'engineering', kind: 'agent', label: '演示工程Agent',
    summary: '静态演示角色；不连接真实Agent或会话。', owner: '演示工程小组', access: 'readable',
  },
  {
    id: 'n-engineering-observability', topic: 'engineering', kind: 'knowledge', label: '可观测性记录卡',
    summary: '演示知识条目：记录事件、上下文与可追溯线索。', owner: '演示工程Agent', access: 'readable',
  },
  {
    id: 'n-engineering-change-safety', topic: 'engineering', kind: 'knowledge', label: '变更回看卡',
    summary: '演示知识条目：说明如何回看变更影响与恢复路径。', owner: '演示工程Agent', access: 'readable',
  },
  {
    id: 'n-engineering-trace-concept', topic: 'engineering', kind: 'concept', label: '可追溯性',
    summary: '演示概念：让过程记录能关联到对应的输入与动作。', owner: '演示工程小组', access: 'readable',
  },
  {
    id: 'n-engineering-source-playbook', topic: 'engineering', kind: 'source', label: '演示材料：工程记录指南',
    summary: '合成来源占位，仅包含明确标记为示例的文本。', owner: '演示工程小组', access: 'readable',
  },
  {
    id: 'n-engineering-conclusion', topic: 'engineering', kind: 'conclusion', label: '演示结论：记录链路应可追溯',
    summary: '仅展示结论节点的表达方式，不代表真实系统审查结果。', owner: '演示工程Agent', access: 'readable',
  },
  {
    id: 'n-engineering-experiment', topic: 'engineering', kind: 'experiment', label: '演示流程：事件关联练习',
    summary: '流程占位，不含实际运行、测量或实验结果。', owner: '演示工程Agent', access: 'readable',
  },

  {
    id: 'n-ai-team', topic: 'ai', kind: 'team', label: '演示AI研究小组',
    summary: '仅用于展示团队与Agent的归属关系。', owner: '演示组织', access: 'readable',
  },
  {
    id: 'n-ai-agent', topic: 'ai', kind: 'agent', label: '演示AI研究Agent',
    summary: '静态演示角色；不连接真实Agent或会话。', owner: '演示AI研究小组', access: 'readable',
  },
  {
    id: 'n-ai-protocol', topic: 'ai', kind: 'knowledge', label: '实验记录协议卡',
    summary: '演示知识条目：预先说明观察目标、步骤与记录字段。', owner: '演示AI研究Agent', access: 'readable',
  },
  {
    id: 'n-ai-uncertainty', topic: 'ai', kind: 'knowledge', label: '不确定性说明卡',
    summary: '演示知识条目：保留未知项和解释边界，不填写虚构结果。', owner: '演示AI研究Agent', access: 'readable',
  },
  {
    id: 'n-ai-calibration-concept', topic: 'ai', kind: 'concept', label: '不确定性校准',
    summary: '演示概念：比较表达的置信程度与证据支持程度。', owner: '演示AI研究小组', access: 'readable',
  },
  {
    id: 'n-ai-source-method', topic: 'ai', kind: 'source', label: '演示材料：研究设计卡',
    summary: '合成来源占位，仅包含明确标记为示例的文本。', owner: '演示AI研究小组', access: 'readable',
  },
  {
    id: 'n-ai-conclusion', topic: 'ai', kind: 'conclusion', label: '演示结论：计划与结果分开记录',
    summary: '仅展示结论节点的表达方式，不表示方法已验证或实验已完成。', owner: '演示AI研究Agent', access: 'readable',
  },
  {
    id: 'n-ai-experiment', topic: 'ai', kind: 'experiment', label: '演示计划：校准观察练习',
    summary: '未执行的流程占位，不含模型输出、测量值或实验结果。', owner: '演示AI研究Agent', access: 'readable',
  },
];

export const evidence: GraphEvidence[] = [
  {
    id: 'ev-finance-method',
    label: '演示材料：研究方法卡摘录',
    location: '隔离演示材料 / finance-method-demo',
    version: 'demo-v1',
    excerpt: '示例文本不对应真实原文：先记录研究问题和比较口径，再用定性情景整理未知项。',
    accessible: true,
  },
  {
    id: 'ev-finance-restricted',
    label: '演示材料：不可读来源占位项',
    location: '隔离演示材料 / restricted-placeholder',
    version: 'demo-v1',
    excerpt: '示例文本不对应真实原文：该条目仅演示不可读状态，不包含来源正文。',
    accessible: false,
  },
  {
    id: 'ev-engineering-playbook',
    label: '演示材料：工程记录指南摘录',
    location: '隔离演示材料 / engineering-playbook-demo',
    version: 'demo-v1',
    excerpt: '示例文本不对应真实原文：为关键事件保留输入、动作与结果之间的关联线索。',
    accessible: true,
  },
  {
    id: 'ev-ai-method',
    label: '演示材料：研究设计卡摘录',
    location: '隔离演示材料 / ai-method-demo',
    version: 'demo-v1',
    excerpt: '示例文本不对应真实原文：在研究开始前列出观察目标、记录步骤和未知项。',
    accessible: true,
  },
  {
    id: 'ev-ai-experiment',
    label: '演示材料：实验计划摘录',
    location: '隔离演示材料 / ai-experiment-demo',
    version: 'demo-v1',
    excerpt: '示例文本不对应真实原文：计划中的观察字段只用于说明记录结构，不表示已有实验结果。',
    accessible: true,
  },
];

export const relations: GraphRelation[] = [
  {
    id: 'r-finance-team-agent', source: 'n-finance-team', target: 'n-finance-agent', label: '包含',
    layer: 'ownership', status: 'confirmed', reason: '演示研究小组包含演示研究Agent，用于展示组织归属方向。', evidenceIds: [],
  },
  {
    id: 'r-finance-agent-reading', source: 'n-finance-agent', target: 'n-finance-reading', label: '负责',
    layer: 'ownership', status: 'confirmed', reason: '演示研究Agent负责维护研究口径记录卡。', evidenceIds: [],
  },
  {
    id: 'r-finance-agent-conclusion', source: 'n-finance-agent', target: 'n-finance-conclusion', label: '产出',
    layer: 'ownership', status: 'confirmed', reason: '演示研究Agent产出演示结论节点。', evidenceIds: [],
  },
  {
    id: 'r-finance-agent-experiment', source: 'n-finance-agent', target: 'n-finance-experiment', label: '产出',
    layer: 'ownership', status: 'confirmed', reason: '演示研究Agent产出流程占位节点，不表示执行过实验。', evidenceIds: [],
  },
  {
    id: 'r-finance-reading-scenarios', source: 'n-finance-reading', target: 'n-finance-scenarios', label: '引用',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的研究口径记录卡引用情景拆解卡作为补充说明。', evidenceIds: ['ev-finance-method'],
  },
  {
    id: 'r-finance-scenarios-concept', source: 'n-finance-scenarios', target: 'n-finance-scenario-concept', label: '解释',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的情景拆解卡解释情景范围这一概念。', evidenceIds: ['ev-finance-method'],
  },
  {
    id: 'r-finance-concept-conclusion', source: 'n-finance-scenario-concept', target: 'n-finance-conclusion', label: '支持',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的情景范围概念支持先核对研究口径这一演示结论。', evidenceIds: ['ev-finance-method'],
  },
  {
    id: 'r-finance-reading-source', source: 'n-finance-reading', target: 'n-finance-source-method', label: '证据来自',
    layer: 'evidence', status: 'confirmed', reason: '隔离演示中的研究口径记录卡证据来自研究方法卡合成摘录。', evidenceIds: ['ev-finance-method'],
  },
  {
    id: 'r-finance-conclusion-source', source: 'n-finance-conclusion', target: 'n-finance-source-method', label: '依据来自',
    layer: 'evidence', status: 'confirmed', reason: '隔离演示中的研究口径结论依据来自研究方法卡合成摘录。', evidenceIds: ['ev-finance-method'],
  },
  {
    id: 'r-finance-conclusion-restricted', source: 'n-finance-conclusion', target: 'n-finance-source-restricted', label: '依据来自',
    layer: 'evidence', status: 'candidate',
    reason: '该连线只用于展示受限来源边界；来源不可访问，因此关系仍待确认，不能用于核验结论。',
    evidenceIds: ['ev-finance-restricted'],
  },

  {
    id: 'r-engineering-team-agent', source: 'n-engineering-team', target: 'n-engineering-agent', label: '包含',
    layer: 'ownership', status: 'confirmed', reason: '演示工程小组包含演示工程Agent，用于展示组织归属方向。', evidenceIds: [],
  },
  {
    id: 'r-engineering-agent-knowledge', source: 'n-engineering-agent', target: 'n-engineering-observability', label: '负责',
    layer: 'ownership', status: 'confirmed', reason: '演示工程Agent负责维护可观测性记录卡。', evidenceIds: [],
  },
  {
    id: 'r-engineering-agent-conclusion', source: 'n-engineering-agent', target: 'n-engineering-conclusion', label: '产出',
    layer: 'ownership', status: 'confirmed', reason: '演示工程Agent产出演示结论节点。', evidenceIds: [],
  },
  {
    id: 'r-engineering-agent-experiment', source: 'n-engineering-agent', target: 'n-engineering-experiment', label: '产出',
    layer: 'ownership', status: 'confirmed', reason: '演示工程Agent产出流程占位节点，不表示实际运行过练习。', evidenceIds: [],
  },
  {
    id: 'r-engineering-knowledge-change', source: 'n-engineering-observability', target: 'n-engineering-change-safety', label: '引用',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的可观测性记录卡引用变更回看卡作为补充说明。', evidenceIds: ['ev-engineering-playbook'],
  },
  {
    id: 'r-engineering-change-concept', source: 'n-engineering-change-safety', target: 'n-engineering-trace-concept', label: '解释',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的变更回看卡解释可追溯性这一概念。', evidenceIds: ['ev-engineering-playbook'],
  },
  {
    id: 'r-engineering-concept-conclusion', source: 'n-engineering-trace-concept', target: 'n-engineering-conclusion', label: '支持',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的可追溯性概念支持记录链路应可追溯这一演示结论。', evidenceIds: ['ev-engineering-playbook'],
  },
  {
    id: 'r-engineering-knowledge-source', source: 'n-engineering-observability', target: 'n-engineering-source-playbook', label: '证据来自',
    layer: 'evidence', status: 'confirmed', reason: '隔离演示中的可观测性记录卡证据来自工程记录指南合成摘录。', evidenceIds: ['ev-engineering-playbook'],
  },
  {
    id: 'r-engineering-conclusion-source', source: 'n-engineering-conclusion', target: 'n-engineering-source-playbook', label: '依据来自',
    layer: 'evidence', status: 'confirmed', reason: '隔离演示中的可追溯性结论依据来自工程记录指南合成摘录。', evidenceIds: ['ev-engineering-playbook'],
  },

  {
    id: 'r-ai-team-agent', source: 'n-ai-team', target: 'n-ai-agent', label: '包含',
    layer: 'ownership', status: 'confirmed', reason: '演示AI研究小组包含演示AI研究Agent，用于展示组织归属方向。', evidenceIds: [],
  },
  {
    id: 'r-ai-agent-knowledge', source: 'n-ai-agent', target: 'n-ai-protocol', label: '负责',
    layer: 'ownership', status: 'confirmed', reason: '演示AI研究Agent负责维护实验记录协议卡。', evidenceIds: [],
  },
  {
    id: 'r-ai-agent-conclusion', source: 'n-ai-agent', target: 'n-ai-conclusion', label: '产出',
    layer: 'ownership', status: 'confirmed', reason: '演示AI研究Agent产出演示结论节点。', evidenceIds: [],
  },
  {
    id: 'r-ai-agent-experiment', source: 'n-ai-agent', target: 'n-ai-experiment', label: '产出',
    layer: 'ownership', status: 'confirmed', reason: '演示AI研究Agent产出未执行的计划占位节点。', evidenceIds: [],
  },
  {
    id: 'r-ai-protocol-uncertainty', source: 'n-ai-protocol', target: 'n-ai-uncertainty', label: '引用',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的实验记录协议卡引用不确定性说明卡作为补充说明。', evidenceIds: ['ev-ai-method'],
  },
  {
    id: 'r-ai-uncertainty-concept', source: 'n-ai-uncertainty', target: 'n-ai-calibration-concept', label: '解释',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的不确定性说明卡解释不确定性校准这一概念。', evidenceIds: ['ev-ai-method'],
  },
  {
    id: 'r-ai-concept-conclusion', source: 'n-ai-calibration-concept', target: 'n-ai-conclusion', label: '支持',
    layer: 'knowledge', status: 'confirmed', reason: '隔离演示中的不确定性校准概念支持计划与结果分开记录这一演示结论。', evidenceIds: ['ev-ai-method'],
  },
  {
    id: 'r-ai-knowledge-source', source: 'n-ai-protocol', target: 'n-ai-source-method', label: '证据来自',
    layer: 'evidence', status: 'confirmed', reason: '隔离演示中的实验记录协议卡证据来自研究设计卡合成摘录。', evidenceIds: ['ev-ai-method'],
  },
  {
    id: 'r-ai-conclusion-source', source: 'n-ai-conclusion', target: 'n-ai-source-method', label: '依据来自',
    layer: 'evidence', status: 'confirmed', reason: '隔离演示中的计划与结果区分结论依据来自研究设计卡合成摘录。', evidenceIds: ['ev-ai-method'],
  },
  {
    id: 'r-ai-experiment-source', source: 'n-ai-experiment', target: 'n-ai-source-method', label: '依据来自',
    layer: 'evidence', status: 'confirmed', reason: '隔离演示中的校准观察计划依据来自研究设计卡合成摘录；该关系不表示实验已执行。', evidenceIds: ['ev-ai-experiment'],
  },

  {
    id: 'r-cross-engineering-ai', source: 'n-engineering-trace-concept', target: 'n-ai-experiment', label: '提供记录方法参照',
    layer: 'knowledge', status: 'confirmed',
    reason: '本隔离演示图将软件工程的可追溯性概念作为AI实验记录流程的示例参照；此确认只表示演示数据内部的连线，不代表真实平台事实。',
    evidenceIds: ['ev-engineering-playbook', 'ev-ai-experiment'],
  },
  {
    id: 'r-cross-finance-ai-candidate', source: 'n-finance-scenario-concept', target: 'n-ai-calibration-concept', label: '可能相关',
    layer: 'knowledge', status: 'candidate',
    reason: '两个演示概念都涉及不确定性的表达；跨主题语义映射尚待人工确认，目前只保留为关系候选。',
    evidenceIds: ['ev-finance-method', 'ev-ai-method'],
  },
];
