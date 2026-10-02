from core.infrastructure.instance_display_name import (
    MAIN_SHORT_NAME,
    assign_instance_display_names,
    current_instance_display,
    instance_short_name_base,
    launcher_window_title,
    workbench_window_title,
)


def test_main_kind_uses_fixed_short_name():
    assert instance_short_name_base(kind="main", branch="main") == MAIN_SHORT_NAME
    assert workbench_window_title(MAIN_SHORT_NAME) == "main 台"
    assert launcher_window_title(MAIN_SHORT_NAME) == "main 控"


def test_worktree_keeps_full_branch_name():
    assert (
        instance_short_name_base(
            kind="worktree",
            branch="codex/slot-supervisor-registry",
        )
        == "branch+codex/slot-supervisor-registry"
    )


def test_feat_task_keeps_codex_prefix():
    assert (
        instance_short_name_base(kind="worktree", branch="codex/feat-task")
        == "branch+codex/feat-task"
    )


def test_retired_uses_retired_prefix():
    assert instance_short_name_base(kind="retired", path_name="shell-only") == "retired+shell-only"


def test_detached_worktree_falls_back_to_path_name():
    assert (
        instance_short_name_base(
            kind="worktree",
            branch="detached",
            path_name="fix-composer-dialog-chrome",
        )
        == "branch+fix-composer-dialog-chrome"
    )


def test_pool_external_id_stays_out_of_short_name():
    items = [
        {
            "id": "worktree:c:/users/dev/codex-wt/nav-preview/vibelution",
            "kind": "worktree",
            "branch": "detached",
            "path": "C:/Users/dev/codex-wt/nav-preview/Vibelution",
            "current": False,
        }
    ]

    assign_instance_display_names(items)

    short_name = items[0]["shortName"]
    assert short_name == "branch+Vibelution"
    assert "/" not in short_name
    assert ":" not in short_name
    assert "\\" not in short_name


def test_assign_names_disambiguates_collisions_and_marks_current():
    items = [
        {"id": "main", "kind": "main", "branch": "main", "path": "", "current": True},
        {
            "id": "worktree:slot-supervisor-registry",
            "kind": "worktree",
            "branch": "codex/slot-supervisor-registry",
            "path": "C:/pool/slot-supervisor-registry",
            "current": False,
        },
        {
            "id": "worktree:slot-supervisor-s1s8-b",
            "kind": "worktree",
            "branch": "codex/slot-supervisor-registry",
            "path": "C:/pool/slot-supervisor-s1s8-b",
            "current": False,
        },
    ]

    assign_instance_display_names(items)

    assert items[0]["shortName"] == "main"
    assert items[0]["workbenchTitle"] == "main 台"
    assert items[0]["launcherTitle"] == "main 控"
    assert items[1]["shortName"] == "branch+codex/slot-supervisor-registry"
    assert items[2]["shortName"] == "branch+codex/slot-supervisor-registry-2"
    assert current_instance_display(items)["workbenchTitle"] == "main 台"
