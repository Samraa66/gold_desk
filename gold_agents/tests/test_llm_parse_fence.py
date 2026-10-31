import pytest

from gold_agents.llm import parse_json


@pytest.mark.parametrize("reply", ['```json\n{"a": 1}\n{"b": 2}\n```', '```json\n{"a": 1}}\n```', '```\n{"a": 1}\n```', '{"a": 1} and a note'])
def test_the_first_object_wins_inside_a_fence_too(reply):
    assert parse_json(reply) == {"a": 1}
