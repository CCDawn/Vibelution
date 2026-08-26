# 默认功能复用证据闭环实施方案

## 目标

让所有会改实现代码、产品行为、架构或验证边界的开发任务，在写入前先检查项目内 owning surface，再对照成熟公开项目；收口时必须携带可验证的候选仓、固定 SHA、许可证、借鉴切片、拒绝理由和验证边界，避免只靠模型常识或无序链接实现功能。

这不是“每个任务必须新增一个仓库”。已有合适项目时直接复用本地浅克隆；只有索引未命中且候选通过质量门时才自动补库。

## 已接受的行为契约

1. 任何实现文件变更默认需要复用研究证据；纯文档、纯测试数据和不改变实现的元数据可豁免。
2. Agent 先读取 `activePaths.memory/github-projects/INDEX.md`，再决定是否联网搜索；未命中时比较 2–4 个候选，不在单一候选上拍脑袋。
3. 公开仓、许可证明确、体积不超过单仓安全上限时可自动浅克隆默认主干；项目总数只产生软提醒，不再成为逐次人工确认门。
4. 许可证不明确、私有仓、超大仓或需要扩大依赖/架构边界时仍停在确认门。
5. 复用研究必须给出 `REUSE / ADAPT / REFERENCE_ONLY / BUILD_IN_HOUSE`，并说明本地 owner、借鉴切片、拒绝项、实现边界和验证策略。
6. 候选的 `fullName / URL / localPath / HEAD / license / status` 从项目 GitHub 库读取，Agent 不手工伪造；证据在 closeout 时重新核对本地 clone。

## 复用研究与裁决

### 当前项目内

- `github_project_library_service.py` 已有 GitHub metadata、默认分支浅克隆、无子模块、长路径 Git、registry 与生成索引：`ADAPT`。保留实现，只把项目数量限制改成软提醒，并把许可证不明确变成确认门。
- `local_quality_gate.py` 已有 task/branch/HEAD/claim/changed-files 绑定和可复核 manifest：`ADAPT`。复用它承载证据快照，不创建第二套 closeout。
- Git common-dir 的 `vibelution-cache` 已承载不入 Git 的质量 manifest：`REUSE`。任务级复用证据写入相邻目录，避免污染仓库或跨 worktree 漂移。

### 外部成熟做法

- Git `clone --depth 1 --single-branch --branch <default>`：`REUSE`，继续固定默认主干 tip 且不拉历史/子模块。
- GitHub repository metadata 的默认分支、许可证和仓库体积：`ADAPT`，作为自动落库安全门，不能把 API 描述当技术结论。
- Promptfoo 等成熟评测项目的声明式配置与可复现输入思想：`REFERENCE_ONLY`，只借“结构化证据 + 固定版本 + 独立验证”，不引入其运行时。
- Codex/OpenCode 的分层项目指令发现：`REFERENCE_ONLY`，规则写入根 `AGENTS.md` 与现行标准/执行环，不复制其代码。

拒绝：每次开发强制新增仓库（会制造低价值条目）；只在文档里要求、无机器证据（无法防漏）；把整仓正文灌入 RAG（污染正式知识）；把候选名称、SHA、许可证完全交给 Agent 自报（不能降低幻觉）。

## 实施路径

### 1. 任务级复用证据合同

新增 `scripts/reuse_research_contract.py`，负责：

- 判断 changed files 是否需要证据；
- 从 active GitHub library registry 解析候选；
- 校验候选为 `ready`、本地 clone 存在、registry HEAD 等于 clone HEAD、许可证与决策兼容；
- 将任务证据原子写入 Git common-dir `vibelution-cache/reuse_research/<task-id>.json`；
- 加载、限制字段长度/数量并生成可嵌入 closeout manifest 的快照。

新增薄 CLI `scripts/reuse_research_evidence.py record`。Agent 只提供 feature、决策、本地 owner、候选 projectId、借鉴切片、拒绝理由、实现边界和验证策略；候选元数据由合同层填充。

### 2. GitHub 项目库默认自动落库

调整 `github_project_library_service.py`：

- `20` 项从硬确认上限改为软提醒阈值；
- 单仓约 1 GiB 的体积门保持硬确认；
- `NOASSERTION`、空许可证或其他未识别许可默认要求确认；
- clone/list payload 暴露有界 warning，不破坏 registry/index SSOT；
- 仍只克隆公开仓默认主干、depth 1、single branch、no recurse submodules。

### 3. 收口机器门

调整 `local_quality_gate.py`：

- manifest schema 升级并加入 `reuseResearch` 快照；
- 实现文件变更缺证据返回 `reuse_research_missing`，证据不匹配返回 `reuse_research_invalid`；
- closeout 在执行测试前验证证据，避免为注定不可收口的任务浪费全量验证；
- verify-manifest 复核证据结构、branch/task 绑定和固定候选提交仍可读取；
- 纯文档/豁免变更记录 `reuseResearchRequired=false`，不强迫凑候选。

`task_closeout.py` 继续调用同一 `run_closeout`，无需创建平行合入路径；只在测试显示错误传播不完整时做最小调整。

### 4. 默认规则与操作说明

同步修改：

- `AGENTS.md`：写成项目红线和默认顺序，明确“条件新增，不按数量凑仓”；
- `docs/standards/development-standard.md` §2.2：定义证据字段、许可证/体积/刷新门和豁免；
- `docs/guides/loop.md`：给出 record 命令与 closeout 顺序；
- `tests/README.md`：说明缺失/失效证据的修复办法。

## 风险与保护边界

- 不自动安装外部依赖、不运行外部代码、不复制整仓代码进入产品。
- 不因库数量增长自动删除、归档或覆盖旧 clone；磁盘治理保持独立、可恢复任务。
- `REFERENCE_ONLY` 可记录未知许可证项目的设计参考，但默认自动克隆仍要求许可证已识别；显式确认不会被解释为允许复制代码。
- 证据记录不是“成熟项目一定正确”的证明；它只证明 Agent 查了哪个固定版本、借了什么、为什么适配，最终仍由本项目测试和边界决定。
- 不把网页/API 描述写成实现结论；closeout 候选必须能解析到本地 clone。

## 验证与成功证据

- 合同单测覆盖：代码变更需证据、docs-only 豁免、候选缺失/脏/HEAD 漂移/许可证不兼容、字段限界和安全路径。
- GitHub library 单测覆盖：超过 20 项自动 clone 并返回 warning；未知许可证和超大仓仍需确认；已有项目不重复 clone。
- quality gate 单测覆盖：缺证据/坏证据失败，合法证据进入 manifest，verify-manifest 拒绝篡改，managed closeout 正确传播失败。
- 运行受影响的聚焦 pytest、selector 给出的门禁自测、`git diff --check`；自审实际 diff 后才进入本地 main 快进合入。

## 模式与执行顺序

模式：`COMPACT_PLAN`。一个 owner 串行完成，顺序为“合同与测试 → library 安全门 → closeout 集成 → 规则文档 → 聚焦验证 → 自审与本地合入”。共享 registry 不在本任务写入；除测试临时目录外不克隆新仓。
