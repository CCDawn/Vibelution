"""One encrypted credential authority, with cross-process transactions.

Only ciphertext is ever passed to the shared atomic writer. DPAPI uses the
current Windows user and forbids interactive prompts. Other OSes fail closed
until a real OS secret backend is supplied; there is no plaintext fallback.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from config.paths import resolve_config_path
from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock

from .errors import ChatGPTSubscriptionError


class Encryption(Protocol):
    name: str

    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class DPAPIEncryption:
    name = "windows-dpapi-current-user-v1"

    def _crypt(self, value: bytes, *, decrypt: bool) -> bytes:
        if os.name != "nt":
            raise ChatGPTSubscriptionError("storage_unavailable")
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = Blob()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        fn = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
        # CRYPTPROTECT_UI_FORBIDDEN; deliberately omit LOCAL_MACHINE.
        if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise ChatGPTSubscriptionError("storage_corrupt" if decrypt else "storage_unavailable")
        try:
            return ctypes.string_at(output.data, output.size)
        finally:
            if output.data:
                # Best effort clear the native plaintext allocation before releasing it.
                ctypes.memset(output.data, 0, output.size)
                kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))

    def protect(self, value: bytes) -> bytes:
        return self._crypt(value, decrypt=False)

    def unprotect(self, value: bytes) -> bytes:
        return self._crypt(value, decrypt=True)


class CredentialStorage:
    def __init__(self, root: Path | None = None, *, encryption: Encryption | None = None):
        self.root = (Path(root) if root is not None else resolve_config_path().parent / "credentials" / "chatgpt").resolve()
        self.path = self.root / "state.json"
        self.encryption = encryption if encryption is not None else DPAPIEncryption()

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        """Call save explicitly inside this lock after a successful mutation."""
        try:
            if isinstance(self.encryption, DPAPIEncryption) and os.name != "nt":
                raise ChatGPTSubscriptionError("storage_unavailable")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                self.root.chmod(0o700)
            with cross_process_file_lock(self.path, timeout=45.0):
                yield self._read()
        except ChatGPTSubscriptionError:
            raise
        except TimeoutError:
            raise ChatGPTSubscriptionError("busy") from None
        except OSError:
            raise ChatGPTSubscriptionError("storage_failed") from None

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            state: dict[str, Any] = {"hostId": f"urn:uuid:{uuid.uuid4()}", "generation": 0}
            self.save(state)
            return state
        try:
            if self.path.stat().st_size > 1024 * 1024:
                raise ValueError("size")
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if envelope["schemaVersion"] != 1 or envelope["encryption"] != self.encryption.name:
                raise ValueError("schema")
            plaintext = self.encryption.unprotect(base64.b64decode(envelope["ciphertext"], validate=True))
            state = json.loads(plaintext)
            host_id = state["hostId"]
            if not isinstance(host_id, str) or not host_id.startswith("urn:uuid:"):
                raise ValueError("host")
            parsed_host = uuid.UUID(host_id.removeprefix("urn:uuid:"))
            if parsed_host.version != 4:
                raise ValueError("host version")
            if not isinstance(state.get("generation"), int):
                raise TypeError("generation")
            return state
        except ChatGPTSubscriptionError:
            raise
        except Exception:  # noqa: BLE001 - Includes OS-backend/decryption failures; never echo ciphertext or plaintext.
            raise ChatGPTSubscriptionError("storage_corrupt") from None

    def save(self, state: dict[str, Any]) -> None:
        try:
            ciphertext = self.encryption.protect(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if not ciphertext:
                raise ValueError("empty ciphertext")
            envelope = {"schemaVersion": 1, "encryption": self.encryption.name,
                        "ciphertext": base64.b64encode(ciphertext).decode("ascii")}
            if len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) > 1024 * 1024 - 1024:
                raise ValueError("encrypted credential record exceeds its read limit")
            atomic_write_json(self.path, envelope, strict_replace=True)
            if os.name != "nt":
                self.path.chmod(0o600)
        except ChatGPTSubscriptionError:
            raise
        except Exception:  # noqa: BLE001 - An injected secure backend must not leak its exception contents.
            raise ChatGPTSubscriptionError("storage_failed") from None
