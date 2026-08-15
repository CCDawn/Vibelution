"""Public chat-room HTTP contracts.

Room documents are large and still evolving. Only stable identity fields are
required; extras such as participants, rounds, and projection fields must pass
through. Dual-shape POST /rounds returns a lightweight accept envelope when
Prefer: respond-async is set, and a full room document otherwise. Routes must
use response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with empty defaults.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ChatRoomCatalogOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str


class ChatRoomDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    roomId: str


class ChatRoomDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    deleted: bool = True
    roomId: str = ""


class ChatRoomRoundResponse(BaseModel):
    """Lightweight accept envelope or a full room document.

    POST /rounds returns the accept payload when Prefer: respond-async is set,
    and a full room document otherwise. Both shapes must survive.
    """

    model_config = ConfigDict(extra="allow")

    accepted: bool | None = None
    roomId: str = ""
    roundId: str = ""
    activeRoundId: str = ""
    status: str = ""
    topic: str = ""
    mode: str = ""
    purpose: str = ""
    acceptedAt: str = ""
