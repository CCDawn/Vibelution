from core.orchestration.turn_outcome import TurnOutcomeController


def test_stateless_chat_replay_keeps_prior_image_message_once() -> None:
    image_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "请检查这张截图"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
            },
        ],
    }
    history = [
        {"role": "system", "content": "previous system"},
        image_message,
        {"role": "assistant", "content": "我先检查图片。"},
    ]

    messages, resumed = TurnOutcomeController.prepare_turn_messages(
        system_prompt="current system",
        user_prompt="继续根据图片给出结论",
        effective_goal="current request",
        active_turn_messages=history,
        active_turn_goal="previous request",
        build_system_message=lambda content: {"role": "system", "content": content},
        build_external_request_message=lambda content: {"role": "user", "content": content},
        allow_append_user_message=True,
    )

    image_messages = [
        item
        for item in messages
        if isinstance(item, dict)
        and isinstance(item.get("content"), list)
        and any(isinstance(part, dict) and part.get("type") == "image_url" for part in item["content"])
    ]

    assert resumed is True
    assert image_messages == [image_message]
    assert messages[-1] == {"role": "user", "content": "继续根据图片给出结论"}
