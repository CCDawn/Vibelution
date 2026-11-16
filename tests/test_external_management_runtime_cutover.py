import shutil
import json
from types import SimpleNamespace

import pytest

from core.web.services.external_management.service import ManagementError, TargetIdentity, build_default_service
from core.web.services.external_management.store import Store, digest
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope


@pytest.mark.parametrize("revoked", [False, True])
def test_runtime_cutover_recovers_only_server_owned_authority(tmp_path, monkeypatch, revoked):
    import vibelution_storage as paths

    root = tmp_path / "checkout"
    instance = tmp_path / "instance"
    runtime = instance / "runtime"
    previous = root / ".runtime"
    data = instance / "data"
    canonical = SimpleNamespace(project_root=root, instance_home=instance, runtime=runtime)
    active = SimpleNamespace(runtime=previous)
    binding = {"projectId": "test-project", "instanceId": "test-instance"}
    monkeypatch.setattr(paths, "load_project_identity", lambda _: SimpleNamespace(project_id=binding["projectId"]))
    monkeypatch.setattr(paths, "instance_id_for_project", lambda _: binding["instanceId"])
    monkeypatch.setattr(paths, "resolve_project_storage_paths", lambda _: canonical)
    monkeypatch.setattr(paths, "resolve_active_project_storage_paths", lambda _: active)
    monkeypatch.setattr(paths, "resolve_project_data_home", lambda _: data)
    migrated = False
    monkeypatch.setattr(paths, "storage_migration_complete", lambda _: migrated)
    old = Store(previous / "external_management")
    subject = "ops-" + "b" * 32
    capability = "s" * 48
    scopes = ["agents:read", "teams:directory:read"]
    client = "original-client"
    signature = digest([str(root).casefold(), str(data).casefold(), str(previous).casefold(), binding])
    grant = {"subject_id": subject, "subject_capability": capability, "binding": binding,
             "authority": signature, "scopes": scopes}
    original = build_default_service(root)
    assert original.root == old.root
    if revoked:
        # Create revocation with its real proof via the previous owner.
        from core.web.services.external_management.service import ManagementService
        old_service = ManagementService(old.root, identity=lambda: TargetIdentity(binding, signature), native=None)
        old_service.store.write(old.path("subjects", subject), grant)
        with server_operator_scope("operator-test", roles=("operator",)):
            old_service._authorization_reductions().invoke(
                subject, capability, "authorization_revoke", "revoke-before-cutover", binding,
                expected_scopes=scopes, expected_grant_revision=0,
            )
    else:
        old.write(old.path("subjects", subject), grant)
    old.write(old.path("clients", client), {"subject_id": subject})
    receipt = {"historical": True}
    old.write(old.path("requests", "original"), receipt)

    # Existing storage migration copies the original files before switching.
    shutil.copytree(old.root, runtime / "external_management")
    manifest = instance / "migrations" / "manifest.jsonl"
    manifest.parent.mkdir()
    relative = old.path("subjects", subject).relative_to(previous)
    manifest.write_text(json.dumps({"category": "runtime", "relative_path": relative.as_posix(),
        "source": str(previous / relative), "destination": str(runtime / relative)}) + "\n", encoding="utf-8")
    paths.storage_migration_state_path(canonical).write_text(json.dumps({"manifestPath": str(manifest)}), encoding="utf-8")
    active.runtime = runtime
    migrated = True
    service = build_default_service(root)
    assert service.root != original.root
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        original.binding()
    assert service.root == runtime / "external_management"
    assert service.store.read(service.store.path("requests", "original")) == receipt
    assert service.native.operation_receipts().root == service.root / "native_outcomes"
    if revoked:
        with pytest.raises(ManagementError, match="SUBJECT_REVOKED"):
            service.authorization_status(subject, capability)
        with server_operator_scope("operator-test", roles=("operator",)):
            receipt = service._authorization_reductions().receipt(
                subject, capability, "authorization_revoke", "revoke-before-cutover",
            )
        assert receipt["authorization"]["revoked"] is True
        return
    assert service.authorization_status(subject, capability)["scopes"] == scopes
    assert service.bind({"client_id": client, "expected_binding": binding, "scopes": scopes})["subject_id"] == subject
    active.runtime = instance / "next-runtime"
    assert build_default_service(root).authorization_status(subject, capability)["scopes"] == scopes
    active.runtime = runtime
    with pytest.raises(ManagementError, match="SUBJECT_DENIED"):
        service.authorization_status("ops-" + "c" * 32, capability)
    with monkeypatch.context() as other_data:
        other_data.setattr(paths, "resolve_project_data_home", lambda _: tmp_path / "different-data")
        with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
            build_default_service(root).authorization_status(subject, capability)
    manifest.unlink()
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        service.authorization_status(subject, capability)
