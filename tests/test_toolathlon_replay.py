"""Replay-test the Toolathlon study on FROZEN fixtures — zero benchmark/network/LLM access.

The keystone the audit calls "testable with zero benchmark access": the reader (`trajectory.py`)
and the scorer (`replay.py`) are pure over a parsed record, so synthetic OpenAI-style chat records
pin every behavior — the JSON-string field coercion, the terminal-narration extraction, the
acted-after corroborator, the (tool,args,result) step assembly, the peak-stall fold, and the
confusion-grid join to the third-party label.

Fixture schema mirrors the VERIFIED dataset record (docs/157): `task_status`/`messages` may be JSON
strings; `messages` is OpenAI chat (assistant `tool_calls=[{id,function:{name,arguments}}]` answered
by a `tool` message with the same `tool_call_id`).
"""

from __future__ import annotations

import json

from benchmark.toolathlon.replay import (
    DetectorReport,
    dangling_fired,
    replay,
    run_row,
    tool_stream_fired,
    tool_stream_peak,
)
from benchmark.toolathlon.trajectory import (
    is_generic_executor,
    is_struct_error,
    normalize_result_bytes,
    parse_record,
    terminal_error_fired,
    to_stop_evidence,
    to_terminal_error_evidence,
    to_tool_stream,
)
from dos.tool_stream import StreamState


# --------------------------------------------------------------------------- fixtures
def _asst(text=None, calls=None):
    m = {"role": "assistant", "content": text}
    if calls:
        m["tool_calls"] = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": json.dumps(c.get("args", {}))}}
            for c in calls
        ]
    return m


def _tool(tcid, content):
    return {"role": "tool", "tool_call_id": tcid, "content": content}


def _record(task, passed, messages, *, json_strings=False, model_run="claude-4.5-sonnet-0929_1"):
    status = {"preprocess": "done", "running": "done", "evaluation": passed}
    rec = {
        "modelname_run": model_run,
        "task_name": task,
        "task_status": json.dumps(status) if json_strings else status,
        "messages": json.dumps(messages) if json_strings else messages,
    }
    return rec


# --------------------------------------------------------------------------- parse
def test_parse_coerces_json_string_fields():
    """task_status + messages arrive as JSON STRINGS in the published dataset; the reader coerces."""
    rec = _record("t", False, [{"role": "user", "content": "hi"}], json_strings=True)
    traj = parse_record(rec)
    assert traj.passed is False
    assert traj.task_name == "t"
    assert traj.model == "claude-4.5-sonnet-0929"  # run suffix stripped
    assert len(traj.messages) == 1


def test_parse_already_decoded_fields():
    rec = _record("t", True, [{"role": "user", "content": "hi"}], json_strings=False)
    traj = parse_record(rec)
    assert traj.passed is True


def test_parse_missing_evaluation_is_none_not_guessed():
    rec = {"modelname_run": "m_1", "task_name": "t",
           "task_status": json.dumps({"preprocess": "done"}), "messages": []}
    assert parse_record(rec).passed is None


# --------------------------------------------------------------------------- dangling_intent reader
def test_dangling_fires_on_terminal_open_obligation():
    """Agent's last text admits unfinished work and nothing env-authored acted after -> FIRE."""
    msgs = [
        {"role": "user", "content": "do the thing"},
        _asst("I read the file. I still need to update the remaining records."),
    ]
    traj = parse_record(_record("t", False, msgs))
    ev = to_stop_evidence(traj)
    assert ev.results_after_turn == 0
    assert "still need to" in ev.final_turn_text.lower()
    assert dangling_fired(traj) is True


def test_dangling_abstains_when_env_tool_acted_after_narration():
    """The env-authored corroborator: a real tool result after the narration -> ABSTAIN (named it,
    then did it)."""
    msgs = [
        {"role": "user", "content": "do the thing"},
        _asst("I still need to update the record.", calls=[{"id": "a", "name": "db-update_row"}]),
        _tool("a", '{"ok": true}'),
    ]
    traj = parse_record(_record("t", False, msgs))
    ev = to_stop_evidence(traj)
    # terminal narration is the assistant text; one env result acted after it
    assert ev.results_after_turn == 1
    assert dangling_fired(traj) is False


def test_dangling_claim_done_result_does_not_count_as_acting():
    """A `claim_done` ack is a LOCAL no-op, not an act on the world — it must NOT mask a dangle.
    The agent admits open work, calls claim_done, gets its ack, stops: still a dangling stop."""
    msgs = [
        {"role": "user", "content": "do the thing"},
        _asst("I still need to grade the rest, but I'll stop here.",
              calls=[{"id": "cd", "name": "claim_done"}]),
        _tool("cd", '{"status": "done"}'),
    ]
    traj = parse_record(_record("t", False, msgs))
    assert to_stop_evidence(traj).results_after_turn == 0
    assert dangling_fired(traj) is True


def test_dangling_abstains_on_clean_stop():
    msgs = [{"role": "user", "content": "x"}, _asst("All records updated. The task is complete.")]
    assert dangling_fired(parse_record(_record("t", True, msgs))) is False


# --------------------------------------------------------------------------- tool_stream reader
def test_tool_stream_builds_steps_pairing_results_by_id():
    msgs = [
        _asst(None, calls=[{"id": "1", "name": "fs-read", "args": {"p": "a"}}]),
        _tool("1", "contents-A"),
        _asst(None, calls=[{"id": "2", "name": "fs-read", "args": {"p": "b"}}]),
        _tool("2", "contents-B"),
    ]
    steps = to_tool_stream(parse_record(_record("t", True, msgs))).steps
    assert len(steps) == 2
    assert steps[0].tool_name == "fs-read"
    assert steps[0].result_digest is not None
    assert steps[0].result_digest != steps[1].result_digest  # different bytes -> different digest


def test_tool_stream_fires_on_repeated_identical_triple():
    """Same (tool,args,result) three times -> REPEATING (the docs/145 repeat_n=3 floor)."""
    calls_and_results = []
    for i in range(3):
        calls_and_results.append(_asst(None, calls=[{"id": str(i), "name": "db-poll", "args": {"q": "1"}}]))
        calls_and_results.append(_tool(str(i), "same-bytes"))
    traj = parse_record(_record("t", False, calls_and_results))
    assert tool_stream_peak(traj) is StreamState.REPEATING
    assert tool_stream_fired(traj) is True


def test_tool_stream_advancing_when_results_differ():
    msgs = []
    for i in range(4):
        msgs.append(_asst(None, calls=[{"id": str(i), "name": "db-read", "args": {"q": str(i)}}]))
        msgs.append(_tool(str(i), f"row-{i}"))
    traj = parse_record(_record("t", True, msgs))
    assert tool_stream_peak(traj) is StreamState.ADVANCING
    assert tool_stream_fired(traj) is False


def test_tool_stream_peak_catches_a_mid_run_stall_then_recovery():
    """The replay PEAK semantics: a stall in the MIDDLE of a run is caught even if the run later
    advances (a live consumer would have seen REPEATING turn-by-turn)."""
    msgs = []
    for i in range(3):  # 3x identical -> REPEATING mid-stream
        msgs.append(_asst(None, calls=[{"id": f"r{i}", "name": "db-poll", "args": {"q": "1"}}]))
        msgs.append(_tool(f"r{i}", "stuck"))
    msgs.append(_asst(None, calls=[{"id": "z", "name": "db-read", "args": {"q": "new"}}]))  # then advances
    msgs.append(_tool("z", "fresh"))
    traj = parse_record(_record("t", True, msgs))
    assert tool_stream_peak(traj) is StreamState.REPEATING  # peak caught despite recovery


def test_tool_stream_missing_result_breaks_run():
    """A call with no answering tool message (result_digest None) can't extend a repeat run."""
    msgs = [
        _asst(None, calls=[{"id": "1", "name": "x", "args": {}}]), _tool("1", "same"),
        _asst(None, calls=[{"id": "2", "name": "x", "args": {}}]),  # no tool result
        _asst(None, calls=[{"id": "3", "name": "x", "args": {}}]), _tool("3", "same"),
    ]
    steps = to_tool_stream(parse_record(_record("t", True, msgs))).steps
    assert steps[1].result_digest is None  # the orphaned call breaks the run


# ------------------------------------------------- LIVE WARN adapter PARITY (warn_patch.py)
# The gate that the live in-loop path is NOT a silent no-op: build a known sequence in BOTH shapes —
# the chat-dict shape the offline replay scores AND the SDK `RunItem` shape the live patch sees in
# `execute_tools_and_side_effects` — and prove the live adapter + classify_stream produces the
# IDENTICAL StreamState (and the SAME repeated result value) as the offline to_tool_stream path.
# If the adapter is wrong (the #1 risk: SDK items fed straight to to_tool_stream match nothing ->
# always ADVANCING), THESE tests fail LOUD instead of the paid A/B silently measuring nothing.
#
# The fakes are duck-typed against the VERIFIED openai-agents==0.0.15 shapes (call_id/.name/
# .arguments on ResponseFunctionToolCall; .output + raw_item dict on ToolCallOutputItem). The
# adapter reads them via getattr only, so no `agents`/`openai` SDK install is needed here — the same
# zero-benchmark-access discipline as the rest of this suite.
from benchmark.toolathlon.warn_patch import (  # noqa: E402
    LIVE_STREAM_POLICY,
    _sdk_items_to_chat_messages,
    build_warn_text,
    stream_verdict_from_items,
)
from dos.tool_stream import classify_stream  # noqa: E402


class _FakeFnCall:
    """Duck-type of openai.types.responses.ResponseFunctionToolCall (the ToolCallItem.raw_item)."""

    type = "function_call"

    def __init__(self, call_id, name, arguments):
        self.call_id = call_id     # the linkage key (NOT .id)
        self.id = "resp-" + call_id  # a DISTINCT field the adapter must NOT use for linkage
        self.name = name
        self.arguments = arguments  # a JSON string, as the SDK gives


class _FakeToolCallItem:
    """Duck-type of agents.items.ToolCallItem."""

    type = "tool_call_item"

    def __init__(self, call_id, name, arguments):
        self.raw_item = _FakeFnCall(call_id, name, arguments)


class _FakeToolOutputItem:
    """Duck-type of agents.items.ToolCallOutputItem (raw_item is a FunctionCallOutput dict)."""

    type = "tool_call_output_item"

    def __init__(self, call_id, output):
        self.output = output  # the raw (pre-str) result; the SDK sets .output = result
        self.raw_item = {"call_id": call_id, "output": str(output), "type": "function_call_output"}


def _both_shapes(seq):
    """From a logical (call_id, tool, args-dict, result-str) sequence build BOTH:
      - chat_msgs : the offline chat-dict list (assistant tool_call + tool result), and
      - sdk_items : the live SDK RunItem list (ToolCallItem + ToolCallOutputItem),
    so the parity test feeds ONE source sequence into the two readers and compares verdicts.
    """
    chat_msgs = []
    sdk_items = []
    for cid, tool, args, result in seq:
        chat_msgs.append(_asst(None, calls=[{"id": cid, "name": tool, "args": args}]))
        chat_msgs.append(_tool(cid, result))
        sdk_items.append(_FakeToolCallItem(cid, tool, json.dumps(args)))
        sdk_items.append(_FakeToolOutputItem(cid, result))
    return chat_msgs, sdk_items


def test_warn_adapter_is_not_a_silent_noop_repeating_parity():
    """THE GATE: a known-REPEATING loop classifies REPEATING via BOTH the offline chat reader and the
    live SDK adapter, with the SAME repeated result value. If the adapter were wrong, the live side
    would read ADVANCING (empty ToolStream) and this assertion would fail loud."""
    seq = [(str(i), "db-poll", {"q": "1"}, "same-bytes") for i in range(3)]  # 3x identical -> REPEATING
    chat_msgs, sdk_items = _both_shapes(seq)

    # offline path: the dataset reader the published study scored
    offline = classify_stream(
        to_tool_stream(parse_record(_record("t", False, chat_msgs))), LIVE_STREAM_POLICY
    )
    # live path: the in-loop SDK adapter the WARN patch uses
    live = stream_verdict_from_items(sdk_items, LIVE_STREAM_POLICY)

    assert offline.state is StreamState.REPEATING
    assert live.state is StreamState.REPEATING           # NOT a silent ADVANCING no-op
    assert live.state == offline.state                   # identical StreamState
    assert live.repeat_run == offline.repeat_run         # identical run length
    # SAME repeated result value (the env-authored result_digest the WARN re-surfaces)
    assert live.repeated_step is not None
    assert live.repeated_step.result_digest == offline.repeated_step.result_digest
    assert live.repeated_step.tool_name == offline.repeated_step.tool_name == "db-poll"


def test_warn_adapter_digests_match_byte_for_byte_per_step():
    """Stronger than the verdict: EVERY StreamStep digest (tool, args, result) matches between the
    offline and live readers — proving the live adapter reuses the SHARED normalizer, not a parallel
    reimplementation. This is what makes 'live == offline replay' a byte claim, not a coincidence."""
    seq = [
        ("a", "fs-read", {"p": "x"}, "contents-X"),
        ("b", "db-poll", {"q": "1"}, "same"),
        ("c", "db-poll", {"q": "1"}, "same"),
        ("d", "db-poll", {"q": "1"}, "same"),
    ]
    chat_msgs, sdk_items = _both_shapes(seq)
    offline_steps = to_tool_stream(parse_record(_record("t", False, chat_msgs))).steps
    # the live adapter builds the same Trajectory shape, then the SAME to_tool_stream
    live_msgs = _sdk_items_to_chat_messages(sdk_items)
    from benchmark.toolathlon.trajectory import Trajectory  # local: pin the assembled shape
    live_steps = to_tool_stream(
        Trajectory(model_run="", task_name="", passed=None, messages=tuple(live_msgs))
    ).steps
    assert len(live_steps) == len(offline_steps) == 4
    for ls, os_ in zip(live_steps, offline_steps):
        assert ls.tool_name == os_.tool_name
        assert ls.args_digest == os_.args_digest        # SAME _normalize_args digest
        assert ls.result_digest == os_.result_digest    # SAME normalize_result_bytes digest


def test_warn_adapter_no_fire_case_is_advancing_in_both():
    """The no-fire half of the gate: a loop with genuinely DIFFERENT results reads ADVANCING via BOTH
    readers — so the WARN arm does not false-fire, and the parity holds in the quiet direction too."""
    seq = [(str(i), "db-read", {"q": str(i)}, f"row-{i}") for i in range(4)]  # all distinct
    chat_msgs, sdk_items = _both_shapes(seq)
    offline = classify_stream(
        to_tool_stream(parse_record(_record("t", True, chat_msgs))), LIVE_STREAM_POLICY
    )
    live = stream_verdict_from_items(sdk_items, LIVE_STREAM_POLICY)
    assert offline.state is StreamState.ADVANCING
    assert live.state is StreamState.ADVANCING
    assert live.state == offline.state


def test_warn_adapter_parity_under_volatile_normalizer():
    """The normalizer parity: a loop whose results differ ONLY in a volatile timestamp reads
    ADVANCING under the RAW floor but REPEATING once masked — and the live adapter (which calls
    to_tool_stream(normalize=True)) recovers it IDENTICALLY to the offline normalized path. Proves
    the shared volatile-field masker is on BOTH sides, not just offline."""
    seq = [
        (str(i), "db-poll", {"q": "1"}, f'{{"status":"pending","checked_at":"2026-06-05T10:0{i}:00Z"}}')
        for i in range(3)
    ]
    chat_msgs, sdk_items = _both_shapes(seq)
    offline = classify_stream(
        to_tool_stream(parse_record(_record("t", False, chat_msgs)), normalize=True),
        LIVE_STREAM_POLICY,
    )
    live = stream_verdict_from_items(sdk_items, LIVE_STREAM_POLICY)  # normalize=True inside
    assert offline.state is StreamState.REPEATING
    assert live.state is StreamState.REPEATING                 # masker recovered the repeat live too
    assert live.repeat_run == offline.repeat_run


def test_warn_adapter_skips_non_function_items():
    """Robustness: a reasoning/web-search item interleaved in the SDK history is skipped (only
    function calls carry .name/.arguments/.call_id), so it does not corrupt the stream or the
    linkage — the live verdict still matches the offline one built from the function steps alone."""
    class _FakeReasoning:
        type = "reasoning_item"
        raw_item = object()

    class _FakeWebCall:  # a non-function ToolCallItem (skip per the adapter)
        type = "tool_call_item"
        class raw_item:  # noqa: N801 - inline fake
            type = "web_search_call"

    seq = [(str(i), "db-poll", {"q": "1"}, "same") for i in range(3)]
    chat_msgs, sdk_items = _both_shapes(seq)
    # interleave noise items the adapter must ignore
    noisy = [_FakeReasoning(), sdk_items[0], sdk_items[1], _FakeWebCall(),
             sdk_items[2], sdk_items[3], sdk_items[4], sdk_items[5]]
    offline = classify_stream(
        to_tool_stream(parse_record(_record("t", False, chat_msgs))), LIVE_STREAM_POLICY
    )
    live = stream_verdict_from_items(noisy, LIVE_STREAM_POLICY)
    assert live.state == offline.state == StreamState.REPEATING


def test_warn_text_resurfaces_the_held_value_never_a_directive():
    """The WARN text quotes the agent's OWN looping tool + repeat count and tells it to USE the held
    value or do something DIFFERENT — it authors no tool directive (the docs/143 derailment channel
    is unreachable)."""
    seq = [(str(i), "excel-read_sheet", {"f": "data.xlsx"}, "same") for i in range(3)]
    _, sdk_items = _both_shapes(seq)
    verdict = stream_verdict_from_items(sdk_items, LIVE_STREAM_POLICY)
    txt = build_warn_text(verdict)
    assert "excel-read_sheet" in txt          # names the agent's own looping tool
    assert "3 times" in txt                    # the repeat count it already holds
    assert "DIFFERENT action" in txt           # invites a different action, not a specific one


# ------------------------------------------------- result_digest normalizer (docs/157 §4)
def test_normalize_masks_iso_timestamp_but_not_bare_date():
    """The #1 volatile field: an ISO instant is masked; a bare due-date (no T-time) is preserved."""
    a = normalize_result_bytes('{"updated":"2026-06-05T10:00:00Z","due":"2026-12-01"}')
    b = normalize_result_bytes('{"updated":"2026-06-05T11:30:45Z","due":"2026-12-01"}')
    assert a == b                                  # the two TIMES collapsed to one identity
    assert "<TS>" in a and "2026-12-01" in a       # bare date survives (not a T-instant)


def test_normalize_masks_uuid_and_search_id_and_pdfdate():
    assert normalize_result_bytes("id=550e8400-e29b-41d4-a716-446655440000") == "id=<UUID>"
    assert normalize_result_bytes("Search ID: 720ed46f\nPattern: FID") == "Search ID: <SEARCHID>\nPattern: FID"
    assert normalize_result_bytes("Creation date: D:20230303012649Z") == "Creation date: <PDFDATE>"


def test_normalize_is_the_SAFE_direction_genuinely_different_content_still_differs():
    """The §5a guard: masking must NOT collapse results that differ in real CONTENT — only the
    volatile token. Two results with the same timestamp but different payloads stay distinct."""
    a = normalize_result_bytes('{"ts":"2026-06-05T10:00:00Z","rows":42}')
    b = normalize_result_bytes('{"ts":"2026-06-05T10:00:00Z","rows":99}')
    assert a != b                                  # the payload difference survives normalization


def test_normalize_is_idempotent():
    once = normalize_result_bytes("at 2026-06-05T10:00:00Z id 550e8400-e29b-41d4-a716-446655440000")
    assert normalize_result_bytes(once) == once    # masking a masked string is a no-op


def test_normalizer_recovers_a_repeat_the_raw_floor_misses():
    """The whole point: a stall where each re-read carries a fresh timestamp digests as ADVANCING
    under the RAW floor (--raw-digest) but REPEATING once the volatile field is masked. This is the
    docs/157 §4 under-count, fixed — and the fix only ADDS recall (it never accuses a healthy loop)."""
    msgs = []
    for i in range(3):
        # identical SEMANTIC result, but a volatile per-read timestamp the env stamped
        msgs.append(_asst(None, calls=[{"id": str(i), "name": "db-poll", "args": {"q": "1"}}]))
        msgs.append(_tool(str(i), f'{{"status":"pending","checked_at":"2026-06-05T10:0{i}:00Z"}}'))
    traj = parse_record(_record("t", False, msgs))
    # RAW: each result differs (timestamp), so no repeat -> ADVANCING (the lower-bound miss)
    assert tool_stream_peak(traj, normalize=False) is StreamState.ADVANCING
    # NORMALIZED: timestamps masked -> identical triples -> REPEATING (the recovered repeat)
    assert tool_stream_peak(traj, normalize=True) is StreamState.REPEATING


def test_normalizer_does_not_manufacture_a_repeat_from_advancing_rows():
    """The dangerous direction, pinned shut: rows that genuinely advance (different payloads) must
    NOT be collapsed into a false REPEATING by the normalizer, even sharing a volatile field."""
    msgs = []
    for i in range(4):
        msgs.append(_asst(None, calls=[{"id": str(i), "name": "db-read", "args": {"q": "1"}}]))
        # same timestamp, but each returns a DIFFERENT row -> must stay ADVANCING
        msgs.append(_tool(str(i), f'{{"ts":"2026-06-05T10:00:00Z","row":{i}}}'))
    traj = parse_record(_record("t", True, msgs))
    assert tool_stream_peak(traj, normalize=True) is StreamState.ADVANCING


def test_replay_normalize_flag_threads_through():
    """The CLI `--raw-digest` path: replay(normalize=False) reproduces the raw floor; the default
    (normalize=True) applies the masker. Same corpus, the flag is the only difference."""
    msgs = []
    for i in range(3):
        msgs.append(_asst(None, calls=[{"id": str(i), "name": "db-poll", "args": {"q": "1"}}]))
        msgs.append(_tool(str(i), f'{{"v":"pending","at":"2026-06-05T10:0{i}:00Z"}}'))
    traj = parse_record(_record("t", False, msgs, model_run="gemini-2.5-flash_1"))
    raw = replay([traj], normalize=False)
    norm = replay([traj], normalize=True)
    assert raw.tool_stream.fired == 0       # raw floor misses the timestamped repeat
    assert norm.tool_stream.fired == 1      # normalizer recovers it


# ------------------------------------------------- terminal_error detector (docs/158)
def test_struct_error_grammar_matches_envelopes_not_loose_substrings():
    """The byte-clean grammar is TIGHT: structured envelopes fire, loose substrings do NOT (they
    appear in legit env-authored content — an abstract about 'error rates', a '404' in HTML)."""
    # structured envelopes → True
    assert is_struct_error("MCP error -32603: Port-forward process exited")
    assert is_struct_error('{"isError": true, "content": "boom"}')
    assert is_struct_error("Error: connection refused")
    assert is_struct_error("Traceback (most recent call last):\n  File ...")
    assert is_struct_error("bash: exited with code 1")
    assert is_struct_error("permission denied")
    # loose substrings in legit content → False (precision guard)
    assert not is_struct_error("This paper studies error rates in diffusion models.")
    assert not is_struct_error("The page returned 404 results for your query.")
    assert not is_struct_error("Task failed successfully is a common joke.")
    assert not is_struct_error("file not found in the search index")


def test_terminal_error_fires_when_run_stops_on_unresolved_env_error():
    """The agent's LAST tool result is a structured env error, never recovered → FIRE."""
    msgs = [
        _asst(None, calls=[{"id": "1", "name": "k8s-deploy", "args": {"svc": "web"}}]),
        _tool("1", 'MCP error -32603: Port-forward process exited with code 1'),
        _asst("Deployment complete! The service is now running."),  # stops, confidently wrong
    ]
    traj = parse_record(_record("deploy", False, msgs))
    assert terminal_error_fired(traj) is True


def test_terminal_error_does_not_fire_when_error_was_recovered():
    """A transient error the agent FIXED (a later success from the same tool) must NOT fire —
    it is not an unresolved failure."""
    msgs = [
        _asst(None, calls=[{"id": "1", "name": "db-write", "args": {"row": 1}}]),
        _tool("1", "Error: connection refused"),
        _asst(None, calls=[{"id": "2", "name": "db-write", "args": {"row": 1}}]),
        _tool("2", '{"ok": true, "wrote": 1}'),   # recovered
        _asst("Done."),
    ]
    traj = parse_record(_record("write", True, msgs))
    assert terminal_error_fired(traj) is False


def test_terminal_error_quiet_on_clean_run():
    msgs = [
        _asst(None, calls=[{"id": "1", "name": "fs-read", "args": {"p": "a"}}]),
        _tool("1", "file contents here"),
        _asst("All done."),
    ]
    assert terminal_error_fired(parse_record(_record("t", True, msgs))) is False


def test_terminal_error_is_byte_clean_agent_cannot_forge_success_over_env_error():
    """The §5a line: the error envelope is in the ENV-authored tool result; the agent's narration
    claiming success CANNOT suppress it. Even a confident 'success!' final message does not stop the
    fire — because the detector reads the env's bytes, not the agent's."""
    msgs = [
        _asst(None, calls=[{"id": "1", "name": "email-send", "args": {"to": "x"}}]),
        _tool("1", '{"isError": true, "message": "SMTP 550 rejected"}'),
        _asst("Email sent successfully to all recipients! Task complete."),  # agent lies
    ]
    traj = parse_record(_record("email", False, msgs))
    assert terminal_error_fired(traj) is True  # env error wins over agent claim


def test_terminal_error_window_bounds_how_far_back_it_looks():
    """An error far in the PAST (outside the closing window) that the run moved on from does NOT
    fire — only an error in the last `window` results counts as 'stopped on'."""
    msgs = [
        _asst(None, calls=[{"id": "0", "name": "a", "args": {}}]), _tool("0", "Error: early hiccup"),
    ]
    # then 4 clean steps from OTHER tools push the error out of the window=3
    for i in range(1, 5):
        msgs.append(_asst(None, calls=[{"id": str(i), "name": f"t{i}", "args": {}}]))
        msgs.append(_tool(str(i), f"ok-{i}"))
    msgs.append(_asst("Done."))
    traj = parse_record(_record("t", True, msgs))
    assert terminal_error_fired(traj, window=3) is False   # the early error is out of window


def test_terminal_error_in_replay_and_runrow():
    """terminal_error is a first-class detector in the replay grid + the durable row."""
    err_run = _record(
        "deploy", False,
        [_asst(None, calls=[{"id": "1", "name": "k8s", "args": {}}]),
         _tool("1", "Traceback (most recent call last):\n  RuntimeError"),
         _asst("Looks good!")],
        model_run="gpt-5.1_1",
    )
    res = replay([parse_record(err_run)])
    assert res.terminal_error.fired == 1 and res.terminal_error.fired_fail == 1
    assert res.terminal_error.oracle_confirmed_precision == 1.0
    # the durable row carries the new scalar field
    assert res.rows[0].to_dict()["terminal_error_fired"] is True
    # by-model breakdown includes it
    assert res.by_model["gpt-5.1"]["terminal_error"].fired_fail == 1
    # the aggregate to_dict exposes the third detector
    assert "terminal_error" in res.to_dict()["detectors"]


def test_terminal_error_is_ADDITIVE_not_subsuming_tool_stream():
    """The docs/158 honesty pin: terminal_error and tool_stream are DISTINCT slices — neither
    subsumes the other, so the trio's recall is genuinely additive and the headline must NOT claim
    terminal_error is the sole/first frontier signal (the corrected claim: it ADDS to what
    tool_stream already catches on the frontier, it does not replace it).

    A loop run fires tool_stream but NOT terminal_error (it ends on a repeated *success*, no error
    envelope); an env-error stop fires terminal_error but NOT tool_stream (no repeat). Proving both
    directions pins the slices as orthogonal."""
    # (a) a loop that ends on repeated SUCCESS bytes -> tool_stream fires, terminal_error does not.
    loop_msgs = []
    for i in range(4):
        loop_msgs.append(_asst(None, calls=[{"id": str(i), "name": "db-poll", "args": {"q": "1"}}]))
        loop_msgs.append(_tool(str(i), "status: pending"))   # identical NON-error bytes
    loop_msgs.append(_asst("Still pending, stopping."))
    loop = parse_record(_record("poll", False, loop_msgs))
    assert tool_stream_peak(loop) is not StreamState.ADVANCING  # tool_stream sees the loop
    assert terminal_error_fired(loop) is False                  # no env error -> terminal_error quiet

    # (b) a clean run that stops on an env ERROR -> terminal_error fires, tool_stream does not.
    err_msgs = [
        _asst(None, calls=[{"id": "1", "name": "k8s", "args": {}}]),
        _tool("1", "MCP error -32603: Port-forward exited"),
        _asst("Deployed!"),
    ]
    err = parse_record(_record("deploy", False, err_msgs))
    assert terminal_error_fired(err) is True
    assert tool_stream_peak(err) is StreamState.ADVANCING       # single step, no repeat


# ------------------------------------------------- terminal_error RECOVERY KNOB (docs/162)
# The confidence knob over the recovery-check: "aware" (default, conservative) / "specific-only"
# (surgical — a generic-executor recovery never suppresses) / "none" (aggressive — recovery ignored).
# The measured phenomenon: an agent's script Tracebacks, it runs a DIFFERENT script with the SAME
# generic executor that succeeds, the run still fails final-state — same-tool ≠ same-operation.
def _generic_exec_false_reassurance():
    """A generic-executor (local-python-execute) error 'recovered' by a later DIFFERENT-script success
    from the SAME tool — the docs/162 false-reassurance shape (the recovery is a different op)."""
    return parse_record(_record("excel-data-transformation", False, [
        _asst(None, calls=[{"id": "1", "name": "local-python-execute", "args": {"code": "bad()"}}]),
        _tool("1", "=== STDERR ===\nTraceback (most recent call last):\n  RuntimeError: boom"),
        _asst(None, calls=[{"id": "2", "name": "local-python-execute", "args": {"code": "print(1)"}}]),
        _tool("2", "=== STDOUT ===\n1"),   # a DIFFERENT script succeeded — not a fix of the failure
        _asst("All transformations complete!"),
    ]))


def test_is_generic_executor_membership_and_shape():
    """The harness-config set: named generic executors + the END-in-exec-verb shape rule; a SPECIFIC
    tool (its name identifies the operation) is NOT generic, so its recovery still counts."""
    assert is_generic_executor("local-python-execute")
    assert is_generic_executor("terminal-run_command")
    assert is_generic_executor("bash") and is_generic_executor("shell")
    assert is_generic_executor("acme-foo.execute")          # shape: ends in `execute`
    # specific tools — name identifies the operation -> NOT generic (recovery is real evidence)
    assert not is_generic_executor("db-write")
    assert not is_generic_executor("email-send")
    assert not is_generic_executor("db-execute_query")      # ends in `query`, not an exec verb
    assert not is_generic_executor("filesystem-list_directory")
    assert not is_generic_executor("")


def test_recovery_aware_default_is_byte_identical_to_old_behavior():
    """The conservative default must reproduce the shipped recovery-aware verdict exactly — a
    generic-executor false-reassurance run stays QUIET under 'aware' (today's behavior)."""
    traj = _generic_exec_false_reassurance()
    assert terminal_error_fired(traj) is False                       # default
    assert terminal_error_fired(traj, recovery="aware") is False     # explicit, same


def test_recovery_specific_only_fires_on_generic_executor_false_reassurance():
    """The surgical knob: a generic-executor recovery does NOT suppress -> the false-reassurance run
    FIRES under 'specific-only' (the +70-catch slice docs/162 measures)."""
    traj = _generic_exec_false_reassurance()
    assert terminal_error_fired(traj, recovery="specific-only") is True
    assert terminal_error_fired(traj, recovery="none") is True       # aggressive fires too


def test_recovery_specific_only_PRESERVES_genuine_recovery_on_a_specific_tool():
    """The whole point of 'specific-only' over 'none': a SPECIFIC tool's recovery is real evidence
    and must STILL suppress. A db-write error fixed by a later db-write success stays QUIET under
    'specific-only' (only 'none' would fire on it)."""
    traj = parse_record(_record("write", True, [
        _asst(None, calls=[{"id": "1", "name": "db-write", "args": {"row": 1}}]),
        _tool("1", "Error: connection refused"),
        _asst(None, calls=[{"id": "2", "name": "db-write", "args": {"row": 1}}]),
        _tool("2", '{"ok": true}'),     # genuine recovery: same SPECIFIC operation succeeded
        _asst("Done."),
    ]))
    assert terminal_error_fired(traj, recovery="aware") is False
    assert terminal_error_fired(traj, recovery="specific-only") is False   # specific recovery kept
    assert terminal_error_fired(traj, recovery="none") is True             # aggressive ignores it


def test_recovery_none_fires_on_any_unrecovered_or_recovered_closing_error():
    """The aggressive floor: 'none' fires whenever a closing-window structured error exists, recovered
    or not (the docs/159 §4b tight-no-recovery floor)."""
    # a specific-tool error that WAS recovered -> aware/specific-only quiet, none fires
    traj = parse_record(_record("t", False, [
        _asst(None, calls=[{"id": "1", "name": "db-write", "args": {}}]),
        _tool("1", "Error: transient"),
        _asst(None, calls=[{"id": "2", "name": "db-write", "args": {}}]),
        _tool("2", "ok"),
        _asst("Done."),
    ]))
    assert terminal_error_fired(traj, recovery="none") is True


def test_recovery_modes_are_monotone_aware_subset_specific_subset_none():
    """SAFE DIRECTION pinned: each looser mode can only fire MORE than the stricter one — never
    silence a catch the stricter mode makes. Across a mixed fixture, fire(aware) ⊆ fire(specific) ⊆
    fire(none) per run."""
    cases = [
        _generic_exec_false_reassurance(),                              # quiet/fire/fire
        parse_record(_record("clean", True, [                          # quiet/quiet/quiet
            _asst(None, calls=[{"id": "1", "name": "fs-read", "args": {}}]),
            _tool("1", "contents"), _asst("Done.")])),
        parse_record(_record("hardfail", False, [                      # fire/fire/fire (unrecovered)
            _asst(None, calls=[{"id": "1", "name": "k8s", "args": {}}]),
            _tool("1", "MCP error -32603: boom"), _asst("Deployed!")])),
    ]
    for tj in cases:
        a = terminal_error_fired(tj, recovery="aware")
        s = terminal_error_fired(tj, recovery="specific-only")
        n = terminal_error_fired(tj, recovery="none")
        assert (not a) or s, "specific-only must fire wherever aware does (monotone)"
        assert (not s) or n, "none must fire wherever specific-only does (monotone)"


def test_recovery_invalid_mode_raises():
    traj = _generic_exec_false_reassurance()
    import pytest
    with pytest.raises(ValueError):
        terminal_error_fired(traj, recovery="bogus")
    with pytest.raises(ValueError):
        to_terminal_error_evidence(traj, recovery="bogus")


def test_recovery_knob_threads_through_replay_and_runrow():
    """The CLI path: replay(te_recovery=...) steers the terminal_error CONFUSION GRID, while the
    durable row always carries BOTH columns (docs/162 SSOT contract — the flag does not change the
    row's column identity, only which mode the grid scores)."""
    traj = _generic_exec_false_reassurance()
    # the durable row columns are FIXED regardless of the flag: aware-column quiet, specific-column fires
    for flag in ("aware", "specific-only", "none"):
        row = run_row(traj, te_recovery=flag)
        assert row.terminal_error_fired is False              # the aware column, always conservative
        assert row.terminal_error_specific_fired is True      # the surgical column, always specific-only
    # the confusion GRID honors the flag:
    aware = replay([traj], te_recovery="aware")
    surgical = replay([traj], te_recovery="specific-only")
    none_mode = replay([traj], te_recovery="none")
    assert aware.terminal_error.fired == 0                 # default: the false-reassurance is silenced
    assert surgical.terminal_error.fired == 1              # surgical: it fires (on a FAILED run)
    assert surgical.terminal_error.fired_fail == 1
    assert surgical.terminal_error.oracle_confirmed_precision == 1.0
    assert none_mode.terminal_error.fired == 1            # none also fires (recomputed, not a row column)


# --------------------------------------------------------------------------- scorer / confusion grid
def test_detector_report_grid_and_rates():
    rep = DetectorReport("d")
    rep.observe(fired=True, passed=False)   # fired_fail
    rep.observe(fired=True, passed=False)   # fired_fail
    rep.observe(fired=True, passed=True)    # fired_pass (false alarm)
    rep.observe(fired=False, passed=False)  # quiet_fail (miss)
    rep.observe(fired=False, passed=True)   # quiet_pass
    rep.observe(fired=True, passed=None)    # unlabeled -> excluded
    assert rep.labeled == 5 and rep.unlabeled == 1
    assert rep.oracle_failed == 3 and rep.oracle_passed == 2
    assert rep.fired == 3 and rep.fired_fail == 2 and rep.fired_pass == 1
    assert abs(rep.fire_rate - 3 / 5) < 1e-9
    assert abs(rep.oracle_confirmed_precision - 2 / 3) < 1e-9
    assert abs(rep.base_fail_rate - 3 / 5) < 1e-9
    # purchase: precision 0.667 > base 0.60 -> small positive lift
    assert rep.lift_over_base > 0
    assert abs(rep.recall_of_failures - 2 / 3) < 1e-9
    assert abs(rep.false_alarm_rate - 1 / 2) < 1e-9


def test_detector_report_precision_none_when_never_fires():
    rep = DetectorReport("d")
    rep.observe(fired=False, passed=False)
    rep.observe(fired=False, passed=True)
    assert rep.oracle_confirmed_precision is None
    assert rep.lift_over_base is None


def test_replay_end_to_end_joins_label_and_breaks_down_by_model():
    """A tiny mixed corpus: a dangling-failed run and a clean-passed run across two models."""
    dangling_fail = _record(
        "t1", False,
        [{"role": "user", "content": "x"}, _asst("I still need to finish the rest.")],
        model_run="gpt-5_1",
    )
    clean_pass = _record(
        "t2", True,
        [{"role": "user", "content": "x"}, _asst("Done. All complete.")],
        model_run="claude-4.5-sonnet-0929_1",
    )
    trajs = [parse_record(dangling_fail), parse_record(clean_pass)]
    res = replay(trajs)
    assert res.n_records == 2
    # dangling fired once, on the failed run -> precision 1.0, lift positive
    assert res.dangling.fired == 1 and res.dangling.fired_fail == 1
    assert res.dangling.oracle_confirmed_precision == 1.0
    # by-model breakdown present for both
    assert set(res.by_model) == {"gpt-5", "claude-4.5-sonnet-0929"}
    assert res.by_model["gpt-5"]["dangling_intent"].fired_fail == 1
    assert res.by_model["claude-4.5-sonnet-0929"]["dangling_intent"].fired == 0
    # to_dict round-trips
    d = res.to_dict()
    assert d["detectors"]["dangling_intent"]["fired_fail"] == 1
    # durable flat rows accumulated (one per trajectory)
    assert len(res.rows) == 2


# --------------------------------------------------------------------------- durable run rows
def test_run_row_is_flat_and_scalar_for_durable_export():
    """The explorable unit: one flat row per run, every field a scalar (loads into a dataframe with
    zero reshaping). The user's 'data in a durable format to explore' requirement."""
    msgs = [
        {"role": "user", "content": "x"},
        _asst(None, calls=[{"id": "1", "name": "fs-read", "args": {"p": "a"}}]),
        _tool("1", "A"),
        _asst("I still need to finish the remaining items."),
    ]
    traj = parse_record(_record("grade-canvas", False, msgs, model_run="gpt-5_2"))
    row = run_row(traj)
    d = row.to_dict()
    # all scalars — no nested dict/list values
    assert all(not isinstance(v, (dict, list)) for v in d.values())
    assert d["model"] == "gpt-5" and d["model_run"] == "gpt-5_2"
    assert d["task_name"] == "grade-canvas" and d["passed"] is False
    assert d["n_tool_steps"] == 1
    assert d["dangling_fired"] is True and "still need to" in d["dangling_cue"]
    assert d["tool_stream_state"] in {"ADVANCING", "REPEATING", "STALLED"}
    assert d["final_text_len"] > 0


def test_run_row_carries_both_terminal_error_modes_regardless_of_te_recovery():
    """docs/162 SSOT contract: the durable row ALWAYS carries both terminal_error_fired (aware) and
    terminal_error_specific_fired (specific-only), independent of te_recovery — so additivity.py can
    fold either trio reproducibly. The te_recovery flag only steers the CLI confusion grid, never the
    durable columns."""
    traj = _generic_exec_false_reassurance()  # quiet under aware, fires under specific-only
    for flag in ("aware", "specific-only", "none"):
        d = run_row(traj, te_recovery=flag).to_dict()
        assert d["terminal_error_fired"] is False             # aware column: ALWAYS the conservative verdict
        assert d["terminal_error_specific_fired"] is True     # surgical column: ALWAYS specific-only
    # the two columns differ on this run (the whole point), and both are present + scalar
    d = run_row(traj).to_dict()
    assert "terminal_error_specific_fired" in d
    assert all(not isinstance(v, (dict, list)) for v in d.values())


# --------------------------------------------------------------------------- additivity (docs/158)
# additivity.py is the single source of truth for the trio claims a figure/ledger draws. These pin
# the DECOMPOSITION logic on a hand-built fixture (independent of the corpus), so the "net-new",
# "union recall", and "frontier" arithmetic can't silently drift. Rows are plain dicts keyed exactly
# like the durable CSV columns, since additivity.compute() reads dicts.
from benchmark.toolathlon import additivity as _add  # noqa: E402


def _arow(model, run, task, passed, *, dang=False, ts=False, te=False, te_spec=None):
    """A minimal durable-row dict — only the columns additivity.compute() reads. `te_spec` is the
    docs/162 surgical column (`terminal_error_specific_fired`); defaults to the aware value `te` when
    not given (the common case where the two modes agree)."""
    return {
        "model": model,
        "model_run": f"{model}_{run}",
        "task_name": task,
        "passed": str(passed),  # "True" / "False" / "None"
        "dangling_fired": str(dang),
        "tool_stream_fired": str(ts),
        "terminal_error_fired": str(te),
        "terminal_error_specific_fired": str(te if te_spec is None else te_spec),
    }


def _fixture_rows():
    """A tiny corpus exercising every additivity branch:
    - weak model "w" (pass-rate 1/5 = 0.2 < cut): pair catches some, terminal_error overlaps one +
      adds one net-new.
    - strong model "s" (pass-rate 3/4 = 0.75 >= cut -> frontier): pair blind, terminal_error catches
      one net-new on the frontier + one false alarm on a PASS.
    - an unlabeled row (passed None) that must be excluded from every count.
    """
    rows = []
    # weak model "w": 4 failures + 1 pass
    rows.append(_arow("w", 1, "f1", False, dang=True))                 # pair only
    rows.append(_arow("w", 1, "f2", False, ts=True, te=True))          # overlap: te AND pair
    rows.append(_arow("w", 1, "f3", False, te=True))                   # te net-new
    rows.append(_arow("w", 1, "f4", False))                            # missed by all
    rows.append(_arow("w", 1, "p1", True))                            # clean pass
    # strong model "s": pass-rate 3/4 = 0.75 >= 0.30 -> frontier; pair blind, te catches 1 net-new
    rows.append(_arow("s", 1, "g1", False, te=True))                  # te net-new ON FRONTIER
    rows.append(_arow("s", 1, "g2", True))
    rows.append(_arow("s", 1, "g3", True))
    rows.append(_arow("s", 1, "g4", True, te=True))                   # false alarm (te on a PASS)
    # an excluded (unlabeled) row — must not move any count
    rows.append(_arow("w", 1, "u1", "None", dang=True, ts=True, te=True))
    return rows


def test_additivity_decomposition_holds_on_fixture():
    s = _add.compute(_fixture_rows(), frontier_pass_rate=0.30)
    # 10 rows; u1 (passed None) excluded -> 9 labeled (5 fail: f1-f4,g1; 4 pass: p1,g2,g3,g4)
    assert (s.n_labeled, s.n_failed, s.n_passed) == (9, 5, 4)
    # terminal_error standalone: fires on f2,f3,g1 (fail) + g4 (pass) = 3 TP, 1 FP
    te = s.detectors["terminal_error"]
    assert (te.fired_fail, te.fired_pass) == (3, 1)
    # net-new = f3, g1 (f2 overlaps the pair); overlap = f2
    assert s.te_netnew_total == 2
    assert s.te_overlap_with_pair == 1
    # THE invariant: trio TP == pair TP + net-new (deduped, run-keyed)
    assert s.trio.tp == s.pair.tp + s.te_netnew_total
    # standalone TP splits exactly into net-new + overlap
    assert te.fired_fail == s.te_netnew_total + s.te_overlap_with_pair


def test_additivity_union_recall_is_monotone_and_correct():
    s = _add.compute(_fixture_rows(), frontier_pass_rate=0.30)
    # pair catches f1 (dang) + f2 (ts) = 2 of 5 failures
    assert s.pair.tp == 2
    # trio adds f3 + g1 = 4 of 5
    assert s.trio.tp == 4
    assert s.trio.recall >= s.pair.recall  # adding a detector can only raise recall
    assert s.trio.recall == 4 / 5


def test_additivity_frontier_split_only_counts_strong_models():
    s = _add.compute(_fixture_rows(), frontier_pass_rate=0.30)
    # only model "s" (pass-rate 0.75) is frontier; "w" (0.0) is not
    assert s.frontier_models == ["s"]
    # on the frontier the pair caught nothing; terminal_error caught g1 (net-new)
    assert s.frontier_pair_tp == 0
    assert s.frontier_te_netnew == 1
    assert s.te_netnew_frontier == 1
    # frontier net-new is a subset of total net-new
    assert 0 <= s.te_netnew_frontier <= s.te_netnew_total


def test_additivity_invariants_pass_on_fixture_and_catch_a_break():
    s = _add.compute(_fixture_rows(), frontier_pass_rate=0.30)
    assert _add.check_invariants(s) == []  # clean fixture: all hold
    # corrupt the decomposition and confirm the checker FAILS loud (not silently)
    s.te_netnew_total += 1
    problems = _add.check_invariants(s)
    assert problems, "check_invariants must flag a broken decomposition"
    assert any("trio TP" in p or "net-new" in p for p in problems)


def test_additivity_excludes_unlabeled_rows_never_guesses():
    """The unlabeled row fires all three detectors but passed is None — it must touch no count."""
    with_unlabeled = _fixture_rows()
    without = [r for r in with_unlabeled if r["task_name"] != "u1"]
    a = _add.compute(with_unlabeled, frontier_pass_rate=0.30)
    b = _add.compute(without, frontier_pass_rate=0.30)
    assert a.n_labeled == b.n_labeled == 9  # u1 excluded either way
    assert a.te_netnew_total == b.te_netnew_total
    assert a.detectors["terminal_error"].fired_fail == b.detectors["terminal_error"].fired_fail


def test_additivity_te_specific_folds_the_surgical_column():
    """docs/162: compute(te_specific=True) folds terminal_error_specific_fired — the surgical trio is
    a first-class SSOT claim. A row where the surgical mode fires but aware does not (the
    false-reassurance shape) lifts the trio recall under te_specific, leaving the aware trio
    untouched."""
    rows = [
        _arow("m", 1, "f1", False, dang=True),                          # pair catches
        # the false-reassurance failure: aware QUIET, specific-only FIRES (te=False, te_spec=True)
        _arow("m", 1, "f2", False, te=False, te_spec=True),
        _arow("m", 1, "f3", False),                                     # missed by all (under aware)
        _arow("m", 1, "p1", True),                                      # clean pass
    ]
    aware = _add.compute(rows, frontier_pass_rate=0.30, te_specific=False)
    surgical = _add.compute(rows, frontier_pass_rate=0.30, te_specific=True)
    # aware: terminal_error fires on nothing -> trio == pair (only f1)
    assert aware.detectors["terminal_error"].fired_fail == 0
    assert aware.trio.tp == aware.pair.tp == 1
    # surgical: terminal_error fires on f2 (net-new) -> trio gains a catch, recall rises
    assert surgical.detectors["terminal_error"].fired_fail == 1
    assert surgical.te_netnew_total == 1
    assert surgical.trio.tp == aware.pair.tp + 1 == 2
    assert surgical.trio.recall > aware.trio.recall
    # invariants still hold under the surgical fold
    assert _add.check_invariants(surgical) == []


def test_additivity_te_specific_on_old_rows_without_column_degrades_to_not_fired():
    """Refuse-to-guess: a rows file written before docs/162 has no specific column. te_specific=True
    must read a missing column as NOT-fired (never silently reuse the aware value), so the result
    degrades safely rather than raising or over-counting."""
    old_rows = [
        {"model": "m", "model_run": "m_1", "task_name": "f1", "passed": "False",
         "dangling_fired": "False", "tool_stream_fired": "False", "terminal_error_fired": "True"},
        {"model": "m", "model_run": "m_1", "task_name": "p1", "passed": "True",
         "dangling_fired": "False", "tool_stream_fired": "False", "terminal_error_fired": "False"},
    ]
    s = _add.compute(old_rows, frontier_pass_rate=0.30, te_specific=True)
    # the aware column says terminal_error fired on f1, but with NO specific column te_specific reads
    # not-fired -> terminal_error contributes 0 (never the aware "True")
    assert s.detectors["terminal_error"].fired_fail == 0


# ------------------------------------------------- classifier baseline (docs/160 SOTA head-to-head)
from benchmark.toolathlon import classifier_baseline as _clf  # noqa: E402


def _crow(passed, *, steps, run, textlen, dang=False, ts=False, te=False):
    return {
        "passed": str(passed),
        "n_tool_steps": str(steps),
        "tool_stream_run": str(run),
        "final_text_len": str(textlen),
        "dangling_fired": str(dang),
        "tool_stream_fired": str(ts),
        "terminal_error_fired": str(te),
    }


def test_classifier_label_excludes_unlabeled_never_guesses():
    """A None/blank label is excluded from training+scoring — never coerced to a class."""
    assert _clf._label({"passed": "True"}) is False   # passed -> not a failure
    assert _clf._label({"passed": "False"}) is True    # failed -> a failure
    assert _clf._label({"passed": ""}) is None
    assert _clf._label({"passed": "None"}) is None


def test_classifier_logreg_separates_a_linearly_separable_fixture():
    """The pure-python logreg actually learns: on a cleanly separable set it predicts held-out
    examples correctly — so the head-to-head is a real trained model, not a stub."""
    X = [[0.0], [0.1], [0.2], [5.0], [5.1], [5.2]]
    y = [0, 0, 0, 1, 1, 1]
    m = _clf._fit_logreg(X, y, epochs=400)
    proba = _clf._predict_proba(m, [[0.05], [5.05]])
    assert proba[0] < 0.5 < proba[1]


def test_classifier_f1_point_degenerates_to_base_on_high_base_rate():
    """The docs/159/160 mirage, pinned: on a high-base-rate set with weak structural signal, the
    classifier's F1-optimal operating point collapses to 'predict all fail' (lift ~0) — exactly why
    lift-at-deployable-falarm, not F1/accuracy, is the scoreboard a detector you ACT ON must use."""
    rows = []
    # 80% failures, structure carries almost no separating signal (overlapping distributions)
    for i in range(80):
        rows.append(_crow(False, steps=10 + (i % 3), run=1, textlen=900 + (i % 5)))
    for i in range(20):
        rows.append(_crow(True, steps=10 + (i % 3), run=1, textlen=900 + (i % 5)))
    X = [_clf._vec(r) for r in rows]
    y = [1 if _clf._label(r) else 0 for r in rows]
    held = _clf._held_out_proba(X, y, folds=5)
    _, preds = _clf._pick_threshold(held, y, objective="f1")
    base = sum(y) / len(y)
    s = _clf._score("f1", preds, y)
    # F1-optimal fires on (nearly) everything -> precision ~ base -> lift ~ 0
    assert s.fired >= 0.9 * len(y)
    assert abs(s.precision - base) < 0.05


def test_classifier_compare_runs_and_reports_both_regimes():
    """compare() returns the DOS detectors (zero-training) AND the trained clf at multiple operating
    points, so neither side is strawmanned. Smoke: structure-only mode runs and the scoreboard
    has the regime-distinguishing rows."""
    import io
    from pathlib import Path
    # write a tiny rows CSV to a temp path the module can read
    import tempfile, csv as _csv, os
    rows = []
    for i in range(60):
        rows.append(_crow(False, steps=20 + i, run=2, textlen=1500, te=(i < 5)))
    for i in range(40):
        rows.append(_crow(True, steps=5 + i, run=1, textlen=300))
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    try:
        res = _clf.compare(Path(path), folds=5, structure_only=True)
        names = [s.name for s in res["scores"]]
        assert any("terminal_error" in n for n in names)         # zero-training detector present
        assert any("held-out" in n for n in names)               # trained clf present, held-out
        assert any("IN-SAMPLE" in n for n in names)              # the optimism-gap row present
        assert res["base"] == 0.6                                 # 60/100 fail
    finally:
        os.unlink(path)


# --------------------------------------------------------------------------- conversion ceiling (lift gate)
# conversion_ceiling.py bounds the MAX possible WARN pass-rate lift offline ($0), the gate before any
# paid live A/B. These pin the load-bearing 'usable-data' grammar (a fire is recoverable ONLY when the
# value was already in hand AND usable) and the upper-bound invariants, so the gate can't silently
# inflate headroom.
from benchmark.toolathlon import conversion_ceiling as _cc  # noqa: E402


def test_usable_result_rejects_errors_empties_and_polls():
    # usable data a WARN could re-surface
    assert _cc.is_usable_result('{"rows": [["alice", 30], ["bob", 25]]}') is True
    assert _cc.is_usable_result("The file contains 3 sections: intro, body, conclusion.") is True
    # NOT usable — empty / error envelope / tool-not-found / no-output / still-converting poll
    assert _cc.is_usable_result("") is False
    assert _cc.is_usable_result("   ") is False
    assert _cc.is_usable_result("Tool excel-read not found in agent") is False
    assert _cc.is_usable_result("Error executing Python code: NameError") is False
    assert _cc.is_usable_result('{"status": 503, "msg": "unavailable"}') is False
    assert _cc.is_usable_result("Traceback (most recent call last):") is False
    assert _cc.is_usable_result('{"status": "still converting"}') is False


def test_tool_stream_recoverable_only_when_looped_result_is_usable():
    """A loop over USABLE bytes is recoverable; a loop over an error envelope is NOT."""
    def looped(result_bytes):
        msgs = []
        for i in range(3):  # 3x identical -> REPEATING
            msgs.append(_asst(None, calls=[{"id": str(i), "name": "db-poll", "args": {"q": "1"}}]))
            msgs.append(_tool(str(i), result_bytes))
        return parse_record(_record("t", False, msgs))

    rec_usable = _cc.classify_recoverability(looped('{"rows": [["data", 1]]}'))
    assert rec_usable.tool_stream_fired and rec_usable.tool_stream_recoverable

    rec_error = _cc.classify_recoverability(looped("Error running tool db-poll: timeout"))
    assert rec_error.tool_stream_fired and not rec_error.tool_stream_recoverable


def test_terminal_error_recoverable_is_always_false_by_design():
    """terminal_error is the wall, not a held value — it never counts as recoverable (honest ceiling)."""
    msgs = [
        {"role": "user", "content": "x"},
        _asst(None, calls=[{"id": "1", "name": "api-call", "args": {}}]),
        _tool("1", '{"status": 500, "error": "server error"}'),
        _asst("The server returned an error."),
    ]
    rec = _cc.classify_recoverability(parse_record(_record("t", False, msgs)))
    assert rec.terminal_error_recoverable is False  # always False, regardless of whether it fired


def test_ceiling_is_an_upper_bound_recov_subset_of_fires():
    """The core gate invariant: recoverable fires <= fires, and max_lift_pp <= fire_rate*100, per
    model and corpus. A ceiling that exceeds the fire mass would be inflating headroom."""
    result = _cc.compute_ceiling(_cc.load_cached_corpus()).to_dict()
    for m in result["models"]:
        assert 0 <= m["recoverable_fires"] <= m["fires"], m["model"]
        assert m["max_lift_pp"] <= 100.0 * m["fires"] / m["n_tasks"] + 1e-9, m["model"]
    # corpus recoverable is the sum of per-model recoverable (no double counting)
    assert result["corpus"]["recoverable_fires"] == sum(m["recoverable_fires"] for m in result["models"])
    # terminal_error contributes zero recoverable corpus-wide (the honest-ceiling rule)
    assert sum(m["recoverable_by_detector"]["terminal_error"] for m in result["models"]) == 0
