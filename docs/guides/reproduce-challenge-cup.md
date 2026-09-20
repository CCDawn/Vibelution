# 挑战杯科研团队复现指南

其他指南：[Windows 安装](install-windows.md) · [macOS 安装](install-macos.md) · [Linux 安装](install-linux.md)

目标：在一台新机器上，从 clone 仓库到跑起「挑战杯科研团队」六角色（搜索 / 提炼 / 知识管理 / 执行 / 实验修订 / 评估），可验证、可复现。全程约 15 分钟（不含依赖下载时间）。

## 你需要什么

1. 按对应平台指南完成安装：[Windows](install-windows.md) / [macOS](install-macos.md) / [Linux](install-linux.md)；
2. 一个阿里云百炼（DashScope）API key——团队全部模型走 `dashscope_main` 通道（申请：dashscope.console.aliyun.com → API-KEY 管理）。

## 步骤

### 1. 配置密钥

把 key 写入 shell 环境（macOS/Linux 写 `~/.zshrc` / `~/.bashrc`，Windows 按模型配置指南）：

```sh
export DASHSCOPE_API_KEY="sk-你的key"
```

配置文件 `~/Documents/Vibelution/config/config.toml` 首次启动时已自动生成（含 `dashscope_main` 预设，密钥以 `env:DASHSCOPE_API_KEY` 引用，不落盘）。

### 2. 启动工作台

```sh
.venv/bin/python scripts/vibelution_launcher.py --action start --no-browser
```

浏览器打开 http://127.0.0.1:8000。模型目录会自动发现 DashScope 可用模型（含 qwen3.8-flash / qwen3.7-plus / qwen3.8-max 系列）。

### 3. 导入团队配置包

任选其一：

**UI**：进入「团队」页 → 工具栏「导入团队配置包」→ 选择 `assets/team-bundles/challenge-cup-research.json` → 查看预检报告（6 个 Agent 新建、依赖、待补密钥清单）→「确认导入」。

**CLI**：

```sh
# 预检
.venv/bin/python scripts/team_bundle.py import --input assets/team-bundles/challenge-cup-research.json --dry-run
# 执行
.venv/bin/python scripts/team_bundle.py import --input assets/team-bundles/challenge-cup-research.json
```

### 4. 验证

- 「团队」页出现「挑战杯科研团队」，6 名成员角色齐全；
- 成员 Agent 的 dialogue 模型绑定分别为：搜索 `qwen3.8-flash`；提炼 / 知识管理 / 执行 / 实验修订 `qwen3.7-plus`；评估 `qwen3.8-max-0902`（依据 [10-qwen-challenge-cup-agent-routing.md](../ops/config/10-qwen-challenge-cup-agent-routing.md)，2026-09-08 核验版）；
- 任选一个成员发起会话能正常回复（密钥有效时）。

### 5. 跑通科研流程（可选）

团队就绪后，用研究画布 / 团队工作流推进「资料搜集 → 内容提炼 → 知识整理 → 假说生成 → 评审修订」；工作流定义见 `core/research/workflow/definitions/challenge-cup-research@3.0.0.json`。README 首页有 2026-09-08 录制的完整流程演示视频。

## 说明与边界

- 配置包内的 persona / task 提示词是按仓库 10 号文档职责**起草的 draft**；若你有原实例数据（原机器 `Documents\Vibelution\data\`），迁移后可用工作台导出原团队配置包替换本文件。
- 密钥永不进入配置包；导出的团队配置包只含 Agent 配置、模型路由与提示词，可自由分享。
- 导入是幂等的：重复导入同一配置包会按 `teamBundleAgentKey` 覆盖更新（upsert），不会产生重复 Agent。

## 常见问题

| 现象 | 处理 |
|------|------|
| 预检报告提示缺 `dashscope_main` | 未启动过工作台或配置目录未生成；先完成步骤 2 |
| 预检提示 `DASHSCOPE_API_KEY` 未设置 | 密钥环境变量未生效；重开终端或确认写入了正确的 rc 文件后重启工作台 |
| 成员会话无回复 | 检查 key 有效性与模型开通（qwen3.8-max 需要对应权限） |
| 导入后想恢复成员提示词 | 重新导入本配置包即可（upsert 覆盖） |
