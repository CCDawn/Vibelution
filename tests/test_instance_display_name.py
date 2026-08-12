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
    assert workbench_window_title(MAIN_SHORT_NAME) == "主 台"
    assert launcher_window_title(MAIN_SHORT_NAME) == "主 控"


def test_slot_supervisor_registry_compresses_to_supervisor():
    assert (
        instance_short_name_base(
            kind="worktree",
            branch="codex/slot-supervisor-registry",
            slug="slot-supervisor-registry",
        )
        == "supervisor"
    )


def test_feat_task_drops_feat_prefix():
    assert instance_short_name_base(kind="worktree", branch="codex/feat-task", slug="feat-task") == "task"


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
            "branch": "test/slot-supervisor-s1s8-b",
            "path": "C:/pool/slot-supervisor-s1s8-b",
            "current": False,
        },
    ]

    assign_instance_display_names(items)

    assert items[0]["shortName"] == "主"
    assert items[0]["workbenchTitle"] == "主 台"
    assert items[0]["launcherTitle"] == "主 控"
    assert items[1]["shortName"] == "supervisor"
    assert items[2]["shortName"] == "supervisor-2"
    assert current_instance_display(items)["workbenchTitle"] == "主 台"
