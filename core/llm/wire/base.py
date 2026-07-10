"""Provider-neutral wire adapter protocol."""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Protocol, Sequence

from ..protocols import WireProtocol
from ..semantic_messages import InvocationScope, SemanticModelRequest
from ..types import CanonicalToolResult, LLMProtocolEvent, TurnOutcome
from .types import BuiltPayload


class WireAdapter(Protocol):
    adapter_id: str
    wire_protocol: WireProtocol

    def encode_request(self, request: SemanticModelRequest, *, route: Any) -> BuiltPayload: ...

    def decode_response(self, response: Any, *, route: Any, scope: InvocationScope) -> TurnOutcome: ...

    def decode_stream(
        self,
        events: Iterable[Any],
        *,
        route: Any,
        scope: InvocationScope,
    ) -> Iterator[LLMProtocolEvent]: ...

    def encode_tool_results(self, results: Sequence[CanonicalToolResult]) -> list[Any]: ...
