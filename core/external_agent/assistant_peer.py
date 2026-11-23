"""Load one operator-enrolled Launcher contact for this MCP connection."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.assistant_runtime.migration_io import read_stable_file, strict_json
from core.assistant_runtime.peer_contacts import PeerContacts


@dataclass(frozen=True)
class AssistantPeerBinding:
    contacts: PeerContacts
    peer_id: str
    credential: str = field(repr=False)

    def describe(self) -> dict:
        return self.contacts.describe(self.peer_id, self.credential)

    def exchange(self, operation: str, request_id: str = "", content: str = "") -> dict:
        return self.contacts.exchange(self.peer_id, self.credential, operation, request_id, content)


def load_assistant_peer_binding(path: Path) -> AssistantPeerBinding:
    # The binding must live in the same private profile as the store. Its
    # location is fixed by the operator command; tool parameters cannot pick it.
    if not path.is_absolute() or path.parent.name != "assistant_peer_grants":
        raise ValueError("PEER_BINDING_UNAVAILABLE")
    try:
        payload = strict_json(read_stable_file(path, max_bytes=2048).raw)
        if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "peerId", "credential"}:
            raise ValueError("PEER_BINDING_UNAVAILABLE")
        if type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1:
            raise ValueError("PEER_BINDING_UNAVAILABLE")
        if not isinstance(payload["peerId"], str) or not isinstance(payload["credential"], str):
            raise ValueError("PEER_BINDING_UNAVAILABLE")
        binding = AssistantPeerBinding(PeerContacts(path.parent.parent), payload["peerId"], payload["credential"])
        binding.describe()
    except (OSError, ValueError):
        raise ValueError("PEER_BINDING_UNAVAILABLE") from None
    return binding
