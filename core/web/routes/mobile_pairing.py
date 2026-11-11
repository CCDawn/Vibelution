"""Phone pairing routes: the desktop mints a code, the phone redeems it.

Two endpoints with deliberately different trust levels:

- ``POST /api/mobile/pairing/code`` keeps the normal control-token gate. Only
  the desktop workbench (which already holds the token) can mint a code.
- ``POST /api/mobile/pairing/claim`` is token-exempt because the phone has no
  token yet. Its safety comes from the code itself: single use, five minute
  TTL, rate limited, and unreachable except over the loopback/trusted surface
  that :mod:`core.web.control` already enforces.
"""

from __future__ import annotations

import socket
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import mobile_pairing_service

router = APIRouter()


class PairingClaimPayload(BaseModel):
    code: str = ""


def _local_lan_address() -> str:
    """Best-effort LAN address the phone can reach.

    A UDP socket connect() performs no traffic but still resolves the routing
    table, which is the portable way to find the outbound interface address.
    Falls back to loopback so the endpoint always answers with something the
    caller can act on.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 65535))
            address = probe.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    return address or "127.0.0.1"


def _request_port(request: Request) -> int:
    port = request.url.port
    if port:
        return int(port)
    return 443 if request.url.scheme == "https" else 80


def _pairing_payload(*, host: str, port: int, code: str) -> str:
    base_url = f"http://{host}:{port}"
    return f"vibelution://pair?v=1&u={quote(base_url, safe='')}&c={code}"


@router.post("/mobile/pairing/code")
def mobile_pairing_code_create(request: Request) -> dict[str, Any]:
    """Mint a one-shot pairing code. The phone never sees the token here."""
    host = _local_lan_address()
    port = _request_port(request)
    session = mobile_pairing_service.create_pairing_code(host=host, port=port)
    return {
        "code": mobile_pairing_service.format_pairing_code(session["code"]),
        "expiresAt": session["expiresAt"],
        "ttlSeconds": mobile_pairing_service.PAIRING_TTL_SECONDS,
        "host": host,
        "port": port,
        "payload": _pairing_payload(host=host, port=port, code=session["code"]),
    }


@router.post("/mobile/pairing/claim")
def mobile_pairing_claim(payload: PairingClaimPayload) -> dict[str, Any]:
    """Redeem a pairing code for this instance's control token."""
    session = mobile_pairing_service.claim_pairing_code(payload.code)
    if session is None:
        raise HTTPException(status_code=403, detail="配对码无效、已过期或尝试次数过多")
    return {
        "ok": True,
        "baseUrl": f"http://{session['host']}:{session['port']}",
        "header": CONTROL_TOKEN_HEADER,
        "controlToken": get_control_token(),
    }
