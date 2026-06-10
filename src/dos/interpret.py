"""Agent-facing interpretation — one line of "what this verdict means for your
NEXT action," shared by every surface that speaks to an agent.

Why this module exists (the de-duplication that makes parity structural)
========================================================================

A kernel verdict is deliberately terse: `{"shipped": false, "source": "none"}`,
`{"outcome": "refuse", ...}`. That is the right *machine* contract — a closed,
byte-faithful shape a pipe consumer can parse. But an LLM agent acts measurably
better on the *gloss* than on the bare dict: it does the right thing far more
often when told "treat this as NOT done; do NOT accept a worker's claim it
shipped without evidence" than when handed `{"shipped": false}` and left to
infer the discipline. The MCP server learned this first and grew an
`interpretation` field on every tool return. The `dos` CLI is the *more*-used
agent surface, though, and an agent shelling `dos verify --json` got only the
bare dict — the better intelligence lived behind the `[mcp]` extra, which is
backwards.

This module is that intelligence, lifted to ONE place both surfaces import:
the MCP tools (`dos_mcp.server`) and the CLI's opt-in `--explain` flag
(`dos verify --explain`, `dos arbitrate --explain`) both call the SAME function,
so they can never drift — the parity is structural, not a copy kept in sync by
hand. A `tests/test_interpret_parity.py` pins that the two surfaces emit
byte-identical interpretation strings for the same verdict.

Not every gloss has BOTH surfaces yet: `verify`/`arbitrate`/`check_reason` are
emitted by both the MCP tools and the CLI, and the parity is cross-tested.
`gate` is so far CLI-only (`dos gate --explain`) — there is no `dos_gate` MCP
tool — but it lives here, beside the others, so the gloss style stays consistent
and it is parity-ready the day a gate tool is added. (Same one-invariant either
way: pure presentation, downstream of an already-decided verdict.)

The one invariant (the renderer/Axis-4 rule, applied here)
==========================================================

**An interpretation is PURE PRESENTATION, strictly downstream of an
already-decided verdict.** Each function takes the verdict's own `to_dict()`
(a plain dict) and returns a string. It receives no config, no leases, nothing
it could decide *with* — exactly the constraint `dos.render` puts on a renderer.
So the hint can never leak policy back into the adjudication: the worst a wrong
gloss can do is read awkwardly; it cannot mis-verify a ship or mis-admit a lease.
That is why this lives beside `render.py` (presentation seam, layer 3), not
inside a verdict module like `oracle.py` — the adjudication core stays
prose-free, and an agent-facing English sentence is held at the boundary.

These functions are byte-faithful lifts of the `_*_interpretation` helpers that
used to live in `dos_mcp.server`; the strings are unchanged so existing MCP
behavior is identical, only their home moved.
"""

from __future__ import annotations


def verify(verdict: dict) -> str:
    """One line on what a `verify` (ShipVerdict) result means for the next action.

    Reads the verdict's `to_dict()` fields (`shipped`, `source`, `sha`). The
    three branches mirror the three things a truth-syscall answer can be: a real
    artefact-backed ship (rely on it), an honest no-evidence-either-way (treat as
    not done, distrust the claim), and a checked-but-unshipped (not done yet).
    """
    shipped = verdict.get("shipped")
    source = verdict.get("source", "")
    if shipped:
        where = {"registry": "a run-registry row", "grep": "a git commit"}.get(
            source, "evidence")
        sha = verdict.get("sha")
        return (f"SHIPPED — confirmed by {where}"
                + (f" ({sha})" if sha else "")
                + ". You can rely on this; the evidence is real, not self-reported.")
    if source == "none":
        return ("NOT shipped — and there is NO positive evidence either way "
                "(no registry row, no matching commit). Treat it as not done. "
                "Do NOT accept a worker's claim that it shipped without evidence.")
    return ("NOT shipped on the evidence checked. Treat it as not done until a "
            "real commit or registry row appears.")


def arbitrate(decision: dict) -> str:
    """One line on what an `arbitrate` (LaneDecision) result means for the next action.

    Reads the decision's `to_dict()` fields (`outcome`, `lane`, `auto_picked`,
    `free_clusters`). A GO names the (possibly auto-picked) lane and why
    concurrency is safe; a STOP says don't start and lists any free lane to take
    instead.
    """
    if decision.get("outcome") == "acquire":
        lane = decision.get("lane", "")
        picked = " (auto-picked for you)" if decision.get("auto_picked") else ""
        return (f"GO — you may take lane {lane!r}{picked}. Its file tree is "
                f"disjoint from every live lease, so concurrent work is safe.")
    free = decision.get("free_clusters") or []
    tail = (f" Free lanes you could take instead: {', '.join(free)}."
            if free else " No free lane is available right now — wait or retry.")
    return ("STOP — do not start this work. Taking this lane would collide with a "
            "live lease (or it is exclusive/held)." + tail)


def gate(result: dict) -> str:
    """One line on what a `gate` (empty-packet) verdict means for the loop's next step.

    Reads the `dos gate` result fields (`verdict`, `reason`). The five verdicts
    map to the five things a /next-up packet can be — and, crucially, to whether
    the dispatch loop should CONTINUE, REPLAN/STOP, SELF-HEAL, or RETRY. This
    mirrors `gate_classify.gate_policy` (the pure policy matrix) in prose, so an
    agent gating its empty case reads the same routing the loop would take.
    """
    verdict = str(result.get("verdict", "")).upper()
    if verdict == "LIVE":
        return ("LIVE — the packet has dispatchable work; CONTINUE dispatch. This "
                "is the success case, not a stop.")
    if verdict == "DRAIN":
        return ("DRAIN — the backlog is genuinely empty. STOP (or /replan to "
                "refill); a second consecutive DRAIN is the real drained-twice "
                "stop. This is the only verdict that counts toward an early stop.")
    if verdict == "STALE-STAMP":
        return ("STALE-STAMP — work shipped in git but the plan rows weren't "
                "stamped, so it only LOOKS drained. Do NOT treat as done-and-empty: "
                "reconcile the stamps and re-dispatch. Never counts toward "
                "drained-twice.")
    if verdict == "BLOCKED":
        return ("BLOCKED — picks exist but a sibling claim / quota blocks them. Do "
                "NOT loop unattended; surface it for the operator (or /replan). "
                "Never counts toward drained-twice.")
    if verdict == "RACE":
        return ("RACE — you lost a candidates-cache lock; the on-disk packet is "
                "wrong-scope. Do NOT read it as a real DRAIN/BLOCKED — sleep "
                "briefly and retry once; the foreign holder will emit the intended "
                "packet. Never counts toward drained-twice.")
    return ("Unrecognised gate verdict — treat conservatively as NOT a clean LIVE; "
            "do not continue dispatch on it without checking the reason.")


def check_reason(out: dict) -> str:
    """One line on whether a reason token is safe to emit.

    Reads the `dos_check_reason` / `dos check-reason` result fields (`known`,
    `refusal`). A known reason is safe to emit (the oracle can verify the
    condition it names); an unknown one is `UNCLASSIFIED` prose-drift the kernel
    exists to kill, so it must not be emitted.
    """
    if out.get("known"):
        kind = "a refusal (route to replan)" if out.get("refusal") else "advisory-only"
        return (f"VALID reason — {kind}. Safe to emit; the oracle can verify the "
                f"condition it names.")
    return ("UNKNOWN reason — this token is NOT in the closed vocabulary, so it is "
            "UNCLASSIFIED drift. Do NOT emit it. Pick a real reason from "
            "`dos_refuse_reasons`, or have the workspace declare this one in "
            "dos.toml [reasons] first.")


def commit_audit(verdict: dict) -> str:
    """One line on what a `commit-audit` (ClaimVerdict) result means for the next action.

    Reads the verdict's `to_dict()` fields (`verdict`, `witness`, `reason`). The
    three branches mirror the three things a claim-vs-diff grade can be: a claim
    its own diff contradicts (fix it before reporting done), a claim the diff
    witnesses (rely on the rung, but note presence ≠ correctness), and no
    checkable claim (nothing to act on). Author-neutral — the same gloss whether a
    human or an agent wrote the commit.
    """
    v = str(verdict.get("verdict", "")).upper()
    if v == "CLAIM_UNWITNESSED":
        why = verdict.get("reason", "")
        return ("CLAIM UNWITNESSED — this commit's message claims something its own "
                "diff does not show" + (f" ({why})" if why else "") + ". Before you "
                "report this as done, either make the change the message claims or "
                "rewrite the message to match what the diff actually did. (This grades "
                "did-it-do-the-kind-of-thing-claimed, not whether the code is correct.)")
    if v == "OK":
        return ("WITNESSED — the diff does the KIND of thing the message claims "
                f"(rung: {verdict.get('witness', '')}). This is NOT a correctness "
                "check (a wrong-but-real change still passes); it only confirms the "
                "claim isn't empty. Run the tests for correctness.")
    return ("NO CHECKABLE CLAIM — the subject makes no concrete code/test claim to "
            "verify against the diff (e.g. wip/merge/chore). Nothing to act on here.")
