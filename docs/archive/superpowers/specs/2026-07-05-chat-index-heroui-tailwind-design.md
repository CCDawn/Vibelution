# Chat Index HeroUI Tailwind Design

## Goal

Optimize the Chat/Coding left conversation index shown in the screenshot so it reads as one compact HeroUI/VUI + Tailwind sidebar list.

## Scope

- Optimize only the left conversation index area: search, create actions, grouped conversation headers, direct/group/team conversation rows, active/running/status chips, and the system entry row.
- Preserve conversation data flow, session grouping, context menus, drag references, delete/rename behavior, group composer behavior, and the right-side conversation surface.
- Use the existing VUI wrappers over HeroUI primitives where practical, and keep styling in Tailwind utility strings.

## Design

- Search becomes a stable compact input surface with icon affordance, clearer focus state, and no heavy nested border.
- Create actions become content-sized HeroUI/VUI buttons with consistent 32px height, icons, and restrained emphasis.
- Group headers become quiet scan rows with a rotating chevron, truncated label, and a small count badge.
- Conversation items share one visual contract: subtle row background, stable grid, avatar/icon, title, model/status chips, time, and lightweight active/running emphasis.
- Running and current states use color chips and a slim accent treatment instead of heavy outlines.
- System entry uses the same row grammar as conversations so it no longer feels like a separate card system.

## Non-Goals

- No backend changes.
- No API or DTO changes.
- No new dependency.
- No redesign of the main chat transcript, composer, Teams canvas, or Agent Center.

## Validation

- Focused Vitest layout/component tests must lock Tailwind/VUI/HeroUI contracts for search/actions/sections/items/system entry.
- `npm --prefix web run build` must pass.
- Browser verification must inspect the Chat page at desktop and narrow widths for no overlap, no overflowing long Chinese text, stable button sizing, readable grouping, and no console errors.
