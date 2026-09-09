<h1 align="center">Vibelution</h1>

<p align="center"><strong>Build AI teams that communicate, collaborate, and evolve.</strong></p>
<p align="center">Native multi-agent setup · Agent communication · Team collaboration · Self and supervised evolution · Virtual characters</p>

<p align="center">
  <a href="README.md">中文</a> · English<br>
  <a href="#native-multi-agent-setup">Build agents</a> · <a href="#agent-communication">Communication</a> · <a href="#team-collaboration">Teams</a> · <a href="#self-evolution-and-supervised-evolution">Evolution</a> · <a href="#virtual-characters">Virtual characters</a> · <a href="#get-started">Get started</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/Code-MIT-38bdae?style=flat-square" alt="Code license: MIT"></a>
  <a href="docs/guides/install-windows.md"><img src="https://img.shields.io/badge/Desktop-Windows-4979e8?style=flat-square" alt="Windows desktop workbench"></a>
  <a href="https://github.com/CCDawn/Vibelution/issues"><img src="https://img.shields.io/badge/Feedback-welcome-f2b36d?style=flat-square" alt="Feedback welcome"></a>
</p>

<p align="center">
  <img src="docs/assets/readme/vibelution-showcase.png" alt="Vibelution showcase composite: native multi-agent research collaboration and a knowledge graph" width="100%">
</p>

**Vibelution is a local multi-agent platform for people organizing AI teams for academic research.** Create agents in the workbench, configure their roles, models, tools, and memory, and let members collaborate through messages, group discussions, and team workflows. Use evaluation and evolution workflows to improve agents or the project implementation.

From research teams to long-term character interactions, five capabilities form the core experience:

| Core capability | What you can do |
| --- | --- |
| **Native multi-agent setup** | Create and manage distinct agents with their own identities, responsibilities, models, prompts, tools, and memory, then organize them into teams |
| **Agent communication** | Send messages to a specific agent session and request processing; exchange information through member messages, team broadcasts, and group discussions |
| **Team collaboration** | Assign roles, connect tasks and human checkpoints, and use the research canvas for source collection, knowledge organization, hypothesis review, and experiment design |
| **Self and supervised evolution** | Inspect, modify, and validate against an explicit objective, or evaluate improvements with datasets and baseline-versus-candidate comparisons |
| **Virtual characters** | Bind character life capabilities to agents, including schedules, emotions, diaries, long-term memory, and proactive messages |

## Watch a research team at work

**Team discussion → source collection → extraction → knowledge graph → hypothesis generation → review and revision.**

[![Watch the research team demo: workflow, member discussion, and knowledge graph](docs/assets/readme/challenge-cup-preview.gif)](docs/assets/readme/challenge-cup-demo.mp4)

**[▶ Full demo · 2:37 · 1080p · Chinese narration and subtitles](docs/assets/readme/challenge-cup-demo.mp4)** · [Download MP4](docs/assets/readme/challenge-cup-demo.mp4?raw=true)

Look at how members divide responsibilities, hand sources to the next stage, and revise a hypothesis after review. Research is one scenario where these platform capabilities work together: researchers decide on directions and conclusions while agents help collect, organize, discuss, and execute the work, leaving traceable research records.

> A Challenge Cup research scenario recorded on September 8, 2026: a replay of real historical data, with Chinese narration and subtitles. It shows workflow and revision records, not fresh execution, experimental findings, or formal competition acceptance. [Media sources and dates](docs/assets/readme/README.md)

## Native multi-agent setup

**Create agents inside Vibelution with their own configuration, sessions, and personal memory, then build teams around the work.** The workbench provides interfaces for role creation, member management, model binding, and tool authorization.

- **Define identities and responsibilities:** Create, edit, archive, and bulk-manage agents, with identity and task prompts for each member.
- **Choose models by role:** Bind providers and models separately and configure runtime parameters for collection, analysis, coding, and review.
- **Configure capabilities and accumulated knowledge:** Authorize file, terminal, and search tools; reuse prompts and skills; bind optional plugins. Personal memory can carry into later sessions of the same agent.
- **Move from individual work to teams:** Work directly with one agent or bind members to team roles and reuse team templates.

For a research question, for example, configure roles for source collection, hypothesis generation, experiment design, and result review, give them appropriate models and tools, and involve them in the same research workflow.

[Agent configuration and management](core/web/services/agent_directory/README.md) · [Model configuration](docs/ops/config/INDEX.md) · [Tool authorization](docs/agents/tool-authorization-entrypoints.md)

## Agent communication

**An agent can send a message to another agent's specific session and request that it continue the work.** Source handoffs, proposal discussions, and review feedback can flow through the platform's communication capabilities.

| Communication channel | Purpose |
| --- | --- |
| **Agent-to-agent messages** | Send sources, questions, or feedback to a target session; the message enters its history and can request that session be woken to process it |
| **Team group chat** | Bring members into a shared discussion and inspect team task rounds and conversation records |
| **Team broadcasts** | Communicate shared information to a team and inspect broadcasts and member messages |
| **Delivery and task tracking** | Inspect delivery, session wake, and execution status, distinguishing a delivered message from completed work |

For example, a source collection agent can hand material to a hypothesis agent, and a reviewer can send feedback to the relevant session. Communication has an explicit destination and is subject to role permissions and team communication rules. Researchers can inspect the records and follow each handoff.

[Agent communication mechanism](docs/adr/0002-agent-collaboration-session-addressing.md) · [Conversation workbench](web/src/routes/chat/README.md)

## Team collaboration

**Organize multiple agents' work into a visible workflow.** The team workbench manages members and role relationships, while the research canvas shows task nodes, dependencies, conditional branches, human checkpoints, and stage artifacts.

![Historical research canvas replay: task nodes, dependencies, and source collection](docs/assets/readme/research-workflow.png)

*Historical replay of the research canvas and a close-up of source collection. Select a node to inspect its task and neighboring stages.*

For academic research, collaboration can cover:

| Research stage | Collaboration and resulting records |
| --- | --- |
| **Source and code research** | Search papers, web pages, and public projects through configured tools; screen candidates, extract content, and retain sources. The GitHub library supports local shallow clones and indexing so agents can inspect reusable implementations |
| **Knowledge organization and handoff** | Organize sources into team knowledge with proposal, review, and ingestion records; personal memory, shared knowledge, and unified search support reuse in later tasks |
| **Hypotheses and review** | Propose candidate directions, record review feedback and revisions, and compare plans and their supporting evidence |
| **Experiment design and runs** | Manage datasets, metrics, baselines, and preliminary checks; revise and freeze plan versions and associate preliminary and formal run records |
| **Iteration and handoff** | Ingest results into knowledge and use iteration and export entry points to carry this round's records into the next stage |

[![Historical research knowledge graph: content, relationships, and sources](docs/assets/readme/challenge-cup-graph.png)](docs/assets/readme/challenge-cup-graph.png)

*[View the full-resolution graph](docs/assets/readme/challenge-cup-graph.png). The graph organizes and traces material; academic conclusions still require checking original sources and experiments.*

Experiment execution depends on supported adapters, data, environment, and run prerequisites. Passing a preliminary check establishes only that check's outcome; experimental performance must come from the corresponding formal run.

[Research workflow and experiment modules](core/web/services/team_workflow/README.md) · [Team knowledge](core/web/services/team_knowledge/README.md) · [Memory and retrieval](core/web/services/memory_rag_services.md)

## Self-evolution and supervised evolution

**Give improvements to agents or the project an objective, a comparison, and an inspectable process.** Vibelution provides two evolution modes.

### Self-evolution: inspect, modify, and validate against a goal

Initiate inspection, modification, and validation within a defined objective and scope. Inspect run status, change transactions, audit, and rollback records. Continuous iteration requires user approval and stopping conditions.

**Objective → inspection → modification → validation → review of results and next steps.**

### Supervised evolution: evaluate with baselines and candidates

Manage evaluation datasets and test bundles, run baseline-versus-candidate comparisons, and review improvement proposals. The workbench provides active runs, historical results, session sample reviews, a proposal library, and recommended baselines. Candidate execution and integration go through isolated validation.

**Baseline evaluation → improvement proposal → candidate execution and re-evaluation → review → integration decision.**

![Supervised evolution workbench: evaluation sources, baseline testing, proposal review, and user approval](docs/assets/readme/web-workbench-supervised.png)

*An existing repository screenshot illustrating the supervised evolution layout. No run has started in this image; it is not evidence of an improvement.*

These modes evaluate and improve agents or the project implementation. The scientific validity of a research hypothesis still needs its own experimental validation, and a generated proposal alone does not establish improved capability.

[Evolution modes and runtime reference](core/web/services/evolution_services.md) · [Agent and evolution configuration](docs/ops/config/06-agent-evolution.md)

## Virtual characters

**Give agents a character identity, life state, and long-term interactions.** A per-agent life plugin adds schedules, activities, and memory beyond conversation. Browse characters in the gallery and enter their sessions.

![Virtual character gallery: identity, life state, mood, and schedule](docs/assets/readme/companions.png)

- **Schedules and daily life:** Manage daily plans, activities, long-term goals, projects, and habits, retaining state across days.
- **Emotions and relationships:** Derive mood and relationship changes from interactions and life events to inform character expression.
- **Diaries and long-term memory:** Record completed activities and retain experiences through reflection and sourced memory.
- **Proactive conversation:** Generate messages according to character state and interaction context, and continue unfinished topics and commitments.

Life and conversation continuity are still being refined. Character capabilities apply only to agents with the plugin explicitly bound and enabled.

<p align="center">
  <img src="docs/assets/readme/desktop-pet.gif" alt="Recorded desktop companion idle animation" width="150">
</p>

Desktop companions can also show session status and open conversations; pet space displays levels, experience, status, and achievements.

[Virtual character life plugin](core/agent_plugins/virtual_human_life/README.md)

## Models, tools, and the research environment

| Capability | What the workbench provides |
| --- | --- |
| **Models and usage** | Multiple providers, per-agent model bindings, protocol and cache settings; token usage, cache reads, and latency by agent, session, or model, distinguishing reported, estimated, and missing data |
| **Prompts, skills, and plugins** | Prompt management, actual session context inspection, and reusable role capabilities; the skill library currently focuses on search and browsing |
| **Files, terminal, and Git** | Read and modify research code, execute commands and tests, inspect diffs and history, and select files to commit |
| **External agents** | Connect configured CLI agents; external development tools can use the MCP gateway to submit tasks to non-team managed agents and query results |
| **Browser and image tools** | Configure services and authorize agent tools as needed; browser automation is disabled by default |
| **Runtime management and diagnostics** | Launcher lifecycle controls, isolated branch instances, task timelines, logs, and runtime records for investigating long-running tasks |

[Model configuration](docs/ops/config/INDEX.md) · [Tool catalog](tools/README.md) · [MCP setup guide](docs/agents/mcp-managed-agent-gateway.md)

## Get started

The primary experience is a **local Windows desktop app**. Install **Python 3.11+ (3.12 recommended), Node.js 18+, and Git**, then run in PowerShell:

```powershell
git clone https://github.com/CCDawn/Vibelution.git
cd Vibelution
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

Open **Vibelution Launcher** from the desktop after installation. The first launch prepares external configuration files; follow the [model configuration guide](docs/ops/config/INDEX.md) to set up models and credentials.

**Start building around a research question:**

1. Create agents and configure their roles, models, prompts, and required tools.
2. Create or select a research team and bind agents to its roles.
3. Provide the question, available sources, and this round's objective, then work through sessions, team discussions, and the research workflow.
4. Inspect member messages, stage artifacts, and review feedback before deciding on the next research direction.

[Windows installation](docs/guides/install-windows.md) · [Development and contributing](CONTRIBUTING.md) · [Linux deployment reference](docs/ops/linux-bootstrap.md)

The workbench runs locally, using models you configure. Cloud model requests are sent to the selected provider and may incur fees; credentials and runtime configuration live outside the repository.

## Documentation and contributing

This page presents development progress as of September 2026. See the [CHANGELOG](CHANGELOG.md) for release history. Share research scenarios, multi-agent collaboration problems, and feature suggestions through [Issues](https://github.com/CCDawn/Vibelution/issues), or start with the [contributing guide](CONTRIBUTING.md).

[Documentation map](docs/README.md) · [Development standards](docs/standards/README.md) · [Security](SECURITY.md) · [Third-party components](THIRD_PARTY_COMPONENTS.md) · [MIT code license](LICENSE)

Character names and third-party assets belong to their respective rights holders. The MIT license for the code does not grant rights to those characters or assets.
