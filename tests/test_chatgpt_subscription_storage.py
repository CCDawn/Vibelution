from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from core.llm.chatgpt_subscription import ChatGPTSubscriptionError
from core.llm.chatgpt_subscription.storage import CredentialStorage, DPAPIEncryption


class TestEncryption:
    __test__ = False
    name = "synthetic-fernet"

    def __init__(self):
        self.cipher = Fernet(Fernet.generate_key())

    def protect(self, value: bytes) -> bytes:
        return self.cipher.encrypt(value)

    def unprotect(self, value: bytes) -> bytes:
        return self.cipher.decrypt(value)


def test_credentials_are_encrypted_and_host_identity_is_stable(tmp_path):
    encryption = TestEncryption()
    storage = CredentialStorage(tmp_path, encryption=encryption)
    with storage.transaction() as state:
        host_id = state["hostId"]
        state["credentials"] = {"access_token": "synthetic-secret"}
        storage.save(state)
    assert "synthetic-secret" not in storage.path.read_text(encoding="utf-8")
    with CredentialStorage(tmp_path, encryption=encryption).transaction() as state:
        assert state["hostId"] == host_id
        assert state["credentials"]["access_token"] == "synthetic-secret"


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_real_dpapi_roundtrip_uses_ciphertext(tmp_path):
    storage = CredentialStorage(tmp_path, encryption=DPAPIEncryption())
    with storage.transaction() as state:
        state["credentials"] = {"refresh_token": "synthetic-refresh"}
        storage.save(state)
    assert "synthetic-refresh" not in json.dumps(json.loads(storage.path.read_text()))
    with storage.transaction() as state:
        assert state["credentials"]["refresh_token"] == "synthetic-refresh"


def test_config_path_override_owns_default_credential_directory(tmp_path, monkeypatch):
    config_file = tmp_path / "override" / "operator.toml"
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_file))
    storage = CredentialStorage(encryption=TestEncryption())
    assert storage.root == config_file.parent / "credentials" / "chatgpt"
    assert not config_file.exists()


def test_encryption_failure_has_no_plaintext_fallback(tmp_path):
    class BrokenEncryption:
        name = "unavailable"

        def protect(self, value):
            raise OSError("synthetic-secret")

    storage = CredentialStorage(tmp_path, encryption=BrokenEncryption())
    with pytest.raises(ChatGPTSubscriptionError) as raised, storage.transaction():
        pass
    assert raised.value.code == "storage_failed"
    assert "synthetic-secret" not in str(raised.value)
    assert not storage.path.exists()


def test_missing_os_secret_backend_fails_closed_without_creating_credential_file(tmp_path, monkeypatch):
    from core.llm.chatgpt_subscription import ChatGPTSubscriptionAuth
    from core.llm.chatgpt_subscription import storage as storage_module

    auth = ChatGPTSubscriptionAuth(tmp_path / "unsupported")
    monkeypatch.setattr(storage_module, "os", SimpleNamespace(name="posix"))
    assert auth.status()["state"] == "unavailable"
    assert auth.status()["lastError"]["code"] == "storage_unavailable"
    assert not auth.storage.path.exists()
    auth.close()


def test_oversized_encrypted_record_is_rejected_before_replacing_readable_state(tmp_path):
    storage = CredentialStorage(tmp_path, encryption=TestEncryption())
    with storage.transaction() as state:
        before = storage.path.read_bytes()
        state["oversized"] = "x" * (1024 * 1024)
        with pytest.raises(ChatGPTSubscriptionError):
            storage.save(state)
    assert storage.path.read_bytes() == before


def test_corrupt_envelope_is_not_reset_or_overwritten(tmp_path):
    storage = CredentialStorage(tmp_path, encryption=TestEncryption())
    storage.path.write_text('{"schemaVersion":1,"ciphertext":"synthetic-corruption"}')
    before = storage.path.read_bytes()
    with pytest.raises(ChatGPTSubscriptionError) as raised, storage.transaction():
        pass
    assert raised.value.code == "storage_corrupt"
    assert storage.path.read_bytes() == before


def test_failed_atomic_replace_retains_original_credentials(tmp_path, monkeypatch):
    from core.llm.chatgpt_subscription import storage as storage_module

    storage = CredentialStorage(tmp_path, encryption=TestEncryption())
    with storage.transaction() as state:
        state["credentials"] = {"refresh_token": "synthetic-old"}
        storage.save(state)
    before = storage.path.read_bytes()

    def fail(*args, **kwargs):
        assert kwargs["strict_replace"] is True
        raise OSError("synthetic-write-failure")

    monkeypatch.setattr(storage_module, "atomic_write_json", fail)
    with pytest.raises(ChatGPTSubscriptionError), storage.transaction() as state:
        state["credentials"] = {"refresh_token": "synthetic-new"}
        storage.save(state)
    assert storage.path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Real DPAPI across Windows processes")
def test_real_dpapi_and_refresh_rotation_are_shared_across_processes(tmp_path):
    storage = CredentialStorage(tmp_path)
    with storage.transaction() as state:
        state["registration"] = {"clientId": "oaiapp_synthetic", "subject": "synthetic-subject", "email": ""}
        state["credentials"] = {"access_token": "synthetic-old", "refresh_token": "synthetic-old-refresh",
                                "id_token": "synthetic-retained-id", "nonce": "synthetic-nonce", "expires_at": 0,
                                "scopes": ["resource.invoke", "chatgpt.tokens.use.direct"]}
        storage.save(state)
    counter = tmp_path / "synthetic-refresh-count.txt"
    script = '''
import sys, time
from pathlib import Path
import httpx
from core.llm.chatgpt_subscription import ChatGPTSubscriptionAuth
root, counter = Path(sys.argv[1]), Path(sys.argv[2])
def handler(request):
    assert request.url.path == "/api/accounts/oauth/token"
    count = int(counter.read_text()) if counter.exists() else 0
    time.sleep(0.2)
    counter.write_text(str(count + 1))
    return httpx.Response(200, json={"access_token":"synthetic-new", "refresh_token":"synthetic-new-refresh",
        "token_type":"Bearer", "expires_in":3600})
with httpx.Client(transport=httpx.MockTransport(handler)) as client:
    auth = ChatGPTSubscriptionAuth(root, http_client=client)
    assert auth.get_access_token() == "synthetic-new"
print("ok")
'''
    processes = []
    try:
        for _ in range(3):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", script, str(tmp_path), str(counter)],
                cwd=str(Path(__file__).resolve().parents[1]), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            ))
        for process in processes:
            output, error = process.communicate(timeout=25)
            assert process.returncode == 0, error
            assert output.strip() == "ok"
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    assert counter.read_text() == "1"
    with storage.transaction() as state:
        assert state["credentials"]["refresh_token"] == "synthetic-new-refresh"
    assert "synthetic-new-refresh" not in storage.path.read_text()
