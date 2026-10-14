"""Repair only plugin-owned simulated memories through native supersession."""

from collections.abc import Callable, Mapping
from typing import Any

from .life_provenance import event_provenance

CORRECTION_LEDGER = "memory/source_corrections.jsonl"


class LifeMemorySourceReconciler:
    def __init__(
        self,
        store: Any,
        *,
        history_lister: Callable[..., list[dict[str, Any]]] | None,
        superseder: Callable[..., dict[str, Any]] | None,
        event_lister: Callable[[str], list[dict[str, Any]]],
        now_iso: Callable[[], str],
    ):
        self.store = store
        self.history_lister = history_lister
        self.superseder = superseder
        self.event_lister = event_lister
        self.now_iso = now_iso

    def reconcile(self, agent_id: str) -> list[dict[str, Any]]:
        corrections = self.store.read_jsonl(agent_id, CORRECTION_LEDGER)
        applied = {
            str(row.get("episodeId") or "")
            for row in corrections
            if row.get("status") == "applied"
        }
        receipts = [
            row
            for row in self.store.read_jsonl(
                agent_id, "memory/promotion_receipts.jsonl"
            )
            if str(row.get("episodeId") or "") not in applied
        ]
        if not receipts or self.history_lister is None:
            return corrections
        episode_ids = list(
            dict.fromkeys(
                str(row.get("episodeId") or "")
                for row in receipts
                if row.get("episodeId")
            )
        )
        episodes = []
        for offset in range(0, len(episode_ids), 500):
            episodes.extend(
                self.history_lister(
                    agent_id,
                    limit=500,
                    include_superseded=True,
                    episode_ids=episode_ids[offset : offset + 500],
                )
            )
        by_id = {
            str(row.get("episodeId") or row.get("eventId") or ""): row
            for row in episodes
            if not row.get("agentId") or row.get("agentId") == agent_id
        }
        events = {
            str(row.get("eventId") or ""): row for row in self.event_lister(agent_id)
        }
        for receipt in receipts:
            episode_id = str(receipt.get("episodeId") or "")
            episode = by_id.get(episode_id)
            sources = list(
                dict.fromkeys(
                    str(value) for value in receipt.get("sourceEventIds", []) if value
                )
            )
            if (
                episode_id in applied
                or not episode
                or episode.get("kind") != "private_note"
                or not sources
            ):
                continue
            refs = {
                str(ref.get("id") or "")
                for ref in episode.get("refs", [])
                if isinstance(ref, Mapping) and ref.get("type") == "item"
            }
            if (
                set(sources) != refs
                or any(
                    not isinstance(ref, Mapping) or ref.get("type") != "item"
                    for ref in episode.get("refs", [])
                )
                or any(
                    source not in events
                    or event_provenance(events[source]) != "simulation"
                    for source in sources
                )
            ):
                continue
            if not episode.get("validUntil"):
                if self.superseder is None:
                    raise RuntimeError(
                        "Native memory correction is unavailable; simulated memory was not invalidated."
                    )
                result = self.superseder(agent_id, episode_id)
                if not isinstance(result, Mapping) or not result.get("validUntil"):
                    raise RuntimeError(
                        "Native memory supersession did not confirm invalidation."
                    )
            correction = {
                "episodeId": episode_id,
                "receiptId": str(receipt.get("receiptId") or ""),
                "sourceEventIds": sources,
                "reason": "schedule_simulation",
                "status": "applied",
                "correctedAt": self.now_iso(),
            }
            # No memory body is copied. The original episode and source event remain authoritative.
            self.store.append_jsonl(agent_id, CORRECTION_LEDGER, correction)
            corrections.append(correction)
            applied.add(episode_id)
        return corrections
