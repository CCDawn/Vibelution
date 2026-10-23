from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import git_history_bridge as bridge
from scripts import local_quality_gate as gate


HUMAN = b"Fixture Human <fixture-human@example.test>"
OTHER = b"Other Human <other-human@example.test>"
BOT = b"Cursor <cursoragent@cursor.com>"
DATE = b" 1000000000 +0800"


class Repository:
    def __init__(self, path: Path):
        self.path = path
        path.mkdir()
        # A pre-commit pytest process can inherit GIT_DIR/GIT_INDEX_FILE from
        # the real checkout. Never let fixture init/config/objects reach it.
        self.env = gate.git_hook_isolated_environment()
        for role in ("AUTHOR", "COMMITTER"):
            for field in ("NAME", "EMAIL", "DATE"):
                self.env.pop(f"GIT_{role}_{field}", None)
        self.git("init", "--initial-branch=main")
        self.tree = self.git("mktree", data=b"100644 blob " + self.git("hash-object", "-w", "--stdin", data=b"tracked\n").strip() + b"\tfile.txt\n").decode().strip()

    def git(self, *args: str, data: bytes | None = None) -> bytes:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-c", "user.name=Fixture Human", "-c",
             "user.email=fixture-human@example.test", "-c", "core.hooksPath=", *args],
            cwd=self.path, env=self.env, input=data, capture_output=True,
            **gate.no_window_subprocess_kwargs(),
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        return result.stdout

    def commit(self, parents=(), *, author=OTHER, committer=HUMAN, message=b"message\n", signed=False) -> str:
        headers = [b"tree " + self.tree.encode(), *[b"parent " + parent.encode() for parent in parents],
                   b"author " + author + DATE, b"committer " + committer + b" 1000000100 -0330",
                   b"encoding UTF-8", b"x-preserved-header raw-byte-value"]
        if signed:
            headers.extend([b"gpgsig -----BEGIN PGP SIGNATURE-----", b" fake-signature", b" -----END PGP SIGNATURE-----",
                            b"gpgsig-sha256 second-signature", b" second-continuation"])
        raw = b"\n".join(headers) + b"\n\n" + message
        return self.git("hash-object", "-w", "-t", "commit", "--stdin", data=raw).decode().strip()

    def raw(self, oid: str) -> bytes:
        return self.git("cat-file", "commit", oid)

    def backup(self, oid: str, name="original") -> dict[str, str]:
        ref = f"refs/backup/history-bridge/{name}"
        self.git("update-ref", ref, oid)
        return {ref: oid}

    def rewrite(self, oldmain: str, fixes: dict[str, bytes], *, name="one", seed=None):
        return bridge.rewrite_commit_dag(
            self.path, oldmain, author_fixes=fixes, backup_zip=self.path.parent / f"{name}.zip",
            receipt_path=self.path.parent / f"{name}.json", backup_refs=self.backup(oldmain, name), seed_map=seed,
        )


@pytest.fixture
def dag(tmp_path):
    repo = Repository(tmp_path / "repo")
    root = repo.commit(message=b"human root\n\nCo-authored-by: Real Person <real@example.test>\n", signed=True)
    bot = repo.commit([root], author=BOT, message="作者修复\n\nCo-authored-by: Real Person <real@example.test>\n".encode(), signed=True)
    left = repo.commit([bot], message=b"left\r\nmessage\n", signed=True)
    side = repo.commit([root], message=b"side\n")
    merge = repo.commit([left, side], message=b"merge\n", signed=True)
    task = repo.commit([bot], message=b"task own work\n", signed=True)
    repo.git("update-ref", "refs/heads/main", merge)
    repo.git("update-ref", "refs/heads/task", task)
    repo.git("reset", "--hard", merge)
    return repo, {"root": root, "bot": bot, "left": left, "side": side, "merge": merge, "task": task}


def _snapshot(repo: Repository):
    gitdir = repo.path / ".git"
    return (
        repo.git("for-each-ref", "--format=%(refname) %(objectname)"),
        (gitdir / "HEAD").read_bytes(), (gitdir / "index").read_bytes(),
        repo.git("status", "--porcelain=v1", "-z"),
        {path.name: path.read_bytes() for path in repo.path.iterdir() if path.is_file()},
    )


def test_raw_dag_rewrite_preserves_metadata_merges_and_dirty_checkout(dag):
    repo, ids = dag
    (repo.path / "file.txt").write_bytes(b"staged\n")
    repo.git("add", "file.txt")
    (repo.path / "file.txt").write_bytes(b"dirty after staged\n")
    (repo.path / "untracked.txt").write_bytes(b"keep untracked\n")
    refs = repo.backup(ids["merge"])
    before = _snapshot(repo)
    receipt = bridge.rewrite_commit_dag(
        repo.path, ids["merge"], author_fixes={ids["bot"]: HUMAN},
        backup_zip=repo.path.parent / "backup.zip", receipt_path=repo.path.parent / "receipt.json", backup_refs=refs,
    )
    assert _snapshot(repo) == before
    assert receipt.mapping[ids["root"]] == ids["root"]
    assert receipt.mapping[ids["side"]] == ids["side"]
    assert receipt.newmain != ids["merge"]
    bot_raw = repo.raw(receipt.mapping[ids["bot"]])
    expected = repo.raw(ids["bot"]).replace(b"author " + BOT + DATE, b"author " + HUMAN + DATE)
    expected = b"\n".join(line for line in expected.split(b"\n") if not line.startswith((b"gpgsig ", b"gpgsig-sha256 ", b" ")))
    assert bot_raw == expected
    assert b"Co-authored-by: Real Person <real@example.test>" in bot_raw
    assert b"gpgsig " in repo.raw(ids["root"])
    assert b"gpgsig " not in repo.raw(receipt.newmain)
    assert bridge._parents(repo.raw(receipt.newmain)) == [receipt.mapping[ids["left"]], ids["side"]]
    assert repo.raw(receipt.mapping[ids["left"]]).endswith(b"left\r\nmessage\n")
    with zipfile.ZipFile(receipt.backup_zip) as archive:
        for old in receipt.mapping:
            assert archive.read(f"commits/{old}") == repo.raw(old)
    loaded = bridge.read_mapping_receipt(repo.path, receipt.receipt_path)
    assert loaded.digest == receipt.digest
    assert bridge.task_base(repo.path, receipt, ids["task"]) == ids["bot"]


def test_task_translation_preserves_task_and_unknown_human_merge_ancestry(dag):
    repo, ids = dag
    receipt = repo.rewrite(ids["merge"], {ids["bot"]: HUMAN})
    foreign_root = repo.commit(message=b"independent human ancestry\n", signed=True)
    foreign_tip = repo.commit([foreign_root], message=b"external work\n")
    task_merge = repo.commit([ids["task"], foreign_tip], message=b"task merged external work\n", signed=True)
    (repo.path / "untracked.txt").write_bytes(b"untouched\n")
    before = _snapshot(repo)
    translated = bridge.translate_task_dag(repo.path, task_merge, receipt)
    assert _snapshot(repo) == before
    assert translated.head != task_merge
    assert translated.mapping[foreign_root] == foreign_root
    assert translated.mapping[foreign_tip] == foreign_tip
    assert bridge._parents(repo.raw(translated.head)) == [translated.mapping[ids["task"]], foreign_tip]
    assert bridge._parents(repo.raw(translated.mapping[ids["task"]])) == [receipt.mapping[ids["bot"]]]
    assert repo.raw(translated.mapping[ids["task"]]).endswith(b"task own work\n")
    assert bridge.translate_task_dag(repo.path, translated.head, receipt).head == translated.head


@pytest.mark.parametrize("role", ["author", "committer", "coauthor", "coauthor-middle"])
def test_unknown_bot_is_rejected_before_backup_or_objects(dag, role):
    repo, ids = dag
    kwargs = {"author": BOT} if role == "author" else {"committer": BOT} if role == "committer" else {
        "message": b"prose\n\n  cO-aUtHoReD-bY: Bot <NOREPLY@COMMANDCODE.AI>\n" + (b"later prose\n" if role == "coauthor-middle" else b"")}
    unknown = repo.commit([ids["merge"]], **kwargs)
    refs = repo.backup(unknown)
    with pytest.raises(bridge.HistoryBridgeError, match="unknown bot"):
        bridge.rewrite_commit_dag(repo.path, unknown, author_fixes={ids["bot"]: HUMAN},
                                  backup_zip=repo.path.parent / "bad.zip", receipt_path=repo.path.parent / "bad.json", backup_refs=refs)
    assert not (repo.path.parent / "bad.zip").exists()
    assert not (repo.path.parent / "bad.json").exists()


def test_task_unknown_bot_is_not_admitted_by_known_oldmain(dag):
    repo, ids = dag
    receipt = repo.rewrite(ids["merge"], {ids["bot"]: HUMAN})
    unknown = repo.commit([ids["task"]], author=BOT)
    before = _snapshot(repo)
    with pytest.raises(bridge.HistoryBridgeError, match="unknown bot"):
        bridge.translate_task_dag(repo.path, unknown, receipt)
    assert _snapshot(repo) == before


def test_author_fix_must_equal_human_committer(dag):
    repo, ids = dag
    with pytest.raises(bridge.HistoryBridgeError, match="human committer"):
        repo.rewrite(ids["merge"], {ids["bot"]: OTHER})


def _resign_json(path: Path, mutate):
    payload = json.loads(path.read_text())
    mutate(payload)
    payload.pop("digest", None)
    payload["digest"] = hashlib.sha256(bridge._canonical(payload)).hexdigest()
    path.write_text(json.dumps(payload))


@pytest.mark.parametrize("tamper", ["digest", "mapping", "zip", "ref", "inventory"])
def test_receipt_revalidates_tampered_evidence_even_with_recomputed_digest(dag, tamper):
    repo, ids = dag
    receipt = repo.rewrite(ids["merge"], {ids["bot"]: HUMAN})
    if tamper == "digest":
        value = json.loads(receipt.receipt_path.read_text())
        value["newmain"] = ids["root"]
        receipt.receipt_path.write_text(json.dumps(value))
    elif tamper == "mapping":
        _resign_json(receipt.receipt_path, lambda value: value["mapping"].__setitem__(ids["left"], ids["side"]))
    elif tamper == "zip":
        with receipt.backup_zip.open("ab") as target:
            target.write(b"changed archive")
    elif tamper == "inventory":
        _resign_json(receipt.receipt_path, lambda value: value["mapping"].pop(ids["root"]))
    else:
        repo.git("update-ref", next(iter(receipt.backup_refs)), ids["root"])
    with pytest.raises(bridge.HistoryBridgeError):
        bridge.read_mapping_receipt(repo.path, receipt.receipt_path)


def test_verified_seed_is_composed_and_forged_seed_rejected(dag):
    repo, ids = dag
    original = repo.rewrite(ids["merge"], {ids["bot"]: HUMAN}, name="original")
    repaired = repo.rewrite(original.newmain, {ids["bot"]: HUMAN}, name="next", seed=dict(original.mapping))
    assert repaired.mapping[ids["merge"]] == original.newmain == repaired.newmain
    assert repaired.mapping[ids["bot"]] == original.mapping[ids["bot"]]
    forged = dict(original.mapping)
    forged[ids["left"]] = ids["side"]
    with pytest.raises(bridge.HistoryBridgeError, match="raw commit transformation mismatch"):
        repo.rewrite(original.newmain, {ids["bot"]: HUMAN}, name="forged", seed=forged)


@pytest.mark.parametrize("ancestor", ["bot", "missing", "human"])
def test_partial_seed_checks_unmapped_raw_ancestry_before_becoming_boundary(dag, ancestor):
    repo, ids = dag
    if ancestor == "missing":
        parent = "a" * 40
    else:
        parent = repo.commit(author=BOT if ancestor == "bot" else OTHER)
    seed_tip = repo.commit([parent], message=b"human partial seed\n")
    if ancestor == "human":
        receipt = repo.rewrite(ids["merge"], {ids["bot"]: HUMAN}, seed={seed_tip: seed_tip})
        assert receipt.mapping[seed_tip] == seed_tip
        assert bridge.translate_task_dag(repo.path, seed_tip, receipt).head == seed_tip
    else:
        with pytest.raises(bridge.HistoryBridgeError, match="unknown bot|missing or invalid raw commit"):
            repo.rewrite(ids["merge"], {ids["bot"]: HUMAN}, seed={seed_tip: seed_tip})
        assert not (repo.path.parent / "one.zip").exists()


def test_missing_task_ancestor_and_ambiguous_task_base_are_rejected(dag):
    repo, ids = dag
    receipt = repo.rewrite(ids["merge"], {ids["bot"]: HUMAN})
    missing = "a" * 40
    task = repo.commit([ids["task"], missing])
    with pytest.raises(bridge.HistoryBridgeError, match="missing or invalid raw commit"):
        bridge.translate_task_dag(repo.path, task, receipt)
    # Criss-cross merges have two best common ancestors; claiming one would
    # silently omit part of the actual task fork.
    first = repo.commit([ids["left"], ids["side"]], message=b"first crossing\n")
    second = repo.commit([ids["side"], ids["left"]], message=b"second crossing\n")
    crossed = repo.rewrite(first, {ids["bot"]: HUMAN}, name="crossed")
    with pytest.raises(bridge.HistoryBridgeError, match="exactly one"):
        bridge.task_base(repo.path, crossed, second)


def test_replace_refs_and_mailmap_do_not_change_raw_repair(dag):
    repo, ids = dag
    fake = repo.commit(message=b"fake replacement\n")
    repo.git("replace", ids["bot"], fake)
    (repo.path / ".mailmap").write_text("Wrong Person <wrong@example.test> Fixture Human <fixture-human@example.test>\n")
    receipt = repo.rewrite(ids["merge"], {ids["bot"]: HUMAN})
    assert b"author " + HUMAN + DATE in repo.raw(receipt.mapping[ids["bot"]])
    assert b"fake replacement" not in repo.raw(receipt.mapping[ids["bot"]])


def test_active_pointer_requires_common_directory_receipt_and_exact_digest(dag):
    repo, ids = dag
    assert bridge.load_active_mapping(repo.path) is None
    directory = repo.path / ".git" / "vibelution-cache" / "history-bridge"
    directory.mkdir(parents=True)
    receipt = bridge.rewrite_commit_dag(
        repo.path, ids["merge"], author_fixes={ids["bot"]: HUMAN}, backup_zip=directory / "backup.zip",
        receipt_path=directory / "receipt.json", backup_refs=repo.backup(ids["merge"]),
    )
    pointer = directory / "active.json"
    pointer.write_text(json.dumps({"receipt": str(receipt.receipt_path), "digest": receipt.digest}))
    assert bridge.load_active_mapping(repo.path) is None  # Prepared, main CAS has not occurred.
    old_progress = repo.commit([ids["merge"]], message=b"normal old-main progress\n")
    repo.git("update-ref", "refs/heads/main", old_progress)
    assert bridge.load_active_mapping(repo.path) is None
    repo.git("update-ref", "refs/heads/main", receipt.newmain)
    assert bridge.load_active_mapping(repo.path).digest == receipt.digest
    new_progress = repo.commit([receipt.newmain], message=b"normal new-main progress\n")
    repo.git("update-ref", "refs/heads/main", new_progress)
    assert bridge.load_active_mapping(repo.path).digest == receipt.digest
    unrelated = repo.commit(message=b"unrelated main\n")
    repo.git("update-ref", "refs/heads/main", unrelated)
    with pytest.raises(bridge.HistoryBridgeError, match="unrelated to current main"):
        bridge.load_active_mapping(repo.path)
    repo.git("update-ref", "refs/heads/main", receipt.newmain)
    pointer.write_text(json.dumps({"receipt": str(receipt.receipt_path), "digest": "invalid"}))
    with pytest.raises(bridge.HistoryBridgeError, match="digest mismatch"):
        bridge.load_active_mapping(repo.path)
    pointer.write_text(json.dumps({"receipt": str(repo.path.parent / "outside.json"), "digest": receipt.digest}))
    with pytest.raises(bridge.HistoryBridgeError, match="inside the common"):
        bridge.load_active_mapping(repo.path)
    pointer.write_text("not JSON")
    with pytest.raises(bridge.HistoryBridgeError):
        bridge.load_active_mapping(repo.path)


def test_fixture_git_environment_isolated_from_real_checkout(tmp_path, monkeypatch):
    inherited = tmp_path / "unrelated"
    monkeypatch.setenv("GIT_DIR", str(inherited))
    monkeypatch.setenv("GIT_INDEX_FILE", str(inherited / "index"))
    monkeypatch.setenv("GIT_COMMON_DIR", str(inherited))
    repo = Repository(tmp_path / "fixture")
    root = repo.commit()
    receipt = repo.rewrite(root, {})
    assert receipt.newmain == root
    assert not inherited.exists()
