"""Trusted all-registration model references; metadata proofs are not grants.

No model-facing API accepts roots. The provider is injected by Launcher main;
the private stored registry includes inactive/offline registrations as well as
the native assistant profile. Deletion additionally requires an owned registry
admission lease and the shared canonical-reference writer fence.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import tomllib

from core.assistant_runtime.migration_io import check_path, read_stable_file, strict_json
from core.infrastructure.model_reference_fence import PublicModelReferenceResolver, model_reference_fence, record_model_retirements
from core.web.services.external_management.store import digest

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}\Z")
_ACTIVE_MUTATION = ContextVar("active_configuration_reference_permit", default=None)


class ConfigurationReferenceError(ValueError):
    def __init__(self, code, proof=None):
        self.code, self.proof = code, proof
        super().__init__(code)


@dataclass(frozen=True)
class ReferenceProof:
    kind: str
    reference: str
    registry_revision: int
    registry_digest: str
    config_hash: str
    digest: str
    complete: bool
    project_count: int
    known_reference_count: int
    issues: tuple[str, ...]
    _config_path: Path = field(repr=False, compare=False)
    _payload_digest: str = field(repr=False, compare=False)

    def summary(self):
        return {"kind": self.kind, "reference": self.reference,
                "registryRevision": self.registry_revision, "registryDigest": self.registry_digest,
                "configHash": self.config_hash, "digest": self.digest,
                "coverage": "complete" if self.complete else "unavailable",
                "projectCount": self.project_count,
                "liveReferenceCount": self.known_reference_count if self.complete else None,
                "knownReferenceCount": self.known_reference_count, "issues": list(self.issues),
                "blocking": not self.complete or bool(self.known_reference_count), "untrustedContent": True}


@dataclass
class ReferenceMutationPermit:
    proof: ReferenceProof
    _post_hash: str | None = None
    _writer_lease: object = field(default=None, repr=False)
    _active: bool = field(default=True, repr=False)

    def summary(self):
        return self.proof.summary()

    def confirm_commit_hash(self, expected_public_hash):
        from config.public_config import public_config_hash
        snapshot = read_stable_file(self.proof._config_path, 16 * 1024 * 1024)
        payload = tomllib.loads(snapshot.raw.decode("utf-8"))
        if (not isinstance(expected_public_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_public_hash)
                or public_config_hash(payload) != expected_public_hash):
            raise ConfigurationReferenceError("REFERENCE_CONFIG_COMMIT_UNCONFIRMED")
        self._post_hash = snapshot.sha256

    def assert_config_unchanged(self):
        current = read_stable_file(self.proof._config_path, 16 * 1024 * 1024)
        if current.sha256 != (self._post_hash or self.proof.config_hash):
            raise ConfigurationReferenceError("REFERENCE_CONFIG_STATE_CHANGED")


def has_active_reference_permit(kind, reference, *, public_config=None, config_path=None):
    """Only the matching config owner may skip a legacy State-taking scan.

    This is not a process-global bypass. Context, target, current config bytes,
    and ownership of the same thread's fence must all match the native permit.
    A mismatched active permit fails before any legacy owner-lock callback.
    """
    permit = _ACTIVE_MUTATION.get()
    if permit is None:
        return False
    from config.paths import resolve_config_path
    path = Path(resolve_config_path() if config_path is None else config_path).resolve()
    if (not permit._active or permit.proof.kind != kind or permit.proof.reference != reference
            or path != permit.proof._config_path.resolve()
            or public_config is not None and digest(public_config) != permit.proof._payload_digest):
        raise ConfigurationReferenceError("REFERENCE_PERMIT_TARGET_MISMATCH")
    permit._writer_lease.assert_owned()
    permit.assert_config_unchanged()
    return True


class StoredConfigurationRegistryProvider:
    """Read Electron main's full stored authority, never its admitted projection.

    The constructor is for trusted host wiring only. In production, main must
    inject its private path and the fixed native root before tools are exposed.
    Reading does not admit projects, initialize their authorities, or grant a
    model permission to access an unapproved project's data.
    """

    def __init__(self, registry_path: Path, native_assistant_root: Path):
        if not Path(registry_path).is_absolute() or not Path(native_assistant_root).is_absolute():
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_UNAVAILABLE")
        self.registry_path, self.native_root = Path(registry_path), Path(native_assistant_root)

    def __call__(self):
        snapshot = read_stable_file(self.registry_path, 4 * 1024 * 1024)
        data = strict_json(snapshot.raw)
        if (not isinstance(data, dict) or set(data) != {"schemaVersion", "revision", "registrations"}
                or type(data["schemaVersion"]) is not int or data["schemaVersion"] != 1
                or type(data["revision"]) is not int or not 0 <= data["revision"] <= 9_007_199_254_740_991
                or not isinstance(data["registrations"], list) or len(data["registrations"]) > 10_000
                or data["revision"] == 0 and data["registrations"]):
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_UNAVAILABLE")
        projects, seen = [], set()
        for row in data["registrations"]:
            if (not isinstance(row, dict) or set(row) != {"integrationRoot", "baseProjectId", "root", "registrationUuid", "active"}
                    or not isinstance(row["baseProjectId"], str) or not _ID.fullmatch(row["baseProjectId"])
                    or not isinstance(row["registrationUuid"], str) or not _UUID.fullmatch(row["registrationUuid"])
                    or row["registrationUuid"] in seen or type(row["active"]) is not bool):
                raise ConfigurationReferenceError("REFERENCE_REGISTRY_UNAVAILABLE")
            for key in ("root", "integrationRoot"):
                value = row[key]
                if not isinstance(value, str) or value != value.strip() or "\0" in value or not Path(value).is_absolute():
                    raise ConfigurationReferenceError("REFERENCE_REGISTRY_UNAVAILABLE")
            seen.add(row["registrationUuid"])
            projects.append({"projectId": f"{row['baseProjectId']}:{row['registrationUuid']}",
                             "root": row["root"], "active": row["active"]})
        return {"schemaVersion": 1, "revision": data["revision"], "complete": True,
                "authorityDigest": snapshot.sha256, "projects": projects, "nativeAssistantRoot": str(self.native_root)}


def _canonical_authority(project, public_config):
    """Resolve existing cutover storage without inheriting native DATA_HOME."""
    import vibelution_storage as storage
    root = check_path(Path(project["root"]))
    root_info = root.stat()
    identity = read_stable_file(root / storage.PROJECT_IDENTITY_RELATIVE_PATH, 64 * 1024)
    paths = storage.resolve_project_storage_paths(root)
    identity_data = strict_json(identity.raw)
    if (not isinstance(identity_data, dict) or type(identity_data.get("schemaVersion")) is not int
            or identity_data["schemaVersion"] != 1 or identity_data.get("projectId") != paths.project_id):
        raise ConfigurationReferenceError("REFERENCE_STORAGE_BINDING_UNAVAILABLE")
    marker = read_stable_file(storage.storage_migration_state_path(paths), 64 * 1024)
    data = strict_json(marker.raw)
    if (not isinstance(data, dict) or type(data.get("schemaVersion")) is not int or data["schemaVersion"] != 1 or data.get("status") != "completed"
            or data.get("projectId") != paths.project_id or data.get("instanceId") != paths.instance_id
            or not isinstance(data.get("projectRoot"), str)
            or not os.path.samefile(check_path(Path(data["projectRoot"])), root)):
        raise ConfigurationReferenceError("REFERENCE_STORAGE_BINDING_UNAVAILABLE")
    override = public_config.get("storage", {}).get("data_home", "")
    if override and (not isinstance(override, str) or Path(override).expanduser().resolve() != paths.data.resolve()):
        raise ConfigurationReferenceError("REFERENCE_STORAGE_BINDING_UNAVAILABLE")
    workspaces, names = _workspace_routes(paths.workspace, paths.runtime)
    return {"binding": {"projectId": paths.project_id, "instanceId": paths.instance_id},
            "routes": workspaces,
            "digest": digest([identity.sha256, marker.sha256, root_info.st_dev, root_info.st_ino, names])}


def _workspace_routes(formal, runtime):
    workspaces = [(formal, runtime)]
    sandbox_root = runtime / "developer-mode" / "sandboxes"
    routes = []
    if sandbox_root.exists():
        check_path(sandbox_root)
        for index, candidate in enumerate(sorted(sandbox_root.iterdir())):
            if index >= 128:
                raise ConfigurationReferenceError("REFERENCE_CONTEXT_LIMIT")
            check_path(candidate)
            if not candidate.is_dir():
                raise ConfigurationReferenceError("REFERENCE_STORAGE_BINDING_UNAVAILABLE")
            workspaces.append((candidate / "workspace", candidate / ".runtime"))
            routes.append(candidate.name)
    return workspaces, routes


class ConfigurationReferenceGuard:
    def __init__(self, registry_provider, *, config_path_provider=None, authority_resolver=None):
        if not callable(registry_provider):
            raise TypeError("Trusted registry provider is required")
        if config_path_provider is None:
            from config.paths import resolve_config_path
            config_path_provider = resolve_config_path
        self.provider, self.config_path = registry_provider, config_path_provider
        self.resolve_authority = authority_resolver or _canonical_authority

    def scan(self, kind, reference):
        from core.web.services.model_reference_service import read_existing_model_reference_metadata
        from config.public_config import UNCONFIGURED_MODEL_REF
        if kind not in {"model", "provider"} or not isinstance(reference, str) or not reference or len(reference) > 320:
            raise ConfigurationReferenceError("INVALID_REFERENCE_TARGET")
        config_path = Path(self.config_path())
        issues, stamps, refs, registry = set(), [], [], None
        config_hash, registry_digest, revision, count = "", "", -1, 0
        try:
            config = read_stable_file(config_path, 16 * 1024 * 1024)
            public_config = tomllib.loads(config.raw.decode("utf-8"))
            config_hash = config.sha256
            providers = public_config["llm"]["providers"]
            if not isinstance(providers, dict):
                raise ValueError("Invalid provider authority")
            resolver = PublicModelReferenceResolver(public_config)
            models = resolver.models
            if (kind == "model" and reference not in models or kind == "provider" and reference not in providers):
                raise ConfigurationReferenceError("INVALID_REFERENCE_TARGET")
            # These are the model-reference fields owned by operator config.
            profiles = public_config.get("llm", {}).get("profiles", {})
            if not isinstance(profiles, dict) or any(not isinstance(row, dict) for row in profiles.values()):
                raise ValueError("Invalid profile authority")
            values = [row.get("model_ref", "") for row in profiles.values()]
            values += [public_config.get("tools", {}).get("image2", {}).get("default_model_ref", ""),
                       public_config.get("git", {}).get("commit_message_model_ref", "")]
            if any(not isinstance(value, str) for value in values):
                raise ValueError("Invalid profile model binding")
            refs.extend(value for value in values if value and value != UNCONFIGURED_MODEL_REF)
        except ConfigurationReferenceError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            issues.add("operator_config_unavailable")
            public_config, models, resolver = {}, set(), None
        try:
            supplied = self.provider()
            registry = supplied
            if isinstance(supplied, dict) and set(supplied) == {"schemaVersion", "leaseId", "revision", "snapshotDigest", "complete", "projects", "nativeAssistantRoot"}:
                if not isinstance(supplied["leaseId"], str) or not 1 <= len(supplied["leaseId"]) <= 160:
                    raise ValueError("Invalid native registry lease")
                if (not isinstance(supplied["projects"], list)
                        or any(not isinstance(row, dict) or set(row) != {"registrationId", "baseProjectId", "root", "active"}
                               for row in supplied["projects"])):
                    raise ValueError("Invalid native registry inventory")
                registry = {"schemaVersion": supplied["schemaVersion"], "revision": supplied["revision"],
                    "authorityDigest": supplied["snapshotDigest"], "complete": supplied["complete"],
                    "projects": [{"projectId": row["registrationId"], "root": row["root"], "active": row["active"]}
                                 for row in supplied["projects"]], "nativeAssistantRoot": supplied["nativeAssistantRoot"]}
            if (not isinstance(registry, dict) or set(registry) != {"schemaVersion", "revision", "complete", "authorityDigest", "projects", "nativeAssistantRoot"}
                    or type(registry["schemaVersion"]) is not int or registry["schemaVersion"] != 1 or registry["complete"] is not True
                    or type(registry["revision"]) is not int or not 0 <= registry["revision"] <= 9_007_199_254_740_991
                    or not isinstance(registry["projects"], list) or len(registry["projects"]) > 10_000
                    or not isinstance(registry["authorityDigest"], str) or not re.fullmatch(r"[a-f0-9]{64}", registry["authorityDigest"])):
                raise ValueError("Incomplete trusted project inventory")
            revision, registry_digest = registry["revision"], registry["authorityDigest"]
            count = len(registry["projects"]) + 1
            projects = list(registry["projects"])
            if any(not isinstance(row, dict) or set(row) != {"projectId", "root", "active"} for row in projects):
                raise ValueError("Invalid trusted registration")
            seen = set()
            for project in projects:
                if (not isinstance(project["projectId"], str) or not _ID.fullmatch(project["projectId"]) or project["projectId"] in seen
                        or project["projectId"] == "launcher-native"
                        or not isinstance(project["root"], str) or not Path(project["root"]).is_absolute()
                        or type(project["active"]) is not bool):
                    raise ValueError("Invalid trusted registration")
                seen.add(project["projectId"])
            native = check_path(Path(registry["nativeAssistantRoot"]))
            projects.append({"projectId": "launcher-native", "root": str(native), "active": True})
            for project in projects:
                try:
                    if project["projectId"] == "launcher-native":
                        workspaces, routes = _workspace_routes(native / "data" / "workspace", native / ".runtime")
                        authority = {"routes": workspaces,
                                     "digest": digest([str(native), native.stat().st_dev, native.stat().st_ino, routes])}
                    else:
                        authority = self.resolve_authority(project, public_config)
                    stamps.append((project["projectId"], authority["digest"]))
                    for workspace, runtime in authority["routes"]:
                        metadata = read_existing_model_reference_metadata(workspace, runtime)
                        stamps.append((project["projectId"], metadata["digest"]))
                        refs.extend(row["modelId"] for row in metadata["references"])
                        issues.update(metadata["issues"])
                except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
                    issues.add("project_metadata_unavailable")
            if self.provider() != supplied:
                issues.add("project_registry_changed")
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
            issues.add("project_registry_unavailable")
        canonical_refs = []
        for model in refs:
            try:
                if resolver is None:
                    raise ValueError("Model resolver unavailable")
                canonical_refs.append(resolver.canonical(model))
            except ValueError:
                issues.add("unresolved_model_reference")
        matches = sum(value == reference if kind == "model" else value.startswith(reference + "/") for value in canonical_refs)
        try:
            if read_stable_file(config_path, 16 * 1024 * 1024).sha256 != config_hash:
                issues.add("operator_config_changed")
        except (OSError, ValueError):
            issues.add("operator_config_unavailable")
        proof_digest = digest([kind, reference, registry_digest, revision, config_hash, sorted(stamps), sorted(issues), sorted(refs), sorted(canonical_refs)])
        return ReferenceProof(kind, reference, revision, registry_digest, config_hash, proof_digest,
            not issues, count, matches, tuple(sorted(issues)), config_path, digest(public_config))

    def assert_unchanged(self, proof):
        current = self.scan(proof.kind, proof.reference)
        if not current.complete or current.digest != proof.digest:
            raise ConfigurationReferenceError("REFERENCE_STATE_CHANGED", current)
        return current

    @contextmanager
    def zero_references(self, kind, reference, *, registry_lease):
        # A raw scan's coverage is NOT a mutation permit. Main must retain its
        # registry admission lease while all canonical reference writers and
        # the existing config transaction share this thread's fence.
        check = getattr(registry_lease, "assert_current", None)
        if not callable(check):
            check = getattr(registry_lease, "assert_owned", None)
        if not callable(check):
            raise ConfigurationReferenceError("REFERENCE_REGISTRY_LEASE_REQUIRED")
        check()
        with model_reference_fence(Path(self.config_path())) as writer_lease:
            check()
            proof = self.scan(kind, reference)
            if not proof.complete:
                raise ConfigurationReferenceError("REFERENCE_COVERAGE_UNAVAILABLE", proof)
            if proof.known_reference_count:
                raise ConfigurationReferenceError("LIVE_MODEL_REFERENCES", proof)
            check()
            self.assert_unchanged(proof)
            writer_lease.assert_owned()
            payload = tomllib.loads(read_stable_file(proof._config_path, 16 * 1024 * 1024).raw.decode("utf-8"))
            affected = [reference] if kind == "model" else [f"{reference}/{key}" for key in payload["llm"]["providers"][reference].get("models", {})]
            try:
                record_model_retirements(affected, config_hash=proof.config_hash,
                    reason="guarded_model_change" if kind == "model" else "guarded_provider_change", config_path=proof._config_path)
            except (OSError, ValueError, TypeError):
                raise ConfigurationReferenceError("REFERENCE_RETIREMENT_AUTHORITY_UNAVAILABLE") from None
            permit = ReferenceMutationPermit(proof, _writer_lease=writer_lease)
            token = _ACTIVE_MUTATION.set(permit)
            try:
                yield permit
                writer_lease.assert_owned()
                permit.assert_config_unchanged()
                check()
            finally:
                permit._active = False
                _ACTIVE_MUTATION.reset(token)
