"""Public chat-room HTTP contracts.

Room documents are large and still evolving. Only stable identity fields are
required; extras such as participants, rounds, and projection fields must pass
through. Dual-shape POST /rounds returns a lightweight accept envelope when
Prefer: respond-async is set, and a full room document otherwise. Routes must
use response_model_exclude_unset=True so missing optional fields stay absent
instead of being filled with empty defaults.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class ChatRoomTimelineEvent(BaseModel):
    """One append-only room timeline event.

    ``seq`` is monotonic within the room and doubles as the read cursor unit.
    ``payload`` is type-specific; message events carry the same public shape
    as the room detail message projection. The wire keys ``from``/``to`` are
    keyword-aliased because ``from`` is a Python keyword.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    eventId: str
    roomId: str
    seq: int
    type: str
    roundId: str = ""
    from_id: str = Field(default="", alias="from")
    to: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: str = ""
    schemaVersion: int = 1


class ChatRoomTimelineResponse(BaseModel):
    """Cursor-paged read-only room timeline."""

    model_config = ConfigDict(extra="allow")

    roomId: str
    cursor: int = 0
    limit: int = 0
    events: list[ChatRoomTimelineEvent] = Field(default_factory=list)
    nextCursor: int = 0
    hasMore: bool = False
