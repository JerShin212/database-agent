"""Unit tests for parallel tool_use execution in AgentRuntime."""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from src.agent.agent_runtime import AgentRuntime
from src.agent.tools.context import ToolContext, get_tool_context, set_tool_context


class FakeBlock(SimpleNamespace):
    pass


def _usage():
    return SimpleNamespace(
        input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


def _multi_tool_response(names_and_inputs):
    return SimpleNamespace(
        content=[
            FakeBlock(type="tool_use", id=f"tu_{i}", name=name, input=tool_input)
            for i, (name, tool_input) in enumerate(names_and_inputs)
        ],
        stop_reason="tool_use",
        usage=_usage(),
    )


def _text_response(text):
    return SimpleNamespace(
        content=[FakeBlock(type="text", text=text)],
        stop_reason="end_turn",
        usage=_usage(),
    )


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **kwargs):
        return self.responses.pop(0)


def _build_runtime(responses):
    runtime = AgentRuntime(api_key="test-key", system="test")
    runtime._client = SimpleNamespace(messages=FakeMessages(responses))
    return runtime


def test_multiple_tool_blocks_run_in_parallel():
    runtime = _build_runtime(
        [
            _multi_tool_response([("slow", {"label": "a"}), ("slow", {"label": "b"}), ("slow", {"label": "c"})]),
            _text_response("done"),
        ]
    )
    runtime.add_tool(
        name="slow",
        description="sleeps",
        handler=lambda label: (time.sleep(0.3), label)[1],
        params={"label": {"type": "string"}},
        required=["label"],
    )

    start = time.monotonic()
    result = runtime.run("go")
    elapsed = time.monotonic() - start

    assert result == "done"
    # Sequential would be >= 0.9s; parallel should land near 0.3s
    assert elapsed < 0.7, f"tools did not run in parallel (took {elapsed:.2f}s)"


def test_results_map_to_correct_tool_use_ids():
    runtime = _build_runtime(
        [
            _multi_tool_response([("echo", {"value": "first"}), ("echo", {"value": "second"})]),
            _text_response("done"),
        ]
    )
    runtime.add_tool(
        name="echo",
        description="echo",
        handler=lambda value: f"echoed:{value}",
        params={"value": {"type": "string"}},
        required=["value"],
    )

    runtime.run("go")

    # The tool_results user message is the 3rd message (user, assistant, tool_results)
    tool_results = runtime.session.messages[2]["content"]
    by_id = {r["tool_use_id"]: r["content"] for r in tool_results}
    assert by_id["tu_0"] == "echoed:first"
    assert by_id["tu_1"] == "echoed:second"


def test_tool_context_propagates_to_parallel_threads():
    set_tool_context(ToolContext(db=None, database_name="ctx-db"))

    runtime = _build_runtime(
        [
            _multi_tool_response([("read_ctx", {}), ("read_ctx", {})]),
            _text_response("done"),
        ]
    )
    runtime.add_tool(
        name="read_ctx",
        description="reads the tool context",
        handler=lambda: (get_tool_context().database_name if get_tool_context() else "MISSING"),
    )

    runtime.run("go")

    tool_results = runtime.session.messages[2]["content"]
    assert all(r["content"] == "ctx-db" for r in tool_results)


def test_concurrent_run_calls_serialize_on_lock():
    active = {"count": 0, "max": 0}
    guard = threading.Lock()

    def tracking_handler():
        with guard:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.1)
        with guard:
            active["count"] -= 1
        return "ok"

    runtime = _build_runtime(
        [
            _multi_tool_response([("track", {})]),
            _text_response("done a"),
            _multi_tool_response([("track", {})]),
            _text_response("done b"),
        ]
    )
    runtime.add_tool(name="track", description="tracks concurrency", handler=tracking_handler)

    threads = [threading.Thread(target=runtime.run, args=("go",)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # The per-runtime lock must prevent interleaved turns on one session
    assert active["max"] == 1


def test_single_tool_block_unchanged():
    runtime = _build_runtime(
        [
            _multi_tool_response([("echo", {"value": "solo"})]),
            _text_response("done"),
        ]
    )
    runtime.add_tool(
        name="echo",
        description="echo",
        handler=lambda value: f"echoed:{value}",
        params={"value": {"type": "string"}},
        required=["value"],
    )

    assert runtime.run("go") == "done"
    tool_results = runtime.session.messages[2]["content"]
    assert tool_results[0]["content"] == "echoed:solo"
