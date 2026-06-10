"""Tests for restart_counterfactual.py — the $0 slice-sizing gate for the seeded-restart live spend.

No gym, no model, no network. Drives the pure replay functions over hand-built recorded-run dicts that
mirror the REAL JSON shape probed from live_results/*/results_*.json (conversation_flow with dos_block
events carrying tool_name + unsupported; tool_results with tool_name + result).

The class these tests pin is the one a real audit run already caught: the BLOCK-arm thrash is an
arg-provenance INVENTED-ID block (recorded as a dos_block event), NOT a gym env error — so the slice
classifier must read the blocked-id signature (`unsupported`), not the env-error grammar. The first
draft read the wrong channel and reported a false 0% slice; these tests lock the regime-aware fix.
"""
import restart_counterfactual as rc


def _block_event(tool, ids):
    return {"type": "dos_block", "tool_name": tool, "unsupported": list(ids)}


def _run(cf=None, tool_results=None):
    return {"conversation_flow": cf or [], "tool_results": tool_results or []}


# ---------------------------------------------------------------------------
# _blocks_per_tool — recover the live loop's _block_counts from logged dos_block events
# ---------------------------------------------------------------------------
def test_blocks_per_tool_counts_dos_block_events():
    run = _run(cf=[
        {"type": "system_message"},
        _block_event("create_new_case", ["contact_id"]),
        _block_event("create_new_case", ["contact_id"]),
        _block_event("link_new_case_sla", ["sla_id"]),
    ])
    c = rc._blocks_per_tool(run)
    assert c["create_new_case"] == 2
    assert c["link_new_case_sla"] == 1


def test_blocks_per_tool_ignores_non_block_events():
    run = _run(cf=[{"type": "ai_message"}, {"type": "tool_result", "tool_name": "x"}])
    assert rc._blocks_per_tool(run) == {}


# ---------------------------------------------------------------------------
# _restart_fires — the REAL restart_decision trigger applied to a recorded run
# ---------------------------------------------------------------------------
def test_restart_fires_on_second_block_only():
    once = _run(cf=[_block_event("t", ["a"])])
    assert rc._restart_fires(once) == []  # block_count 1 < threshold 2

    twice = _run(cf=[_block_event("t", ["a"]), _block_event("t", ["a"])])
    assert rc._restart_fires(twice) == ["t"]


def test_restart_fires_is_one_shot_per_tool():
    # a tool blocked 3× still fires exactly once (the live one-restart-per-tool cap)
    thrice = _run(cf=[_block_event("t", ["a"])] * 3)
    assert rc._restart_fires(thrice) == ["t"]


def test_restart_fires_on_multiple_distinct_thrash_tools():
    run = _run(cf=[
        _block_event("a", ["x"]), _block_event("a", ["x"]),
        _block_event("b", ["y"]), _block_event("b", ["y"]),
    ])
    assert sorted(rc._restart_fires(run)) == ["a", "b"]


# ---------------------------------------------------------------------------
# _block_thrash_class — the regime-aware fix: SAME/VARYING off the blocked-id signature
# ---------------------------------------------------------------------------
def test_block_thrash_same_when_same_id_reinvented():
    # the real upstream-omission tell: the agent re-invents the SAME missing id every block
    run = _run(cf=[
        _block_event("update_configuration_item", ["configuration_item_id"]),
        _block_event("update_configuration_item", ["configuration_item_id"]),
    ])
    assert rc._block_thrash_class(run, "update_configuration_item") == "same"


def test_block_thrash_varying_when_different_ids():
    # exploratory: different invented ids across blocks (configuration_item_id -> owner_id)
    run = _run(cf=[
        _block_event("update_configuration_item", ["configuration_item_id"]),
        _block_event("update_configuration_item", ["owner_id"]),
    ])
    assert rc._block_thrash_class(run, "update_configuration_item") == "varying"


def test_block_thrash_unknown_under_two_blocks():
    run = _run(cf=[_block_event("t", ["a"])])
    assert rc._block_thrash_class(run, "t") == "unknown"


def test_block_thrash_id_order_insensitive():
    # a multi-id block set is compared as a sorted set, so ordering is not spuriously 'varying'
    run = _run(cf=[
        _block_event("t", ["a", "b"]),
        _block_event("t", ["b", "a"]),
    ])
    assert rc._block_thrash_class(run, "t") == "same"


# ---------------------------------------------------------------------------
# _thrash_class — regime dispatch: block signature first, env-error grammar fallback
# ---------------------------------------------------------------------------
def test_thrash_class_uses_block_signature_when_present():
    run = _run(cf=[
        _block_event("t", ["id1"]),
        _block_event("t", ["id1"]),
    ])
    # block signature wins even though there are no struct-error tool_results
    assert rc._thrash_class(run, "t") == "same"


def test_thrash_class_falls_back_to_env_grammar_without_blocks():
    # no id-bearing blocks → defer to the natural-regime env-error classifier; with no struct errors
    # recorded it returns 'unknown' (not a crash) — the safe fallback
    run = _run(cf=[], tool_results=[{"tool_name": "t", "result": {"ok": True}}])
    assert rc._thrash_class(run, "t") == "unknown"


# ---------------------------------------------------------------------------
# _discarded_window_turns — the cost half (messages[2:] = everything past [System, Human])
# ---------------------------------------------------------------------------
def test_discarded_window_drops_system_and_human():
    cf = [{"type": "system_message"}, {"type": "user_message"},
          {"type": "ai_message"}, {"type": "tool_result"}]
    discarded = rc._discarded_window_turns(_run(cf=cf))
    assert len(discarded) == 2  # the 2 turns past [System, Human] a restart re-pays


def test_discarded_window_empty_when_no_progress():
    cf = [{"type": "system_message"}, {"type": "user_message"}]
    assert rc._discarded_window_turns(_run(cf=cf)) == []
