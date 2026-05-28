# Vibelution Product Context

## Register

product

## Product Purpose

Vibelution is a local-first AI Agent workbench for engineering collaboration, repository reading, Git operations, self-evolution, supervised evaluation, runtime-scene evidence, and model configuration. It is not a marketing site and not a hosted assistant shell. The interface exists to help a developer and future Agents understand, validate, and improve the same local project with clear evidence and reversible operations.

## Primary Users

- Developer operator: works in the Web Workbench during coding, review, debugging, Git submission, and configuration.
- Maintainer: inspects runtime scenes, supervised evolution records, worktree state, and operational risk before accepting changes.
- Future Agent: uses the UI, logs, project memory, and stable terminology to reconstruct prior work without relying on stale screenshots or guesswork.

## Core Surfaces

- Chat and Coding: multi-session collaboration, file tree, readonly previews, message state, active task context, and run status.
- Agent Management: Agent registry, prompts, tools, skills, memory, runtime activity, and permission boundaries.
- Git: worktree status, diffs, selected-file commits, and AI-assisted commit message drafts.
- Supervised Evolution: dataset and bundle runs, active run monitoring, proposal library, decision records, and advisory baseline governance.
- Self Evolution: bounded self-improvement, audit trail, rollback boundary, and fitness evidence.
- Logs and Runtime Scenes: packaged lifecycle evidence for diagnosing failures, stalls, drift, delegation, and validation outcomes.
- Config, Reset, and Pet: operational settings, protected cleanup, and long-lived companion state.

## Product Tone

Calm, precise, operational, and evidence-led. The UI should feel like a serious local control room: dense enough for repeated work, quiet enough for long sessions, and explicit about state, risk, and provenance. It should make progress legible without pretending uncertainty is certainty.

## Design Register Guidance

Most Vibelution frontend work uses the product register: design serves the task. Prefer stable affordances, predictable layout, native-feeling controls, clear hierarchy, and consistent component vocabulary. Do not turn workbench pages into landing pages, hero sections, decorative showcases, or card-heavy marketing compositions.

## Visual Priorities

- Compact information density with readable grouping.
- Strong state visibility for running, idle, failed, blocked, stopped, selected, pending, and archived states.
- Evidence-first navigation: logs, sessions, files, runs, and decisions should be reachable from the context that mentions them.
- Stable route-level structure across related pages, especially Agent management, Chat/Coding, Evolution, Logs, and Research.
- Clear split between global system health and the active Agent or session state.
- Keyboard-visible focus and touch-safe controls where applicable.

## Anti-References

- Generic SaaS landing page aesthetics.
- Large decorative hero areas inside task surfaces.
- Nested cards, identical card grids, and repeated icon-heading-text blocks.
- Purple-blue gradient branding used as decoration.
- Glassmorphism as a default surface style.
- Display fonts in controls, labels, data tables, logs, or dense panels.
- Motion that delays task completion or only adds spectacle.

## Strategic Principles

- Evidence before theory: logs, runtime scenes, tests, and current data are primary.
- Product clarity before visual novelty.
- Consistency is an affordance across workbench routes.
- Every user-visible behavior change needs an explicit logging decision and test decision.
- Preserve local-first trust: do not hide paths, states, errors, or irreversible actions behind vague copy.
- Optimize for future reconstruction by humans and Agents.
