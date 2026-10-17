from __future__ import annotations

import pytest

from config.public_config import public_config_hash


@pytest.mark.parametrize(
    ("left", "right"),
    [(1.0, 1), (0.0, 0), (-0.0, 0), (-2.0, -2), (1e20, 10**20)],
)
def test_public_config_hash_treats_integral_json_numbers_as_equivalent(left, right):
    # Browser JSON.stringify turns integral floats into integer JSON tokens.
    original = {"nested": {"values": [left]}}
    roundtripped = {"nested": {"values": [right]}}

    assert public_config_hash(original) == public_config_hash(roundtripped)
    assert type(original["nested"]["values"][0]) is type(left)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (True, 1),
        (False, 0),
        (1.0, 1.0000000000000002),
        (0.7, 0.7000000000000001),
        (1, "1"),
        ([1, 2], [2, 1]),
    ],
)
def test_public_config_hash_preserves_real_json_value_changes(left, right):
    assert public_config_hash({"value": left}) != public_config_hash({"value": right})


def test_public_config_hash_is_independent_of_object_key_order():
    assert public_config_hash({"a": 1, "b": 2}) == public_config_hash({"b": 2, "a": 1})
