import json
import os
import time
from pathlib import Path

import pytest

from scripts import prune_instance_storage as prune

PROJECT_ID = "proj-1"


def _instance_dir(projects_home: Path, instance_id: str) -> Path:
    return projects_home / PROJECT_ID / "instances" / instance_id


def _make_instance(projects_home: Path, instance_id: str, *, size_kb: int = 1) -> Path:
    instance_dir = _instance_dir(projects_home, instance_id)
    (instance_dir / "logs").mkdir(parents=True, exist_ok=True)
    (instance_dir / "logs" / "conversations.jsonl").write_text(
        "x" * (size_kb * 1024), encoding="utf-8"
    )
    return instance_dir


def _write_state(
    instance_dir: Path, project_root: str, *, manager_pid: int = 0
) -> None:
    state_path = instance_dir / prune.RUNTIME_MANAGER_STATE_RELATIVE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"projectRoot": project_root, "managerPid": manager_pid}),
        encoding="utf-8",
    )


def _age(instance_dir: Path, days: float) -> None:
    stamp = time.time() - days * 86_400.0
    os.utime(instance_dir / "logs" / "conversations.jsonl", (stamp, stamp))


@pytest.fixture()
def projects_home(tmp_path: Path) -> Path:
    home = tmp_path / "projects"
    (home / PROJECT_ID / "instances").mkdir(parents=True)
    return home


def _verdicts(candidates: list[prune.InstanceCandidate]) -> dict[str, str]:
    return {item.instance_id: item.verdict for item in candidates}


def test_classifies_live_dead_and_unproven_by_recorded_root(
    projects_home: Path, tmp_path: Path
):
    live_root = tmp_path / "live-checkout"
    live_root.mkdir()
    live = _make_instance(projects_home, "aaaaaaaa")
    _write_state(live, str(live_root))

    dead = _make_instance(projects_home, "bbbbbbbb")
    _write_state(dead, str(tmp_path / "deleted-worktree"))

    _make_instance(projects_home, "cccccccc")

    candidates = prune.collect_candidates(projects_home)

    assert _verdicts(candidates) == {
        "aaaaaaaa": prune.LIVE,
        "bbbbbbbb": prune.DEAD,
        "cccccccc": prune.UNPROVEN,
    }


def test_daemon_held_instance_is_kept_even_when_root_is_gone(
    projects_home: Path, tmp_path: Path
):
    instance = _make_instance(projects_home, "dddddddd")
    _write_state(instance, str(tmp_path / "gone"), manager_pid=4242)

    alive = prune.collect_candidates(
        projects_home, process_alive=lambda pid: pid == 4242
    )
    assert _verdicts(alive) == {"dddddddd": prune.DAEMON_ALIVE}

    stopped = prune.collect_candidates(projects_home, process_alive=lambda pid: False)
    assert _verdicts(stopped) == {"dddddddd": prune.DEAD}


def test_current_checkout_instance_is_protected(projects_home: Path, tmp_path: Path):
    instance = _make_instance(projects_home, "eeeeeeee")
    _write_state(instance, str(tmp_path / "gone"))

    candidates = prune.collect_candidates(
        projects_home, protected_instance_ids=frozenset({"eeeeeeee"})
    )

    assert _verdicts(candidates) == {"eeeeeeee": prune.PROTECTED}


def test_unproven_instances_are_only_reclaimed_with_an_explicit_age(
    projects_home: Path,
):
    old = _make_instance(projects_home, "11111111")
    _age(old, days=40)
    _make_instance(projects_home, "22222222")

    without_flag = prune.collect_candidates(projects_home)
    assert _verdicts(without_flag) == {
        "11111111": prune.UNPROVEN,
        "22222222": prune.UNPROVEN,
    }
    assert [item for item in without_flag if item.reclaimable] == []

    with_flag = prune.collect_candidates(projects_home, unproven_older_than_days=30)
    assert _verdicts(with_flag) == {
        "11111111": prune.UNPROVEN_STALE,
        "22222222": prune.UNPROVEN,
    }
    assert [item.instance_id for item in with_flag if item.reclaimable] == ["11111111"]


def test_dry_run_reports_without_deleting(projects_home: Path, tmp_path: Path):
    dead = _make_instance(projects_home, "33333333", size_kb=4)
    _write_state(dead, str(tmp_path / "gone"))

    result = prune.reclaim(prune.collect_candidates(projects_home), apply=False)

    assert result["removed"] == 1
    assert result["freedBytes"] >= 4 * 1024
    assert result["failed"] == []
    assert dead.is_dir()


def test_apply_removes_only_reclaimable_instances(projects_home: Path, tmp_path: Path):
    live_root = tmp_path / "still-here"
    live_root.mkdir()
    live = _make_instance(projects_home, "44444444")
    _write_state(live, str(live_root))

    dead = _make_instance(projects_home, "55555555")
    _write_state(dead, str(tmp_path / "gone"))

    unproven = _make_instance(projects_home, "66666666")

    result = prune.reclaim(prune.collect_candidates(projects_home), apply=True)

    assert result["removed"] == 1
    assert result["failed"] == []
    assert dead.is_dir() is False
    assert live.is_dir() is True
    assert unproven.is_dir() is True


def test_main_defaults_to_dry_run_and_keeps_everything(
    projects_home: Path, tmp_path: Path, capsys
):
    dead = _make_instance(projects_home, "77777777")
    _write_state(dead, str(tmp_path / "gone"))

    exit_code = prune.main(["--projects-home", str(projects_home), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run"
    assert payload["removed"] == 1
    assert payload["freedBytes"] > 0
    assert [item["instance_id"] for item in payload["reclaimable"]] == ["77777777"]
    assert dead.is_dir() is True


def test_apply_through_main_deletes_and_reports(
    projects_home: Path, tmp_path: Path, capsys
):
    dead = _make_instance(projects_home, "88888888")
    _write_state(dead, str(tmp_path / "gone"))

    exit_code = prune.main(["--projects-home", str(projects_home), "--apply", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "apply"
    assert payload["removed"] == 1
    assert dead.is_dir() is False


def test_project_id_filter_limits_the_scan(projects_home: Path, tmp_path: Path, capsys):
    other = projects_home / "proj-2" / "instances" / "99999999"
    other.mkdir(parents=True)
    _write_state(other, str(tmp_path / "gone"))

    dead = _make_instance(projects_home, "aaaa1111")
    _write_state(dead, str(tmp_path / "gone"))

    exit_code = prune.main(
        [
            "--projects-home",
            str(projects_home),
            "--project-id",
            PROJECT_ID,
            "--apply",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item["instance_id"] for item in payload["reclaimable"]] == ["aaaa1111"]
    assert payload["removed"] == 1
    assert dead.is_dir() is False
    assert other.is_dir() is True


def test_main_never_touches_the_current_checkout_instance(
    projects_home: Path, tmp_path: Path, capsys
):
    protected_id = prune.instance_id_for_project(prune.REPO_ROOT)
    instance = _make_instance(projects_home, protected_id, size_kb=2)
    _write_state(instance, str(tmp_path / "gone"))

    exit_code = prune.main(["--projects-home", str(projects_home), "--apply", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 0
    assert protected_id in payload["protectedInstanceIds"]
    assert instance.is_dir() is True


def test_json_report_stays_ascii_for_non_ascii_roots(
    projects_home: Path, tmp_path: Path, capsys
):
    """机器可读输出必须 ASCII：Windows 旧代码页与 CI 解析器都可能读它。"""

    instance = _make_instance(projects_home, "bbbb2222")
    _write_state(instance, str(tmp_path / "已删除的工作树"))

    exit_code = prune.main(["--projects-home", str(projects_home), "--json"])

    assert exit_code == 0
    raw = capsys.readouterr().out
    raw.encode("ascii")  # raises UnicodeEncodeError if any non-ASCII slipped through
    payload = json.loads(raw)
    assert payload["reclaimable"][0]["instance_id"] == "bbbb2222"
