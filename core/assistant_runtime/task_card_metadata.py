"""Optional, body-free display labels over existing dispatch identities."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import unicodedata

import anyio

from core.external_agent.backend_client import BackendClientError

from .dispatch import DispatchError

_CONCURRENCY = 4
_LOOKUP_BUDGET = 0.2
_PAGE_BUDGET = 0.8
_MAX_LOOKUPS = 128
# Keep at most one page's worth of public labels, not task or execution state.
_MAX_CACHED_LABELS = _MAX_LOOKUPS
_LABEL_AUTHORITY_ERRORS = frozenset({
    "SCOPE_DENIED", "SUBJECT_DENIED", "SUBJECT_REVOKED", "TARGET_BINDING_CHANGED",
    "UNKNOWN_MANAGEMENT_SUBJECT", "MANAGEMENT_IDENTITY_ROTATED", "RUNTIME_IDENTITY_MISMATCH",
})


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


def _discard_project_labels(labels, project, binding):
    for key in tuple(labels):
        if key[0] == project and (binding is None or key[1] != binding):
            labels.pop(key, None)


async def enrich_dispatch_cards(dispatch, rows):
    """Copy rows and add best-effort labels without reading task/session bodies.

    A failed directory, denied scope or timeout leaves the native card usable.
    The service retains bounded public labels only for a currently authorized,
    exact project binding. Every request still attempts fresh directory reads;
    cached labels cannot authorize work or become a second task ledger.
    """
    cards = deepcopy(rows)
    binding_reader = getattr(dispatch, "_project_read_binding", None)
    agent_reader = getattr(getattr(dispatch, "management", None), "agent", None)
    if not callable(binding_reader):
        return cards
    labels = getattr(dispatch, "_task_card_agent_labels", {})
    state = getattr(dispatch, "_dispatch_state", nullcontext())
    bindings, targets = {}, {}
    for index, row in enumerate(cards):
        project, agent = row.get("projectId"), row.get("agentId")
        if not isinstance(project, str) or not project:
            continue
        if project not in bindings:
            with state:
                try:
                    bindings[project] = binding_reader(project)
                except Exception:
                    bindings[project] = None
                _discard_project_labels(labels, project, bindings[project])
        if bindings[project] is None:
            continue
        name = project_display_name(bindings[project])
        if name:
            row["projectName"] = name
        if isinstance(agent, str) and agent:
            targets.setdefault((project, agent), []).append(index)
            with state:
                cached = labels.get((project, bindings[project], agent))
                if cached:
                    row["agentName"] = cached

    semaphore = anyio.Semaphore(_CONCURRENCY)
    denied_projects = set()

    def discard_agent_labels(project, agent=None):
        with state:
            if agent is None:
                denied_projects.add(project)
                _discard_project_labels(labels, project, None)
            else:
                labels.pop((project, bindings[project], agent), None)
            for (target_project, target_agent), indices in targets.items():
                if target_project == project and (agent is None or target_agent == agent):
                    for index in indices:
                        if "agentName" in rows[index]:
                            cards[index]["agentName"] = deepcopy(rows[index]["agentName"])
                        else:
                            cards[index].pop("agentName", None)

    async def lookup(project, agent, indices):
        async with semaphore:
            try:
                if project in denied_projects:
                    return
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
                    with state:
                        if (not isinstance(result, dict) or result.get("projectId") != project
                                or not isinstance(identity, dict) or identity.get("agentId") != agent):
                            discard_agent_labels(project, agent)
                            return
                        if binding_reader(project) != bindings[project]:
                            return
                        name = display_name(identity.get("displayName"))
                        if name:
                            key = (project, bindings[project], agent)
                            labels.pop(key, None)
                            labels[key] = name
                            while len(labels) > _MAX_CACHED_LABELS:
                                labels.pop(next(iter(labels)), None)
                            for index in indices:
                                cards[index]["agentName"] = name
            except (BackendClientError, DispatchError, PermissionError) as exc:
                # Registry identity alone does not prove the native agents:read
                # grant still exists. Explicit denials invalidate this page too.
                if isinstance(exc, PermissionError) or exc.code in _LABEL_AUTHORITY_ERRORS:
                    discard_agent_labels(project)
            except Exception:
                pass

    async def lookup_project(project, agents):
        # Native reads share one project lock. Do not mistake another label
        # lookup from this request for busy task control and drop its siblings.
        for agent, indices in agents:
            await lookup(project, agent, indices)

    if callable(agent_reader):
        by_project = {}
        for (project, agent), indices in list(targets.items())[:_MAX_LOOKUPS]:
            by_project.setdefault(project, []).append((agent, indices))
        with anyio.move_on_after(_PAGE_BUDGET):
            async with anyio.create_task_group() as tasks:
                for project, agents in by_project.items():
                    tasks.start_soon(lookup_project, project, agents)
    # Registry changes invalidate only optional labels, never original rows.
    for index, row in enumerate(cards):
        project = row.get("projectId")
        with state:
            try:
                current = binding_reader(project)
            except Exception:
                current = None
            _discard_project_labels(labels, project, current)
        if project in bindings and (current is None or current != bindings[project]):
            for key in ("agentName", "projectName"):
                if key in rows[index]:
                    row[key] = deepcopy(rows[index][key])
                else:
                    row.pop(key, None)
    return cards
