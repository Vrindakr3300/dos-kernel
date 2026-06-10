"""Tests for the EnterpriseOps-Gym DOS harness (docs/143) — the consumer-side proof.

Covers the pure pieces that run with NO gym / LLM / Docker: the `dos_react` nudge helpers
(write-verb classifier, corpus build, per-call evaluation, nudge text) and the simulator's
A/B dynamics (the bump is positive, emergent — vanishes when the mechanism cannot act, and
the false-nudge rate on legit derived ids is ~0).

These pin the harness so a refactor of `dos.arg_provenance` that broke the mechanism would
fail here, not only in a slow real run.
"""
from __future__ import annotations

from benchmark.enterpriseops.dos_react import (
    build_nudge_text,
    build_prior_results,
    evaluate_tool_call,
    is_mutating_tool,
)
from benchmark.enterpriseops.simulator import SimParams, run_split
from dos.arg_provenance import CorpusSource


# ── dos_react: the write-verb classifier (fail-open) ─────────────────────────

def test_mutating_classifier_fires_on_write_verbs():
    for name in ("create_incident", "update_user", "delete_record", "send_email",
                 "add_member", "incident.create", "assign-task", "close_case"):
        assert is_mutating_tool(name) is True, name


# ── docs/147: the precursor-presence consult (the consumer's pure path) ───────

def test_precursor_consult_warns_on_skipped_prerequisite():
    """The consult builds a CallStream from prior tool_results and folds the gate. A mutating
    call whose mandated precursor never fired → REFUTED → a WARN decision (the call still
    dispatches). Mirrors the wiring in DosReactOrchestrator.execute without needing the gym."""
    from dos.evidence import EvidenceStance
    from dos.intervention import Intervention
    from dos.precursor_gate import (
        CallStream, MutatingCall, PriorCall, classify_call, precursor_intervention,
        grammar_from_table,
    )
    # The grounded gym rule: link_new_case_sla must be preceded by update_case (the state
    # transition). Here the agent skips it — only an unrelated read fired.
    grammar = grammar_from_table({"requires": {"link_new_case_sla": ["update_case"]}})
    prior = [{"tool_name": "get_case", "result": {}}]
    stream = CallStream(calls=tuple(PriorCall(tool_name=tr["tool_name"]) for tr in prior))
    verdict = classify_call(
        MutatingCall(tool_name="link_new_case_sla", is_mutating=True), stream, grammar)
    assert verdict.stance is EvidenceStance.REFUTED
    decision = precursor_intervention(verdict)
    assert decision is not None and decision.intervention is Intervention.WARN
    assert decision.rung.dispatches is True  # the call still proceeds (turn preserved)


def test_precursor_consult_silent_when_prerequisite_present():
    """When update_case DID fire before link_new_case_sla → ATTESTED → no intervention."""
    from dos.precursor_gate import (
        CallStream, MutatingCall, PriorCall, classify_call, precursor_intervention,
        grammar_from_table,
    )
    grammar = grammar_from_table({"requires": {"link_new_case_sla": ["update_case"]}})
    prior = [{"tool_name": "get_case"}, {"tool_name": "update_case"}]
    stream = CallStream(calls=tuple(PriorCall(tool_name=tr["tool_name"]) for tr in prior))
    verdict = classify_call(
        MutatingCall(tool_name="link_new_case_sla", is_mutating=True), stream, grammar)
    assert precursor_intervention(verdict) is None


def test_real_gym_grammar_file_loads():
    """The hand-authored benchmark/enterpriseops/precursor_grammar.toml parses into a grammar
    with the two grounded rules (the 'written, never inferred' artifact, docs/147 §0)."""
    import os
    from dos.precursor_gate import load_from_toml
    path = os.path.join(
        os.path.dirname(__file__), "..", "benchmark", "enterpriseops", "precursor_grammar.toml")
    g = load_from_toml(path)
    assert g.required_set("link_new_case_sla") == frozenset({"update_case"})
    assert g.required_set("update_case") == frozenset({"get_case"})


def test_mutating_classifier_fails_open_on_reads():
    for name in ("get_incident", "list_users", "search_kb", "query_table",
                 "fetch_record", "describe_schema", "whoami"):
        assert is_mutating_tool(name) is False, name


def test_explicit_schema_overrides_heuristic():
    # an explicit read_tools set wins over a write-verb-looking name
    assert is_mutating_tool("create_view", read_tools={"create_view"}) is False
    # an explicit mutating_tools set is authoritative
    assert is_mutating_tool("frobnicate", mutating_tools={"frobnicate"}) is True
    assert is_mutating_tool("frobnicate", mutating_tools={"other"}) is False


# ── dos_react: corpus build + per-call evaluation ────────────────────────────

def test_corpus_tags_task_text_and_tool_results():
    prior = build_prior_results("the task prose", [{"result": {"number": "INC0010023"}}])
    sources = {b.source for b in prior.blobs}
    assert CorpusSource.TASK_TEXT in sources
    assert CorpusSource.TOOL_RESULT in sources


def test_evaluate_minted_fk_nudges():
    v = evaluate_tool_call(
        "create_incident", {"parent": "INC9999999"}, "do the task",
        [{"result": {"number": "INC0010023"}}],
    )
    assert v.believe is False
    assert v.unsupported == ("parent",)
    assert "INC9999999" in build_nudge_text(v, "create_incident")


def test_evaluate_resolved_fk_silent():
    v = evaluate_tool_call(
        "create_incident", {"caller_id": "INC0010023"}, "task",
        [{"result": {"number": "INC0010023"}}],
    )
    assert v.believe is True


def test_evaluate_read_call_not_gated():
    v = evaluate_tool_call(
        "get_incident", {"number": "INC9999999"}, "task", [{"result": {"x": 1}}],
    )
    assert v.believe is True


def test_evaluate_new_key_exempt():
    v = evaluate_tool_call(
        "create_user", {"email": "fresh@acme.com"}, "task",
        [{"result": {"x": 1}}], new_key_args={"email"},
    )
    assert v.believe is True


def test_evaluate_truly_empty_corpus_abstains():
    """A genuinely empty corpus (no task text, no prior results) → ABSTAIN (cannot prove
    mintage on step zero)."""
    v = evaluate_tool_call("create_incident", {"parent": "INC9999999"}, "", [])
    assert v.believe is True


def test_evaluate_task_text_only_id_present_believed():
    """On the first mutating call, an FK named in the TASK TEXT is provenance (env-authored)
    → believed even with no tool results yet."""
    v = evaluate_tool_call(
        "create_incident", {"parent": "INC0010023"},
        "Please link the new record to incident INC0010023.", [],
    )
    assert v.believe is True


def test_evaluate_task_text_absent_id_nudged_on_first_mutate():
    """An FK that is neither in the task text nor any read result IS minted, even on an
    early call — the nudge correctly fires (the task text is part of the corpus, so the
    call is not 'empty')."""
    v = evaluate_tool_call(
        "create_incident", {"parent": "INC9999999"},
        "Please process the open incidents for the finance team.", [],
    )
    assert v.believe is False
    assert v.unsupported == ("parent",)


# ── simulator: the A/B dynamics (the bump is positive AND emergent) ──────────

def test_r1_lifts_integrity_slice():
    """R1 (the arg_provenance nudge) lifts the Integrity slice by a clear margin with the
    feasible-task rate flat — the docs/143 R1 gate."""
    r0, r1 = run_split(seed=1, n_tasks=300, params=SimParams())
    assert r1.integrity_rate > r0.integrity_rate + 4.0
    # feasible-task rate must not regress (the §8 kill-signal)
    assert r1.feasible_rate >= r0.feasible_rate - 1.0


def test_bump_vanishes_when_nudge_ignored():
    """q_recover=0 → the agent ignores every nudge → the bump must be ~0 (proving the delta
    is recovery-driven, not a measurement artifact)."""
    p = SimParams(q_recover=0.0)
    r0, r1 = run_split(seed=1, n_tasks=300, params=p)
    assert abs(r1.integrity_rate - r0.integrity_rate) < 0.5


def test_bump_shrinks_with_fewer_mints():
    """Fewer mints → less catchable surface → a smaller bump (monotonicity, the
    mechanism-driven signature)."""
    hi = SimParams(p_mint_base=0.20)
    lo = SimParams(p_mint_base=0.05)
    r0h, r1h = run_split(seed=2, n_tasks=400, params=hi)
    r0l, r1l = run_split(seed=2, n_tasks=400, params=lo)
    assert (r1h.integrity_rate - r0h.integrity_rate) > (r1l.integrity_rate - r0l.integrity_rate)


def test_false_nudge_rate_on_derived_ids_is_low():
    """The kill-signal guard: the detector must rarely false-flag a legit DERIVED id (the
    component-decomposition + derived-id containment rungs drive this toward ~0)."""
    p = SimParams(derive_rate=0.5)  # half the correct resolutions are derived forms
    _, r1 = run_split(seed=3, n_tasks=500, params=p)
    # false nudges should be a tiny fraction of total nudges (well under 5%)
    if r1.n_nudged:
        assert r1.n_false_nudges / r1.n_nudged < 0.05


# ── the `dos arg-provenance` CLI verb (the operator surface) ─────────────────

def test_cli_arg_provenance_minted_exit_3(capsys):
    """A minted id arg → exit 3 (UNSUPPORTED) + the arg named."""
    from dos import cli
    rc = cli.main([
        "arg-provenance", "--tool", "create_incident",
        "--args", '{"parent":"INC9999999"}', "--prior", '{"number":"INC0010023"}',
    ])
    assert rc == 3
    out = capsys.readouterr().out
    assert "UNSUPPORTED" in out and "parent" in out


def test_cli_arg_provenance_resolved_exit_0(capsys):
    """A resolved id arg → exit 0 (BELIEVE)."""
    from dos import cli
    rc = cli.main([
        "arg-provenance", "--tool", "create_incident",
        "--args", '{"caller_id":"INC0010023"}', "--prior", '{"number":"INC0010023"}',
    ])
    assert rc == 0
    assert "BELIEVE" in capsys.readouterr().out


def test_cli_arg_provenance_read_not_gated(capsys):
    """--read marks the call non-mutating → never gated, exit 0."""
    from dos import cli
    rc = cli.main([
        "arg-provenance", "--tool", "get_incident",
        "--args", '{"number":"INC9999999"}', "--prior", '{"x":1}', "--read",
    ])
    assert rc == 0


def test_cli_arg_provenance_json_shape(capsys):
    """--json emits the believe/unsupported/args/reason shape."""
    import json as _json
    from dos import cli
    rc = cli.main([
        "arg-provenance", "--tool", "create_incident",
        "--args", '{"parent":"INC9999999"}', "--prior", '{"number":"INC0010023"}', "--json",
    ])
    assert rc == 3
    d = _json.loads(capsys.readouterr().out)
    assert set(d) == {"believe", "args", "unsupported", "reason"}
    assert d["believe"] is False and d["unsupported"] == ["parent"]


def test_cli_arg_provenance_new_key_exempt(capsys):
    """--new-key marks a create's own identity as non-reference → never nudged."""
    from dos import cli
    rc = cli.main([
        "arg-provenance", "--tool", "create_user",
        "--args", '{"email":"new@acme.com"}', "--prior", '{"x":1}', "--new-key", "email",
    ])
    assert rc == 0
