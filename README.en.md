<p align="center"><img src="docs/assets/readme/vibelution-showcase.png" alt="Vibelution — a local multi-agent workbench. Give agents distinct roles and make their collaboration visible." width="100%"></p>

<p align="center"><strong>Organize your AI team, from task assignment and discussion to execution and review.</strong></p>

<p align="center">
  <a href="README.md">中文</a> · English<br>
  <a href="#watch-a-research-team-at-work">Research demo</a> · <a href="#core-capabilities">Core capabilities</a> · <a href="#side-products-built-on-the-workbench">Side products</a> · <a href="#get-started">Get started</a>
</p>

**Vibelution is a local multi-agent workbench.** Give members roles, models, and tools to discuss, execute, and review tasks. Follow their progress, step in at key decisions, and inspect handoff artifacts in one place.

## Watch a research team at work

Challenge Cup research demo: follow a team as it gathers sources, develops a hypothesis, and revises it after review.

[![Watch the Challenge Cup demo: workflow, team discussion, and knowledge graph](docs/assets/readme/challenge-cup-preview.gif)](docs/assets/readme/challenge-cup-demo.mp4)

**[▶ Full demo · 2:37 · 1080p · Chinese narration and subtitles](docs/assets/readme/challenge-cup-demo.mp4)** · [Download MP4](docs/assets/readme/challenge-cup-demo.mp4?raw=true) · [Full-resolution graph](docs/assets/readme/challenge-cup-graph.png)

**Team discussion → source collection and extraction → knowledge graph → hypothesis and revision.**

Follow a concrete hypothesis before and after review, and trace it back to source material. The team leaves research records that the next step can use.

> Recorded September 8, 2026: a replay of real historical data, with Chinese narration and subtitles. It does not show fresh execution, experimental validation, or formal competition acceptance. [Media notes](docs/assets/readme/README.md)

[Workflow reference](core/web/services/team_workflow/README.md)

## Core capabilities

### Put distinct roles to work together

Assign responsibilities and work through individual sessions and team discussions. Follow tool calls, task status, and handoff artifacts; stop, resume, or take over when needed.

### Make longer workflows visible

Connect tasks, conditional branches, and human checkpoints on a canvas. The research pipeline links sources, knowledge, hypotheses, and review while retaining candidate proposals and revisions.

### Carry knowledge into the next task

Personal memory and team knowledge bases retain sources and research records. Search and knowledge graphs help trace sources and explore relationships. The GitHub project library helps agents find code worth reusing.

### Equip each role with models and tools

Choose models per Agent, reuse prompts, skills, and plugins, and connect files, terminals, search, and coding tools. Configure external CLI agents, MCP, browser automation, or image generation as needed, and track model usage.

### Check improvements against evidence

Supervised evolution compares baselines with candidates. Self-evolution supports inspection, changes, and validation with explicit goals and stop conditions. Evaluation, review, and rollback records make each change inspectable.

<details>
<summary>Explore all features and configuration guides</summary>

Availability depends on models, permissions, and runtime configuration. Browser automation is disabled by default; the skill library UI is currently primarily for browsing.

#### Conversations, group discussions, and tasks

- **Individual sessions:** Create and manage conversations, follow streamed replies, inspect tools, pending approvals, and history, and stop or resume work.
- **Multi-agent rooms:** Bring several members into a shared discussion, with direct conversations and group rooms in one index.
- **Coding workspace:** Browse project files, read their contents, work with terminals and tools, and inspect related child sessions.
- **Kernel Task Center:** Filter tasks by status and assigned Agent, then follow dispatch, execution, delivery outcomes, and artifact references on a timeline.
- **External agents:** Execution and terminal entry points for configured CLI agents. An MCP gateway lets external coding tools submit tasks to managed project agents and query their results. Both require the appropriate setup.

[Conversation workspace](web/src/routes/chat/README.md) · [MCP setup](docs/agents/mcp-managed-agent-gateway.md)

#### Agents, prompts, tools, and skills

- **Agent management:** Create, edit, archive, and bulk-manage roles; inspect model bindings and capabilities.
- **Prompt templates:** Browse and maintain reusable role instructions, and inspect the context assembled for a conversation.
- **Tool management:** Inspect the catalog and each Agent's permissions. Configured tools cover files, code edits, commands, tests, webpage retrieval, and paper, news, and project search.
- **Skill library:** Search and read skill descriptions and details so agents can find reusable methods. The current UI is primarily a browsing surface.
- **Agent plugins:** Bind optional capabilities to selected agents, such as Virtual Human Life.
- **Browser automation:** Controlled Computer Use in a sandbox browser; disabled by default and enabled through configuration.
- **Image generation:** An Agent tool for generating images, requiring the corresponding image service configuration and tool permission.

[Agent configuration](core/web/services/agent_directory/README.md) · [Tool catalog](tools/README.md) · [Tool permissions](docs/agents/tool-authorization-entrypoints.md)

#### Teams, research, and knowledge

- **Teams and workflows:** Manage members and role relationships, reuse team templates, and inspect task nodes, branches, human checkpoints, and stage handoffs on a canvas.
- **Research pipeline:** Work from questions and sources through knowledge organization, hypotheses, review, and experiment design. Keep candidate proposals, revisions, and stage artifacts. Experiment execution and acceptance have their own requirements.
- **Source processing:** Agent tools for source intake, processing, and retrieval, with source references for subsequent work.
- **Personal memory and team knowledge:** Separate views of Agent memories and shared knowledge, including proposals, ingestion, and review records.
- **Search and graphs:** Search memory and knowledge and explore relationships. Optional vector indexing can enhance retrieval when configured.
- **GitHub project library:** Index shallow clones of public repositories so agents can find code worth reusing.
- **User documents and governance:** Manage Markdown content, sources, indexes, and effective content. Preview the scope before protected cleanup.

[Team workflows](core/web/services/team_workflow/README.md) · [Knowledge base](core/web/services/team_knowledge/README.md) · [Memory and retrieval](core/web/services/memory_rag_services.md)

#### Supervised evolution and self-evolution

**Supervised evolution: compare before deciding.** Manage datasets and evaluation bundles, compare baselines with candidates, and inspect live runs, history, and the library. Conversation samples have a separate review queue. Proposals and advisory baselines retain records; candidate execution and integration use isolated validation.

**Self-evolution: give each improvement a clear goal.** Inspect repository and runtime state, start bounded inspection, modification, and validation, and retain transaction, audit, and rollback records. Continuing loops require user approval and explicit stop conditions.

Neither mode grants unrestricted permission to change the project. Producing a proposal does not, by itself, demonstrate an improvement.

[Evolution modes and execution](core/web/services/evolution_services.md) · [Configuration](docs/ops/config/06-agent-evolution.md)

#### Models, configuration, and usage

- **Models and providers:** Manage providers, model libraries, role bindings, and runtime parameters. Choose models per Agent and configure protocols, output limits, and caching for each provider.
- **Configuration workspace:** Inspect and adjust runtime settings, model references, and provider drafts. Credentials live outside the repository.
- **Token usage:** View all-time, daily, seven-day, and latest-call totals, with Agent, session, and model breakdowns, cache reads, context limits, and latency. Records distinguish provider-reported usage, estimates, and missing data.
- **Interface preferences:** Chinese and English, themes and backgrounds, and persistent pane layouts.

[Model and configuration guide](docs/ops/config/INDEX.md)

#### Git, runtime management, and troubleshooting

- **Git workbench:** Inspect status, diffs, and history, select files to commit, and draft commit messages.
- **Launcher and system tray:** Start, stop, restart, and open the workbench. Active-task checks protect lifecycle actions while work is running.
- **Branch instances:** Inspect isolated branch workspaces and their runtime state, and manage separate development instances.
- **Logs and runtime scenes:** Browse logs and diagnostics, connect session, tool, and process problems, and inspect or export per-run evidence packages.
- **Maintenance and reset:** Preview cleanup scope and perform protected maintenance on allowed targets.

[Launcher and desktop](desktop/electron/README.md) · [Logging and diagnostics](core/logging/README.md) · [Runtime configuration](docs/ops/config/07-launcher-runtime-workbench.md)

</details>

## Side products built on the workbench

<p align="center">
  <img src="docs/assets/readme/companions.png" alt="Virtual-human lobby" width="52%">
  <img src="docs/assets/readme/desktop-pet.gif" alt="Desktop buddy idle animation recording" width="16%">
</p>

- **Virtual humans:** Characters with schedules, moods, diaries, long-term memory, and proactive messages. Continuity between life events and dialogue is still being refined. [Character capabilities](core/agent_plugins/virtual_human_life/README.md)
- **Desktop buddy:** See session status on your desktop, click to inspect conversations, drag to reposition, and reopen it from the system tray.
- **Pet space:** Inspect levels, experience, state, and achievements.

## Get started

The primary desktop experience is currently **Windows**. Install **Python 3.11+ (3.12 recommended), Node.js 18+, and Git**, then run in PowerShell:

```powershell
git clone https://github.com/CCDawn/Vibelution.git
cd Vibelution
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

Open **Vibelution Launcher** from the desktop. The first launch prepares the external configuration file. Configure your model and credentials using the [model configuration guide](docs/ops/config/INDEX.md), then start a conversation.

[Windows setup](docs/guides/install-windows.md) · [Development and contributing](CONTRIBUTING.md) · [Linux deployment reference](docs/ops/linux-bootstrap.md)

The workbench runs locally, with models you configure. **Cloud-model requests are sent to the selected provider**; local-first does not mean every inference runs offline. Provider fees may apply. Credentials and runtime configuration live outside the repository.

## Documentation and contributing

This page reflects September 2026 development progress; see [CHANGELOG](CHANGELOG.md) for releases. Share a use case or report a problem in [Issues](https://github.com/CCDawn/Vibelution/issues), or start with the [contribution guide](CONTRIBUTING.md).

---

[Documentation](docs/README.md) · [Development standards](docs/standards/README.md) · [Security](SECURITY.md) · [Third-party components](THIRD_PARTY_COMPONENTS.md) · [MIT code license](LICENSE)

Character names and third-party media remain the property of their respective rights holders. The code's MIT license does not grant rights to third-party characters or media.
