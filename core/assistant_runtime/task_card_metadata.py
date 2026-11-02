"""Optional, body-free display labels over existing dispatch identities."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unicodedata

import anyio

_CONCURRENCY = 4
_LOOKUP_BUDGET = 0.2
_PAGE_BUDGET = 0.8
_MAX_LOOKUPS = 128


def display_name(value):
    """Treat public names as bounded, untrusted text, never instructions."""
    if not isinstance(value, str):
        return ""
    visible = (" " if char.isspace() else char for char in value
               if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
    return " ".join("".join(visible).split())[:160]


def project_display_name(binding):
    """The registered root's basename is a label, never project identity."""
    if not isinstance(binding, tuple) or len(binding) != 2 or not isinstance(binding[1], Path):
        return ""
    return display_name(binding[1].name)


async def enrich_dispatch_cards(dispatch, rows):
    """Copy rows and add best-effort labels without reading task/session bodies.

    A failed directory, denied scope or timeout leaves the native card usable.
    Names are scoped to this request and rechecked against the same binding;
    neither a durable cache nor a second task ledger is created.
    """
    cards = deepcopy(rows)
    binding_reader = getattr(dispatch, "_project_read_binding", None)
    agent_reader = getattr(getattr(dispatch, "management", None), "agent", None)
    if not callable(binding_reader):
        return cards
    bindings, targets = {}, {}
    for index, row in enumerate(cards):
        project, agent = row.get("projectId"), row.get("agentId")
        if not isinstance(project, str) or not project:
            continue
        if project not in bindings:
            try:
                bindings[project] = binding_reader(project)
            except Exception:
                bindings[project] = None
        if bindings[project] is None:
            continue
        name = project_display_name(bindings[project])
        if name:
            row["projectName"] = name
        if isinstance(agent, str) and agent:
            targets.setdefault((project, agent), []).append(index)

    semaphore = anyio.Semaphore(_CONCURRENCY)

    async def lookup(project, agent, indices):
        async with semaphore:
            try:
                # Metadata must not queue behind task control or make _call
                # wait for a shielded native heartbeat borrower to drain.
                slots = getattr(dispatch, "_active_project_clients", {})
                slot = slots.get(project)
                guard = getattr(dispatch, "_project_locks", {}).get(project)
                if (slot is not None and (slot.borrowers or slot.closing)
                        or guard is not None and guard.locked()):
                    return
                with anyio.move_on_after(_LOOKUP_BUDGET):
                    result = await agent_reader(project, agent_id=agent)
                    identity = result.get("agent") if isinstance(result, dict) else None
                    if (not isinstance(result, dict) or result.get("projectId") != project
                            or not isinstance(identity, dict) or identity.get("agentId") != agent
                            or binding_reader(project) != bindings[project]):
                        return
                    name = display_name(identity.get("displayName"))
                    if name:
                        for index in indices:
                            cards[index]["agentName"] = name
            except Exception:
                pass

    if callable(agent_reader):
        with anyio.move_on_after(_PAGE_BUDGET):
            async with anyio.create_task_group() as tasks:
                for (project, agent), indices in list(targets.items())[:_MAX_LOOKUPS]:
                    tasks.start_soon(lookup, project, agent, indices)
    # Registry changes invalidate only optional labels, never original rows.
    for index, row in enumerate(cards):
        project = row.get("projectId")
        try:
            current = binding_reader(project)
        except Exception:
            current = None
        if project in bindings and (current is None or current != bindings[project]):
            for key in ("agentName", "projectName"):
                if key in rows[index]:
                    row[key] = deepcopy(rows[index][key])
                else:
                    row.pop(key, None)
    return cards
