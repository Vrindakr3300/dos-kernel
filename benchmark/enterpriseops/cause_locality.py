"""cause_locality.py — the $0 ablation that subdivides natural thrash by WHERE the fix-info lives.

docs/172 §9 / docs/176 §4. The operator's instruction: keep sub-dividing and ablating "what is an
actual issue vs not." The §4 prune-vs-reorchestrate law says rewind (subtract + no-good) helps ONLY
when the dead end's corruption lives *strictly after* the last verified anchor, and LIVELOCKS when
the root cause sits *upstream* of the anchor (re-entering the clean prefix re-spawns the error). But
"upstream vs downstream" is only TWO buckets, and the natural corpus needs a THIRD: a dead end whose
fix-info is NOT IN THE TRANSCRIPT AT ALL (schema knowledge the model lacks, e.g. create_filter
`negatedQuery: required field cannot be an empty string`). That class is unreachable by ANY transcript
surgery — rewind, restart, or append — because the missing bytes live in the model's weights, not the
truncatable context. Conflating it with the upstream-omission class over-counts what rewind could ever
fix. This module measures the three-way split DIRECTLY on the natural-thrash corpus, at $0.

THE THREE CAUSE-LOCALITY CLASSES (per natural thrash, mutually exclusive):

  A. DOWNSTREAM / RECOVERABLE-FROM-PREFIX (rewind-ADDRESSABLE).
     The value the dead-end call got wrong DID appear, correctly, in a tool result the surviving
     prefix (turns <= the rewind anchor) retains. The agent HAD the right value and lost track of it
     in the accreted dead-end tail. Subtracting the tail + re-surfacing leaves the correct value in
     view → rewind CAN help. This is the only class the §4 law predicts a conversion on.

  B. UPSTREAM-OMISSION-IN-TRANSCRIPT (rewind-LIVELOCKS, §3.5).
     The fix-info is recoverable, but ONLY from a read the agent never issued / issued AFTER the
     anchor, OR the correct value appeared but is upstream of NO clean anchor. Re-entering the clean
     prefix hands back the same prefix that caused the omission → the agent re-omits and re-thrashes.
     The measured livelock. A *restart* that re-reasons the prefix MIGHT escape; rewind cannot.

  C. NOT-IN-TRANSCRIPT (rewind-UNREACHABLE — and so is every transcript move).
     The dead end is a schema/format/constraint the model violates (a required field it omits, a type
     it mis-supplies) where the correct value is NOT a datum from any tool result — it is API
     knowledge the model lacks. No anchor exists whose prefix contains it. The no-good note carries
     the env's complaint, but it is advisory (PDP not PEP), and the model that didn't know the schema
     the first time re-violates it. NEITHER rewind NOR restart can supply it; only a stronger model,
     a tool-schema injection, or a binding (PEP) constraint can. This is the SOTA-honest bucket: it is
     a MODEL-CAPABILITY gap, not a context-hygiene problem, so it is OUTSIDE what any rewind primitive
     can claim.

The classifier is a HEURISTIC over env-authored bytes only (it reads tool args + tool results, never
response.content). It is deliberately CONSERVATIVE toward C/B (it only calls a thrash class-A when it
can POINT to the correct value in the prefix), so the rewind-addressable count is a LOWER bound and
the not-an-issue-for-rewind count (B+C) is an upper bound — the safe direction for "do not over-claim
what rewind fixes." Pure replay of recorded JSON; no model, no network.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

_STRUCT = re.compile(
    r"MCP error -3\d{4}|\"isError\"\s*:\s*true|^\s*Error:|Traceback \(most recent"
    r"|exited with code [1-9]|permission denied", re.IGNORECASE | re.MULTILINE)

# A schema/format/constraint complaint = the env rejecting the SHAPE of the call (a required field
# missing, a type wrong, an empty string where one is required, a value out of an enum). The fix is
# API KNOWLEDGE, not a datum from a prior result → class C (not-in-transcript). Anchored to the gym's
# real validation grammar (measured: create_filter `... is required` / `required field cannot be an
# empty string` / `expected type ... got ...`; create_knowledge `String should have at most ...`).
_SCHEMA_COMPLAINT = re.compile(
    r"is required"
    r"|required field cannot be"
    r"|expected type"
    r"|String should have"
    r"|should have at most"
    r"|must be a valid"
    r"|must contain at least"
    r"|Invalid Tool Arguments"
    r"|string_too_long|string_too_short|value_error|type_error|missing",
    re.IGNORECASE)

# An id/reference complaint = the env rejecting a VALUE that names another row (a foreign key that
# doesn't resolve). The fix IS a datum that could live in a prior result → class A or B (depends on
# whether that datum is in the surviving prefix).
_REF_COMPLAINT = re.compile(
    r"not found|does not exist|no such|unknown id|invalid id|references|foreign key|"
    r"could not find|no .* with (id|name)",
    re.IGNORECASE)


def _rtext(tr) -> str:
    try:
        return json.dumps(tr.get("result", tr), default=str)
    except Exception:
        return str(tr)


def _is_struct_error(tr) -> bool:
    return bool(_STRUCT.search(_rtext(tr)))


def _is_blocked(tr) -> bool:
    if not isinstance(tr, dict):
        return False
    if tr.get("dos_blocked"):
        return True
    r = tr.get("result")
    return isinstance(r, dict) and bool(r.get("dos_blocked"))


def _is_ok(tr) -> bool:
    """A real, non-error result (a last-known-good turn / a prefix datum)."""
    return not _is_blocked(tr) and not _is_struct_error(tr)


def _error_text(tr) -> str:
    """The env's error message text node (for grammar classification).

    The gym has TWO error envelope shapes: (1) MCP validation results put the message in a
    `"text":` content node (create_filter `❌ Invalid Tool Arguments: [...]`); (2) REST-style
    errors put it in `"detail"."message"` / a top-level `"message"` (link_knowledge_to_incident
    `RESOURCE_NOT_FOUND: Incident 'INC-...' not found`). Read both so the ref-vs-schema grammar
    sees the real complaint, not the JSON scaffolding."""
    # The error text is often DOUBLE-encoded: a `"text"` content node whose value is itself a JSON
    # string (so `"message"` appears as `\"message\"`), or `\\n`-laden. Rather than extract one
    # clean field (fragile across the gym's two envelope shapes), fully UNESCAPE the blob and let
    # the ref/schema grammars match the real complaint anywhere in it. Strip the JSON scaffolding
    # quotes so a token like `not found` / `is required` is plain text.
    raw = _rtext(tr)
    flat = raw.replace('\\"', '"').replace("\\n", " ").replace('\\\\', "")
    # collapse the longest run that looks like the human message (after a 'message'/'text' key) for
    # the excerpt; but classification (below) runs the grammar over the WHOLE `flat`, not this.
    m = re.search(r'(?:"message"|"text"|"msg")\s*:\s*"?(.{0,200})', flat)
    excerpt = m.group(1) if m else flat[:200]
    # return the WHOLE flattened blob so _SCHEMA_COMPLAINT/_REF_COMPLAINT see every token; the
    # caller truncates the displayed excerpt separately.
    return flat


def _error_excerpt(tr) -> str:
    """A short, human-readable slice of the env error for display (not for classification)."""
    flat = _error_text(tr)
    m = re.search(r'(?:message|msg|error_code)["\s:]+([^"]{4,140})', flat)
    if m:
        return m.group(1).strip()
    m = re.search(r'(Invalid Tool Arguments[^\]]{0,140})', flat)
    return (m.group(1) if m else flat[:140]).strip()


def _ref_slots_from_error(err_text: str, call_args: dict) -> list:
    """Which arg slot(s) does a reference error implicate? Returns arg keys to check in the prefix.

    Strategy (conservative): (1) if the error names an entity ("Incident 'INC-...' not found"),
    map it to any arg key whose name contains that entity word (incident → incident_id); (2) else
    fall back to EVERY id-shaped arg key (`*_id`, `*Id`, `userId`, etc.) — checking all of them is
    safe because class A still requires a CONCRETE differing value in the prefix for at least one."""
    keys = list(call_args.keys())
    low = err_text.lower()
    named = []
    for k in keys:
        kl = k.lower()
        # the entity word inside the key (incident_id → 'incident') appears in the error?
        ent = kl.replace("_id", "").replace("id", "").strip("_")
        if ent and len(ent) >= 3 and ent in low:
            named.append(k)
    if named:
        return named
    # fall back to id-shaped keys
    return [k for k in keys if re.search(r"(_id$|^id$|Id$|_ids$)", k) or "id" == k.lower()]


def _classify_thrash(tool_results, tool_name) -> dict | None:
    """Classify one tool's natural thrash into cause-locality A/B/C. None if not a thrash."""
    own = [tr for tr in tool_results if str(tr.get("tool_name", "")) == tool_name
           and not _is_blocked(tr)]
    errs = [tr for tr in own if _is_struct_error(tr)]
    if len(errs) < 2 or not _is_struct_error(own[-1]):
        return None

    # the anchor = last OK turn (any tool) strictly before the FIRST error of this tool.
    first_err_pos = None
    for i, tr in enumerate(tool_results):
        if str(tr.get("tool_name", "")) == tool_name and _is_struct_error(tr) and not _is_blocked(tr):
            first_err_pos = i
            break
    prefix = tool_results[:first_err_pos] if first_err_pos is not None else []
    anchor_ok = [tr for tr in prefix if _is_ok(tr)]

    err_text = _error_text(own[-1])
    is_schema = bool(_SCHEMA_COMPLAINT.search(err_text))
    is_ref = bool(_REF_COMPLAINT.search(err_text))

    # CLASS C — a pure schema/format/constraint complaint with NO id-reference component. The fix is
    # API knowledge, not a prior-result datum. Unreachable by any transcript move.
    if is_schema and not is_ref:
        cls = "C_not_in_transcript"
        why = "schema/format/constraint complaint — fix is API knowledge, not a transcript datum"
    elif is_ref:
        # An id/reference complaint ("X not found"): the fix is a DATUM (the correct id). Class A
        # (rewind-addressable) requires that the CORRECT value is available in the surviving prefix
        # and the agent simply used a wrong one — i.e. an OK prefix result READ the same entity type
        # and returned a concrete id that the agent FAILED to use. Class B (upstream omission /
        # livelock) is when the agent never read the entity at all and is GUESSING (the measured
        # link_knowledge case: INC-000001/044/069 fabricated, no find_incident ever ran).
        #
        # TIGHT test (conservative toward B — the safe direction for "do not over-claim what rewind
        # fixes"): the same reference SLOT (the arg key that the error names, e.g. incident_id) must
        # have a CONCRETE candidate value in an OK prefix result that DIFFERS from the agent's bad
        # value. A mere shared digit-substring is NOT enough (it credits a coincidental number match
        # — the false-A bug). We require: (1) an OK prefix result exists that is a READ of the entity
        # (its bytes carry the slot's key with a concrete value), and (2) that value != the bad value.
        bad_call_args = errs[-1].get("arguments", {}) or {}
        slot_keys = _ref_slots_from_error(err_text, bad_call_args)
        prefix_blob = " ".join(_rtext(tr) for tr in anchor_ok)
        recoverable_slot = None
        for slot in slot_keys:
            bad_val = str(bad_call_args.get(slot, ""))
            # concrete candidate values the prefix RETURNED for this slot (key:"value" in OK results)
            cands = set(re.findall(rf'"{re.escape(slot)}"\s*:\s*"?([A-Za-z0-9_\-]{{2,}})', prefix_blob))
            cands |= set(re.findall(rf'\\"{re.escape(slot)}\\"\s*:\s*\\?"?([A-Za-z0-9_\-]{{2,}})', prefix_blob))
            good = {c for c in cands if c and c != bad_val}
            if good:
                recoverable_slot = (slot, sorted(good)[:2])
                break
        if recoverable_slot:
            cls = "A_recoverable_from_prefix"
            why = (f"id complaint on `{recoverable_slot[0]}`, and the prefix RETURNED a different "
                   f"concrete value ({recoverable_slot[1]}) the agent failed to use — recoverable")
        else:
            cls = "B_upstream_omission"
            why = ("id complaint, but NO concrete value for the referenced slot is in the surviving "
                   "prefix — the entity was never read (the agent is guessing); rewind livelocks")
    else:
        # neither clearly schema nor ref — fall to B (conservative: assume not prefix-recoverable).
        cls = "B_upstream_omission"
        why = "unrecognized complaint shape — conservatively not prefix-recoverable"

    return {
        "tool": tool_name,
        "n_errors": len(errs),
        "anchor_ok_turns": len(anchor_ok),
        "class": cls,
        "why": why,
        "err_excerpt": _error_excerpt(own[-1]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dirs", nargs="+",
                    default=[os.path.join(_HERE, "live_results_natural_run", "none"),
                             os.path.join(_HERE, "live_results_natural", "none")])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cases = []
    n_runs = 0
    for d in args.dirs:
        for f in sorted(glob.glob(os.path.join(d, "*.json"))):
            try:
                data = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            for run in data.get("runs", []):
                n_runs += 1
                trs = run.get("tool_results") or []
                # find the (first) thrashing tool in this run
                fc = Counter(str(tr.get("tool_name", "")) for tr in trs if _is_struct_error(tr))
                for tool, c in fc.items():
                    if c < 2:
                        continue
                    r = _classify_thrash(trs, tool)
                    if r is not None:
                        r["file"] = os.path.basename(f)
                        r["success"] = bool(run.get("overall_success"))
                        cases.append(r)
                        break  # one thrash per run (the live arm's first-fire)

    by_class = Counter(c["class"] for c in cases)
    by_tool = defaultdict(Counter)
    for c in cases:
        by_tool[c["class"]][c["tool"]] += 1

    addressable = by_class.get("A_recoverable_from_prefix", 0)
    livelock = by_class.get("B_upstream_omission", 0)
    unreachable = by_class.get("C_not_in_transcript", 0)
    total = len(cases)

    summary = {
        "as_of": "2026-06-06",
        "n_runs": n_runs,
        "natural_thrash_cases": total,
        "A_recoverable_from_prefix (rewind-ADDRESSABLE)": addressable,
        "B_upstream_omission (rewind-LIVELOCKS)": livelock,
        "C_not_in_transcript (rewind-UNREACHABLE, model-capability gap)": unreachable,
        "rewind_addressable_pct_of_thrash": round(100.0 * addressable / total, 1) if total else 0.0,
        "not_a_rewind_issue_pct (B+C)": round(100.0 * (livelock + unreachable) / total, 1) if total else 0.0,
    }

    if args.json:
        print(json.dumps({"summary": summary, "cases": cases}, indent=2))
        return

    print("=== CAUSE-LOCALITY ABLATION of natural thrash (what is an actual rewind issue?) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\n  by class × tool:")
    for cls in ("A_recoverable_from_prefix", "B_upstream_omission", "C_not_in_transcript"):
        if by_tool.get(cls):
            print(f"    {cls}: {dict(by_tool[cls])}")
    print("\n=== per-case ===")
    for c in cases:
        print(f"  [{c['class']:<26}] {c['tool']:<22} errs={c['n_errors']} "
              f"anchor_ok={c['anchor_ok_turns']} success={c['success']}")
        print(f"      why: {c['why']}")
        print(f"      err: {c['err_excerpt']}")
    print("\n  THE ABLATION VERDICT: only class A is an 'actual issue' rewind can convert; B livelocks")
    print("  (rewind), C is a MODEL-CAPABILITY gap outside any transcript move. B+C is the honest")
    print("  ceiling on what rewind CANNOT fix. Conservative: A is a lower bound, B+C an upper bound.")


if __name__ == "__main__":
    main()
