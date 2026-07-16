from core.research.question_tree import ResearchQuestionTreeStore


def test_question_tree_generates_stable_multi_perspective_queries(tmp_path):
    store = ResearchQuestionTreeStore(tmp_path)

    first = store.create(
        "research-team",
        research_question="Can predictive coding improve masked image reconstruction?",
        created_by_agent="agent-source-finder",
    )
    duplicate = store.create(
        "research-team",
        research_question="Can predictive coding improve masked image reconstruction?",
        created_by_agent="agent-source-finder",
    )

    assert duplicate["questionTreeId"] == first["questionTreeId"]
    assert len(first["perspectives"]) == 5
    assert {item["perspectiveId"] for item in first["perspectives"]} == {
        "mechanism",
        "empirical",
        "alternatives",
        "implementation",
        "falsification",
    }
    assert all(first["researchQuestion"] in item["query"] for item in first["perspectives"])
    assert first["coverage"]["requiredPerspectiveCoverage"] == 1.0
    assert first["boundaries"]["externalSearchTriggered"] is False
    assert first["boundaries"]["writesFormalKnowledge"] is False
    assert len(store.list("research-team")) == 1


def test_question_tree_accepts_bounded_custom_perspective_without_duplicates(tmp_path):
    store = ResearchQuestionTreeStore(tmp_path)

    tree = store.create(
        "research-team",
        research_question="How robust is the proposed algorithm?",
        created_by_agent="agent-source-finder",
        custom_perspectives=[
            {"perspectiveId": "clinical_transfer", "label": "Clinical transfer", "prompt": "Assess transfer limits"},
            {"perspectiveId": "clinical_transfer", "label": "Duplicate", "prompt": "Duplicate"},
        ],
    )

    assert [item["perspectiveId"] for item in tree["perspectives"]].count("clinical_transfer") == 1
    assert tree["coverage"]["totalPerspectiveCount"] == 6


def test_question_tree_list_is_team_scoped(tmp_path):
    store = ResearchQuestionTreeStore(tmp_path)
    store.create("team-a", research_question="Question A?", created_by_agent="agent-a")
    store.create("team-b", research_question="Question B?", created_by_agent="agent-b")

    assert [item["researchQuestion"] for item in store.list("team-a")] == ["Question A?"]
