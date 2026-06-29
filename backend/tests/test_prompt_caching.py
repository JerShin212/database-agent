"""Unit tests for prompt-cache breakpoints in AgentRuntime."""

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from src.agent.agent_runtime import AgentRuntime, Session


class FakeBlock(SimpleNamespace):
    pass


def _text_response(text, usage=None):
    return SimpleNamespace(
        content=[FakeBlock(type="text", text=text)],
        stop_reason="end_turn",
        usage=usage
        or SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _tool_use_response(tool_name, tool_input):
    return SimpleNamespace(
        content=[FakeBlock(type="tool_use", id="tu_1", name=tool_name, input=tool_input)],
        stop_reason="tool_use",
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=7,
            cache_creation_input_tokens=3,
        ),
    )


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        # Snapshot: the runtime mutates its message list after the call
        self.calls.append(copy.deepcopy(kwargs))
        return self.responses.pop(0)


def _build_runtime(responses):
    runtime = AgentRuntime(api_key="test-key", system="be helpful")
    fake = FakeMessages(responses)
    runtime._client = SimpleNamespace(messages=fake)
    return runtime, fake


def _count_cache_markers(messages):
    count = 0
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    count += 1
    return count


def test_system_is_block_list_with_cache_control():
    runtime, fake = _build_runtime([_text_response("hi")])
    runtime.run("hello")

    system = fake.calls[0]["system"]
    assert isinstance(system, list)
    assert system[0]["text"] == "be helpful"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_last_message_block_carries_single_cache_marker():
    runtime, fake = _build_runtime([_text_response("hi")])
    runtime.run("hello")

    messages = fake.calls[0]["messages"]
    assert _count_cache_markers(messages) == 1
    last_blocks = messages[-1]["content"]
    assert last_blocks[-1]["cache_control"] == {"type": "ephemeral"}


def test_marker_moves_to_tool_result_on_second_iteration():
    runtime, fake = _build_runtime(
        [_tool_use_response("echo", {"value": "x"}), _text_response("done")]
    )
    runtime.add_tool(
        name="echo",
        description="echo",
        handler=lambda value: value,
        params={"value": {"type": "string"}},
        required=["value"],
    )
    result = runtime.run("call echo")

    assert result == "done"
    second_call_messages = fake.calls[1]["messages"]
    # Exactly one marker in the whole transcript, on the trailing tool_result
    assert _count_cache_markers(second_call_messages) == 1
    last_blocks = second_call_messages[-1]["content"]
    assert last_blocks[-1]["type"] == "tool_result"
    assert last_blocks[-1]["cache_control"] == {"type": "ephemeral"}


def test_session_accumulates_cache_token_usage():
    runtime, _ = _build_runtime(
        [_tool_use_response("echo", {"value": "x"}), _text_response("done")]
    )
    runtime.add_tool(
        name="echo",
        description="echo",
        handler=lambda value: value,
        params={"value": {"type": "string"}},
        required=["value"],
    )
    runtime.run("call echo")

    assert runtime.session.cache_read_tokens == 7
    assert runtime.session.cache_creation_tokens == 3


def test_string_user_input_normalized_to_blocks():
    session = Session()
    session.add_user("plain text")
    assert session.messages[0]["content"] == [{"type": "text", "text": "plain text"}]
