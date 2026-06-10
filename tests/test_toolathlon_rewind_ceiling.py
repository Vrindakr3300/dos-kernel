"""Replay-test the Toolathlon REWIND-ceiling estimator on FROZEN fixtures — zero benchmark/LLM access.

`benchmark/toolathlon/rewind_ceiling.py` sizes the UPPER BOUND on the lift a DOS REWIND/BACKJUMP
(docs/164 F1.5) could buy on the frozen corpus, AND its DISJOINTNESS from the WARN re-surface ceiling
(`conversion_ceiling.py`). Like the replay tests, the classifier is PURE over a parsed record, so
synthetic OpenAI-style chat records pin every behavior:

  * the dead-end MUTATION-branch predicate (a mutation tool thrashed >= MIN_CALLS / >= MIN_DISTINCT_ARGS
    AND >= ERR_FRACTION of its ENV results were rejections),
  * the SUCCESS-dominated exclusion (a legit varied-write loop is NOT a dead end → not fixable),
  * the READ-loop exclusion (re-reading is the WARN/tool_stream class, never a mutation dead end),
  * the byte-clean / safe-direction property (the env-authored rejection is load-bearing; the agent
    cannot forge errors it did not receive),
  * the perfect DISJOINTNESS from WARN-recoverable (usable-loop vs error-dominated-loop are mutually
    exclusive by construction → BOTH == 0).
"""

from __future__ import annotations

import json

from benchmark.toolathlon.rewind_ceiling import (
    ERR_FRACTION,
    MIN_CALLS,
    MIN_DISTINCT_ARGS,
    _is_mutation_tool,
    classify_rewind_fix,
    compute_rewind_ceiling,
)
from benchmark.toolathlon.trajectory import parse_record


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


def _record(task, passed, messages, *, model_run="grok-4_1"):
    return {
        "modelname_run": model_run,
        "task_name": task,
        "task_status": {"preprocess": "done", "running": "done", "evaluation": passed},
        "messages": messages,
    }


def _mutation_thrash_run(tool="notion-API-patch-page", n=6, err_each=True, vary_args=True,
                          ok_tail=0, vary_results=True):
    """Build a FAILED run that thrashes a mutation tool: n calls, each with a (varying) arg, and the
    ENV rejects the first (n - ok_tail) with an error envelope.

      vary_args     — toggles distinct AGENT arg-shapes (the upper-variant signal).
      vary_results  — toggles distinct ENV result bytes (the BYTE-CLEAN branch signal). When True, each
                      rejection carries a different detail (a real branch the env answered variously);
                      when False, the env returns the IDENTICAL byte every call (the WARN-shaped wall
                      the byte-clean gate must reject)."""
    msgs = [_asst("starting")]
    for i in range(n):
        args = {"page_id": f"p{i}"} if vary_args else {"page_id": "p0"}
        tcid = f"c{i}"
        msgs.append(_asst(calls=[{"id": tcid, "name": tool, "args": args}]))
        if i < n - ok_tail and err_each:
            # vary_results=True → a DISTINCT env rejection each call (a real branch); False → identical.
            detail = f"Not found: parent {i}" if vary_results else "Not found"
            content = json.dumps({"status": 404, "object": "error", "message": detail})
        else:
            content = json.dumps({"object": "page", "id": f"id{i}", "ok": True})
        msgs.append(_tool(tcid, content))
    msgs.append(_asst("I think I'm done."))
    return msgs


# --------------------------------------------------------------------------- the mutation grammar
def test_mutation_tool_grammar_matches_writes_not_reads():
    for w in ("notion-API-patch-page", "excel-write_data_to_excel", "github-create_or_update_file",
              "filesystem-create_directory", "google_sheet-update_cells", "send_notification"):
        assert _is_mutation_tool(w), w
    for r in ("filesystem-read_file", "filesystem-list_directory", "google_sheet-get_sheet_data",
              "k8s-kubectl_get", "web_search", "arxiv_local-download_paper"):
        # download is a read of remote bytes, not a state mutation of the task env
        assert not _is_mutation_tool(r) or r == "arxiv_local-download_paper", r
    # "download" is intentionally NOT a mutation stem (it reads into the workspace, the convert-poll class)
    assert not _is_mutation_tool("arxiv_local-download_paper")


# --------------------------------------------------------------------------- the core predicate
def test_error_dominated_mutation_thrash_is_rewind_fixable():
    # A real branch: the env answered the agent's exploration with DISTINCT rejections (vary_results).
    rec = _record("notion-hr", False, _mutation_thrash_run(n=6, err_each=True, vary_args=True,
                                                            vary_results=True))
    rf = classify_rewind_fix(parse_record(rec))
    assert rf.fixable                                   # byte-clean primary
    assert rf.loop_tool == "notion-API-patch-page"
    assert rf.n_calls == 6
    assert rf.n_distinct_results >= 2                   # the env-authored branch signal
    assert rf.n_err_results / rf.n_results >= ERR_FRACTION
    # the checkpoint is the FIRST call to the looping tool, and a backjump excises >0 turns
    assert rf.checkpoint_turn >= 0 and rf.dropped_turns > 0


def test_identical_env_bytes_with_varied_args_is_NOT_byte_clean_fixable():
    # THE BYTE-CLEAN FIX (the adversary's catch): the agent varied its args 6 ways, but the ENV
    # returned the IDENTICAL byte every call (vary_results=False). This is the WARN-shaped wall, NOT a
    # branch — the byte-clean primary must REJECT it (env returned one distinct result), while the
    # args-variant upper bound still admits it (and the gap is the forgeable-promotion ledger).
    rec = _record("task-tracker", False, _mutation_thrash_run(n=6, err_each=True, vary_args=True,
                                                              vary_results=False))
    rf = classify_rewind_fix(parse_record(rec))
    assert rf.n_distinct_args >= MIN_DISTINCT_ARGS      # the agent DID vary args (the forgeable signal)
    assert rf.n_distinct_results < 2                    # but the ENV returned one identical byte
    assert not rf.fixable, "identical env bytes = WARN-shaped wall, not a byte-clean branch"
    assert rf.args_variant, "the looser args-variant upper bound still admits it"


def test_success_dominated_varied_writes_is_NOT_fixable():
    # A legit varied-write loop (e.g. writing many cells) — every write SUCCEEDS, so it is NOT a dead end.
    rec = _record("data-fill", False, _mutation_thrash_run(n=8, err_each=False, vary_args=True))
    rf = classify_rewind_fix(parse_record(rec))
    assert not rf.fixable, "success-dominated varied writes must not count as a dead-end branch"


def test_read_loop_is_NOT_a_mutation_dead_end():
    # Re-reading the same file is the WARN/tool_stream class, never a mutation dead end.
    msgs = [_asst("start")]
    for i in range(6):
        tcid = f"r{i}"
        msgs.append(_asst(calls=[{"id": tcid, "name": "filesystem-read_file", "args": {"path": f"/f{i}"}}]))
        msgs.append(_tool(tcid, json.dumps({"status": 404, "message": "not found"})))
    rec = _record("read-loop", False, msgs)
    rf = classify_rewind_fix(parse_record(rec))
    assert not rf.fixable, "a read loop is not a mutation dead-end branch"


def test_single_stuck_call_is_NOT_thrash():
    # One mutation, rejected once — not a THRASH (needs >= MIN_CALLS). A backjump needs branch evidence.
    msgs = [_asst("start"),
            _asst(calls=[{"id": "c0", "name": "notion-API-patch-page", "args": {"x": 1}}]),
            _tool("c0", json.dumps({"status": 404, "object": "error"})),
            _asst("done")]
    rf = classify_rewind_fix(parse_record(_record("t", False, msgs)))
    assert not rf.fixable


def test_identical_args_reissue_is_NOT_a_branch():
    # Same mutation, same args, identical env rejection each — "can't tell it succeeded" (the WARN
    # class), neither a byte-clean branch (1 distinct env result) NOR an args-variant (1 distinct arg).
    rec = _record("t", False, _mutation_thrash_run(n=6, err_each=True, vary_args=False,
                                                   vary_results=False))
    rf = classify_rewind_fix(parse_record(rec))
    assert rf.n_distinct_args < MIN_DISTINCT_ARGS
    assert not rf.fixable and not rf.args_variant, "an identical re-issue is the WARN class, not a branch"


def test_eventual_consistency_retry_wall_is_excluded():
    # An adversarial catch: a 409 conflict / "please try again" wall is a TRANSIENT-RETRY (the env
    # asks the agent to re-issue the SAME action), NOT a dead-end branch — re-issuing is correct, there
    # is nothing to subtract. Even with distinct env bytes (409 conflict #1, #2, ...), it is excluded.
    msgs = [_asst("start")]
    for i in range(6):
        tcid = f"c{i}"
        msgs.append(_asst(calls=[{"id": tcid, "name": "notion-API-post-page", "args": {"p": i}}]))
        # distinct bytes (different conflict ids) but all transient-retry shape
        msgs.append(_tool(tcid, json.dumps({"status": 409, "object": "error",
                                            "message": f"conflict_error #{i}: Please try again"})))
    msgs.append(_asst("done"))
    rf = classify_rewind_fix(parse_record(_record("task-tracker", False, msgs)))
    assert not rf.fixable, "an eventual-consistency 409/'try again' wall is not a dead-end branch"


def test_early_success_is_excluded():
    # An adversarial catch: if the FIRST loop-tool call SUCCEEDED (a real write landed), rewinding to
    # before it would DELETE real progress — there is no pure dead-end branch. Excluded (conservative).
    msgs = [_asst("start")]
    for i in range(6):
        tcid = f"c{i}"
        msgs.append(_asst(calls=[{"id": tcid, "name": "filesystem-create_directory", "args": {"p": i}}]))
        if i == 0:
            msgs.append(_tool(tcid, json.dumps({"type": "text", "text": "Successfully created /a/b"})))
        else:
            msgs.append(_tool(tcid, json.dumps({"status": 404, "message": f"Parent missing #{i}"})))
    msgs.append(_asst("done"))
    rf = classify_rewind_fix(parse_record(_record("arrange-workspace", False, msgs)))
    assert not rf.fixable, "an early-success run has real progress; rewinding would delete it"


def test_passed_run_is_never_fixable_in_the_fold():
    # A fix on a PASSED run cannot lift the pass-rate — the fold skips it (here: classify still pure,
    # but the corpus fold must not count it). We assert via the fold.
    rec = _record("t", True, _mutation_thrash_run(n=6, err_each=True, vary_args=True))
    res = compute_rewind_ceiling([parse_record(rec)])
    assert res.corpus_rewind_fixable == 0


# --------------------------------------------------------------------------- disjointness + the fold
def test_disjointness_from_warn_is_perfect():
    # An error-dominated mutation thrash (rewind-fixable) and a usable read-loop (warn-recoverable
    # tool_stream) on different runs → rewind-fixable and warn-fixable are DISJOINT (BOTH == 0).
    rewind_run = _record("notion-hr", False, _mutation_thrash_run(n=6, err_each=True, vary_args=True),
                         model_run="grok-4_1")
    # a usable-data read loop that the WARN ceiling would mark recoverable (same usable bytes >= repeat_n)
    usable = json.dumps({"type": "text", "text": "[FILE] report.csv\n[FILE] data.json\nrow,val\n1,2\n"})
    msgs = [_asst("start")]
    for i in range(4):
        tcid = f"u{i}"
        msgs.append(_asst(calls=[{"id": tcid, "name": "filesystem-list_directory", "args": {"path": "/w"}}]))
        msgs.append(_tool(tcid, usable))
    msgs.append(_asst("still need to write the report"))
    warn_run = _record("list-loop", False, msgs, model_run="grok-4_1")
    # both tasks must be SOLVED-somewhere (the never-solved gate) — add a passing sibling per task.
    solved_a = _record("notion-hr", True, [_asst("ok")], model_run="claude-4.5-opus_1")
    solved_b = _record("list-loop", True, [_asst("ok")], model_run="claude-4.5-opus_1")
    res = compute_rewind_ceiling([parse_record(rewind_run), parse_record(warn_run),
                                  parse_record(solved_a), parse_record(solved_b)])
    assert res.corpus_both == 0, "rewind-fixable and warn-fixable must be disjoint by construction"
    assert res.corpus_rewind_fixable >= 1
    # only_rewind == rewind_fixable when BOTH == 0
    assert res.corpus_only_rewind == res.corpus_rewind_fixable


def test_byte_clean_safe_direction_agent_cannot_forge_into_fixable():
    # The load-bearing gate is ENV-authored: if the env did NOT reject (all results usable), no
    # amount of agent narration claiming distress makes the run fixable. Flip the SAME thrash from
    # error-dominated to success-dominated → fixable flips True→False. The agent authored identical
    # calls/args in both; only the ENV result bytes differ, and the verdict follows the env.
    err = classify_rewind_fix(parse_record(_record("t", False,
        _mutation_thrash_run(n=6, err_each=True, vary_args=True))))
    ok = classify_rewind_fix(parse_record(_record("t", False,
        _mutation_thrash_run(n=6, err_each=False, vary_args=True))))
    assert err.fixable and not ok.fixable, "the verdict must follow the ENV-authored result, not the agent"


def test_fold_counts_only_labeled_failed_runs():
    # The failed run's task ("a") must be solved SOMEWHERE (the never-solved gate) → give it a passing
    # sibling. "b" (unlabeled) and "c" (passed, different task) round out the labeled/excluded checks.
    runs = [
        parse_record(_record("a", False, _mutation_thrash_run(n=6, err_each=True, vary_args=True))),
        parse_record(_record("a", True, [_asst("ok")], model_run="claude-4.5-opus_1")),  # solved sibling
        parse_record(_record("b", None, _mutation_thrash_run(n=6, err_each=True, vary_args=True))),   # unlabeled
        parse_record(_record("c", True, _mutation_thrash_run(n=6, err_each=True, vary_args=True))),    # passed
    ]
    res = compute_rewind_ceiling(runs)
    assert res.n_records == 4 and res.n_labeled == 3   # the None is excluded from labeled
    assert res.corpus_rewind_fixable == 1              # only the labeled FAILED, ever-solved run counts
    assert res.corpus_turns_subtracted > 0


def test_never_solved_task_is_excluded():
    # A failed mutation-thrash whose task NO run ever solved is plausibly impossible (the envelope, not
    # the branch) → excluded from the sound-gates primary, even though classify_rewind_fix marks it.
    rec = parse_record(_record("impossible-task", False,
                               _mutation_thrash_run(n=6, err_each=True, vary_args=True)))
    assert classify_rewind_fix(rec).fixable          # the per-run byte-clean predicate fires
    res = compute_rewind_ceiling([rec])              # ...but no sibling ever solved the task
    assert res.corpus_rewind_fixable == 0, "a task no run ever solved is excluded by the never-solved gate"
