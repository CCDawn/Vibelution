# 受治理的评估器进化：论文框架笔记

> 工作草案：以 Vibelution 平台两条「评估器的评估」数据管道为核心，写一篇
> 关于「自迭代评估器在统计治理下进化」的论文。本文件沉淀 motivation 与
> measurement 章节框架及真实数据锚点；随实验推进持续更新。

## 1. Motivation

### 1.1 自迭代评估器是当前缺失的一环

自进化 agent 研究已进入爆发期（agentic RL、上下文进化 ACE、技能库、
CoNL 的元评估自博弈），但三个最直接的近邻都把评估器当作训练信号源而
不是被治理对象：

- **CoNL（ICML 2026, arXiv:2601.21464）**：诊断奖励 r_diag 训练评估者，
  但评估器的每次自我更新无准入门；自述「peer 共识不必然对应客观质量」。
- **Self-Taught Evaluators（Meta, arXiv:2408.02666）**：judge 随训练集
  迭代，晋升决策无统计保证，依赖固定 held-out 集（自适应复用风险）。
- **Meta-Evaluation Collapse（OpenReview IF0L7HSs3K）**：理论上证明递归
  元评估收敛到「一致但偏差」——一致性掩盖漂移，唯一硬缓解是人类锚点。

我们的主张：**评估器的进化本身需要一个受治理的准入与度量层**——每次
评估器行为（judge 判定、评审批评）都应对抗可复算的质量证据，而不是
假设迭代等于改进。

### 1.2 我们有两个生产管道提供了第一手证据

Vibelution 是长期运行的多 agent 科研平台，两条评估链路已实弹运行：

1. **监督进化链**（supervised worktree loop）：Judge 按冻结 rubric 双评
   （基线/候选），独立审批 Agent 终审，受控合入。历史 79 轮运行。
2. **假说评审链**（hypothesis rounds）：七维 ordinal 审计 + 五维数值
   评分，评审批评驱动修订循环。

### 1.3 三个实证锚点（已核实）

- **治理门语义实证**：同一 Judge 在证据可见性恢复前后对同类工作评分
  11.25 → 99（swte-38cfc2b63358 vs swte-edc63421f8d9；根因是证据包
  零轨迹，Judge 的「缺证判罚」本身正确）——评估器质量度量的前提是
  证据链完整性，而非评分口径。
- **维度异质性**：诊断奖励归因显示修订循环对 competitionFit
  （meanΔ+0.1175）与 feasibility/evidenceSupport 为正收益，对
  falsifiability 与 novelty **净负**（−0.0175）——「批评 → 修订」
  不是全面提升，存在系统性牺牲维度。
- **一致性基线**：Judge×审批 5 组配对 kappa=1.0、零假自动批准
  （Wilson 上界 0.40@n=4，小样本诚实口径）。

## 2. Measurement（度量设计）

### 2.1 管道 A：judge-agreement 面板（监督链）

- 映射：Judge 判定 = auto 侧（APPROVE→auto_approve，其余→escalate）；
  独立审批 = human 侧。对齐 G12 校准门（决策 #13）的 escalate 正类。
- 统计：Cohen's kappa + Fleiss CI、假自动批准率单侧上界
  （Wilson / Beta-Binomial 双方法）、分 executionMode 分数漂移序列。
- 治理挂钩：与 auto-advance 校准门同构——评估器晋升可用同一统计闸门。
- 索引：`supervised_judge_quality_service.build_supervised_judge_quality_report()`
  + `/api/evolution/judge-quality` + 每轮终态自动快照台账
  （`evaluation/judge_quality/ledger.jsonl`）。

### 2.2 管道 B：diagnostic-reward 归因（假说链）

- 机制：CoNL r_diag 的免训练事后版——相邻轮次 × 同候选 × 维度级
  delta；ordinal 通道（七维评级，批评=低于 strong）由工作流 artifact
  权威存储水合；数值通道（五维 0-1 分，批评=基线<1.0）内联直读。
- 评审者归属优先级：行内 `reviewer` → 轮 `roles.reflection` → 默认。
- 输出：按评审者（improvement/harm rate + Wilson 下界 + mean reward）、
  按维度、整体；ordinal 与数值两通道独立报告。
- 索引：`reviewer_diagnostic_reward_service` +
  `/api/teams/{id}/research-workflow/reviewer-diagnostic-reward` +
  变化时快照台账（`evaluation/reviewer_diagnostic_reward/ledger.jsonl`）。

### 2.3 度量设计的三个原则

1. **可复算**：两个面板都是只读纯函数 × 持久存储，快照带内容指纹。
2. **宁缺毋滥**：缺任一侧判定的样本不入 kappa；缺证据不虚构未变化。
3. **小样本诚实**：一律报告 Wilson/Beta-Binomial 边界与样本量。

## 3. 贡献主张（草）

1. 「评估器的评估」双管道形式化：判定一致性（治理层）+ 批评诊断价值
   （内容层），两者互补且都可从既有生产数据零标注复算。
2. 维度异质性发现：修订循环的批评-改进归因存在系统性牺牲维度
   （falsifiability/novelty 净负），直接挑战「评审迭代=质量提升」假设。
3. 治理语义实证：同一个统计闸门族（kappa+上界）同时服务 autonomy
   晋升与评估器质量监测——与 Conformal Policy Control（动作自治层）/
   SEVerA（形式规约层）可清晰切割。

## 4. 开放项

- ordinal 通道的权威存储水合已接线，但历史轮次的 refs 覆盖率待统计。
- 人类锚点：目前 human 侧=审批 Agent；引入真实人工裁决记录后 kappa
  才是「对人一致性」而非「对代理一致性」。
- 评估器自身进化（rubric/prompt 版本化 + shadow 晋升）尚未实施，
  是本论文的实验增量所在（P1 偏好对 + 候选池晋升）。
