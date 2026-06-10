"""schema_refresh — the byte-clean CONVERSION mechanism for CURABLE thrashes (docs/198 §7).

THE QUESTION (operator, 2026-06-06): once the feasibility witness says a thrash is CURABLE (a path
exists), how can DOS help provide the critical schema data — e.g. a structured nudge that gets the
model to refresh the schema itself — WITHOUT DOS authoring the fix?

THE ANSWER, and why it is byte-clean. On a CURABLE thrash the authoritative correction is ALREADY in
the environment's own error reply. Measured on this gym (docs/198 §7), the curable-tool errors are
richly diagnostic and ENV-AUTHORED:

    update_vacation_settings -> "Invalid Tool Arguments: ['responseBodyHtml: is required',
                                  'restrictToContacts: is required', 'restrictToDomain: is required']"
    update_vacation_settings -> "start_time must be a valid epoch millisecond timestamp"
    update_vacation_settings -> "HTML content must contain at least one HTML tag"

The agent already DIAGNOSES the fix from these (docs/198 §0) and still fails — it does not ACT on the
env's own correction. So DOS's job is NOT to supply the schema (that would be author-and-believe, the
docs/164 violation). DOS's job is to make the env's own corrective UN-IGNORABLE: re-surface the
env-authored validation message as a STRUCTURED forcing function the model must satisfy before it may
retry. DOS authors only the FRAMING; every corrective byte is the environment's.

This module is the PURE extractor + the $0 upper-bound replay:

  * `extract_corrective(error_text)` — parse the env's structured error into a typed `SchemaCorrective`
    (missing-required fields, type/format constraints, the raw env message). Reads ENV bytes only.
  * `refresh_directive(corrective)` — render the byte-clean re-prompt: the env's own requirements as a
    checklist + (in the GENERAL case) a "re-fetch the tool schema via tools/list and satisfy every
    field before retrying" instruction. DOS authors the structure; the constraints are the env's.
  * `corrective_presence(corpus)` — the $0 UPPER BOUND on conversion: of the curable thrashes, what
    fraction carry an env corrective specific enough to act on (missing-field list or a typed
    constraint)? A re-surface can only convert where the env already said HOW. This bounds the live
    conversion A/B from above before any spend.

THE GENERALIZATION (when the env has a schema-introspection tool). This gym exposes NO get_schema /
tools/list tool, so the only env-authored schema source here is the error reply. Where an MCP server
DOES expose `tools/list` (JSON Schema per tool), the cleanest form is to route the agent to RE-FETCH
that schema before retry — 100% env-authored, zero DOS authorship. `refresh_directive` emits that
instruction too, so the mechanism degrades gracefully: re-fetch if introspection exists, else
re-surface the error's own corrective. Either way DOS never writes the schema.

    python schema_refresh.py                  # the $0 corrective-presence upper bound on the curable slice
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_BENCH = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _BENCH)

from _feasibility import ToolEvent, Verdict, feasibility_witness, thrash_tools  # noqa: E402
from dos_react import (  # noqa: E402
    _is_struct_error, _result_text, _is_blocked_result, _redact_reflected_input,
)


# ---------------------------------------------------------------------------
# The typed corrective extracted from the ENV's own error bytes.
# ---------------------------------------------------------------------------
# The corrective KIND — not every curable thrash is a SCHEMA thrash. The honest discipline
# (docs/198 §0 applied recursively): a schema-refresh converts SCHEMA-shaped failures (missing
# field, wrong type/format) — but a curable thrash can also be a WRONG-REFERENCE (NOT_FOUND: the
# schema is fine, the referenced entity does not exist → needs a LOOKUP, not a schema) or a
# STATE-CONFLICT (already-exists/idempotency → needs a re-plan, not a schema). Classifying the kind
# keeps the mechanism honest about which thrashes it can convert.
KIND_SCHEMA = "SCHEMA"        # missing required field / wrong type / format constraint → schema-refresh
KIND_REFERENCE = "REFERENCE"  # NOT_FOUND / wrong id → re-fetch the entity (a lookup), NOT the schema
KIND_STATE = "STATE"          # already-exists / idempotency / conflict → re-plan, NOT the schema
KIND_OPAQUE = "OPAQUE"        # an error with no actionable detail → fall back to early-halt


@dataclass(frozen=True)
class SchemaCorrective:
    """What the environment's error reply tells the model to fix. Every field is ENV-authored —
    parsed out of the validation message, never invented by DOS.

      kind             — one of KIND_SCHEMA / REFERENCE / STATE / OPAQUE (which lever applies).
      missing_required — field names the env said are required (e.g. 'responseBodyHtml').
      constraints      — typed/format constraints the env stated (e.g. 'start_time must be a valid
                         epoch millisecond timestamp', "message: expected type 'object', got 'string'").
      raw              — the env's original (redacted) error text, carried verbatim as the provenance.
      actionable       — True iff there is a corrective specific enough to act on.
      schema_convertible — True iff a SCHEMA-REFRESH (re-surface the field/type corrective) applies;
                         False for REFERENCE/STATE/OPAQUE (a different lever or early-halt).
    """

    kind: str = KIND_OPAQUE
    missing_required: tuple = ()
    constraints: tuple = ()
    raw: str = ""

    @property
    def actionable(self) -> bool:
        return bool(self.missing_required) or bool(self.constraints) or self.kind in (
            KIND_REFERENCE, KIND_STATE)

    @property
    def schema_convertible(self) -> bool:
        return self.kind == KIND_SCHEMA and (bool(self.missing_required) or bool(self.constraints))


# the env's structured "is required" list: ['field.path: is required', ...]
_REQUIRED_RE = re.compile(r"['\"]([\w.\[\]]+):\s*is required['\"]")
# a stated constraint sentence: "<thing> must <...>" or "<thing> must be <...>"
_CONSTRAINT_RE = re.compile(r"([A-Za-z_][\w .]*?\s+must\s+[^'\"\]]+?)(?=['\"\]]|$)")
# a type mismatch: "message: expected type 'object', got 'string'"
_TYPE_RE = re.compile(r"([\w.]+:\s*expected type\s*'[^']+',\s*got\s*'[^']+')")
# a JSON-detail value error (Pydantic-style): "msg": "Invalid phone format provided: ..."
_MSG_RE = re.compile(r'"msg"\s*:\s*"([^"]+)"')
# reference-not-found / state-conflict markers (env-authored)
_NOT_FOUND_RE = re.compile(r"not found|NOT_FOUND|does not exist|no such|RESOURCE_NOT_FOUND", re.I)
_STATE_RE = re.compile(r"already (has|exists|been)|duplicate|conflict|ALREADY_EXISTS", re.I)


def _unwrap(error_text: str) -> str:
    """Dig the human-readable message out of the gym's {"result":{"content":[{"text":...}]}} wrapper.
    Returns the innermost text node (which may itself be a JSON string for the Pydantic-detail shape)."""
    text = error_text
    try:
        obj = json.loads(error_text)
        node = obj.get("result", obj) if isinstance(obj, dict) else obj
        if isinstance(node, dict):
            content = node.get("content")
            if isinstance(content, list) and content and isinstance(content[0], dict):
                text = content[0].get("text", error_text)
    except (json.JSONDecodeError, TypeError):
        pass
    return text or ""


def extract_corrective(error_text: str) -> SchemaCorrective:
    """Parse the ENV's structured error into a typed corrective AND classify its kind. Pure; reads
    only the env-authored bytes. Handles the gym's emoji/`is required`/type-mismatch/Pydantic-detail
    grammars + the reference/state failure classes a schema-refresh does NOT cover."""
    if not error_text:
        return SchemaCorrective(raw="")
    text = _unwrap(error_text)

    missing = tuple(dict.fromkeys(_REQUIRED_RE.findall(text)))
    constraints = list(c.strip() for c in _CONSTRAINT_RE.findall(text) if "is required" not in c)
    constraints += [t.strip() for t in _TYPE_RE.findall(text)]
    # a Pydantic value-error msg is a schema-ish corrective ONLY if it is not a not-found/state msg
    for m in _MSG_RE.findall(text):
        if not _NOT_FOUND_RE.search(m) and not _STATE_RE.search(m):
            constraints.append(m.strip())
    constraints = tuple(dict.fromkeys(constraints))

    # classify the KIND: reference/state win over schema (they are NOT schema-convertible even if a
    # stray field name appears), then schema if we found a field/type corrective, else opaque.
    if _NOT_FOUND_RE.search(text):
        kind = KIND_REFERENCE
    elif _STATE_RE.search(text):
        kind = KIND_STATE
    elif missing or constraints:
        kind = KIND_SCHEMA
    else:
        kind = KIND_OPAQUE
    # Redact the agent's reflected `input` echo from the raw BEFORE storing it, so the REFERENCE/STATE
    # branches (which embed corrective.raw verbatim) carry only the ENV's own validation message — the
    # surviving bytes are honestly THIRD_PARTY, the same boundary-side redaction natural_thrash_gate /
    # terminal_error_gate apply. (The SCHEMA branch surfaces missing_required/constraints, which are
    # already env-structural field names, so this only hardens the reference/state path.)
    return SchemaCorrective(kind=kind, missing_required=missing,
                            constraints=constraints, raw=_redact_reflected_input(text)[:300])


def refresh_directive(corrective: SchemaCorrective, tool_name: str,
                      *, has_introspection: bool = False) -> str:
    """Render the byte-clean re-prompt, KIND-DISPATCHED. DOS authors only the STRUCTURE; every
    corrective byte is the env's. The kind decides the LEVER (docs/200 §2 — not every curable thrash
    is a SCHEMA thrash, so a single frame would mis-prescribe):

      * SCHEMA      — re-surface the env's missing-field / type / format corrective as a forcing
                      checklist (the agent must satisfy every requirement before retry). With
                      has_introspection, also route a tools/list re-fetch (0 DOS authorship).
      * REFERENCE   — the env said NOT_FOUND: the referenced entity does not exist as called. Route a
                      LOOKUP (read/list/query) to resolve the correct id, then retry — never re-send
                      the same id. The env's verbatim NOT_FOUND text rides through (redacted raw).
      * STATE       — the env said already-exists / conflict: the op may already hold; re-read state
                      and RE-PLAN, never retry the identical call. The env's verbatim conflict text
                      rides through (redacted raw).
      * OPAQUE      — no actionable detail and no introspection -> "" (the caller falls back to the
                      docs/198 §2 early-halt; there is nothing env-authored to surface).

    Every form carries ONLY env bytes (missing_required / constraints / the redacted raw) inside a DOS
    frame — never a candidate value, a resolved id, or a corrected plan (that would be the docs/164
    author-and-believe violation). Returns "" only for OPAQUE-without-introspection."""
    if corrective.kind == KIND_REFERENCE:
        # The env reported the referenced entity does not exist. DOS routes a lookup; it never names
        # the correct id (it does not know it) — the agent must resolve it from the env.
        return "\n".join([
            f"The previous call to `{tool_name}` was REJECTED by the environment:",
            f"  {corrective.raw}",
            f"The referenced entity does not exist as called. Before retrying `{tool_name}`, issue a "
            f"READ / LIST / QUERY tool to resolve the correct identifier from the environment, then "
            f"retry with the resolved value. Do NOT re-send the same identifier. This is the "
            f"environment's verbatim reply, not advice.",
        ])
    if corrective.kind == KIND_STATE:
        # The env reported a state conflict (already-exists/idempotency). DOS routes a re-plan; it
        # never authors the revised plan — only surfaces that the prior step may already hold.
        return "\n".join([
            f"The previous call to `{tool_name}` was REJECTED by the environment:",
            f"  {corrective.raw}",
            f"The requested change already holds or conflicts with current state — the prior step may "
            f"already have succeeded. Before retrying, RE-READ the current state and revise your plan; "
            f"do NOT retry the identical call. This is the environment's verbatim reply, not advice.",
        ])
    # SCHEMA (and OPAQUE-with-introspection): the missing-field / type / format checklist.
    if not corrective.actionable and not has_introspection:
        return ""
    lines = [f"The previous call to `{tool_name}` was REJECTED by the environment. "
             f"Before retrying, satisfy the environment's own requirements (do NOT guess):"]
    if has_introspection:
        lines.append(f"  1. Call the schema-introspection tool to RE-FETCH the authoritative "
                     f"schema for `{tool_name}` (tools/list), then fill EVERY required field.")
    if corrective.missing_required:
        lines.append("  Required fields the environment reported missing (fill ALL of them):")
        for fld in corrective.missing_required:
            lines.append(f"    - {fld}")
    if corrective.constraints:
        lines.append("  Constraints the environment stated (each must hold):")
        for c in corrective.constraints:
            lines.append(f"    - {c}")
    lines.append("Only retry once every requirement above is met. These requirements are the "
                 "environment's verbatim reply, not advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The $0 upper bound: how often does the env corrective EXIST and is it actionable?
# ---------------------------------------------------------------------------
def _events(run):
    out = []
    for tr in (run.get("tool_results") or []):
        if _is_blocked_result(tr):
            continue
        t = str(tr.get("tool_name", ""))
        if not t:
            continue
        out.append(ToolEvent(t, _is_struct_error(_result_text(tr))))
    return out


def _runs(arm_glob):
    for f in sorted(glob.glob(arm_glob)):
        try:
            r = (json.load(open(f, encoding="utf-8")).get("runs") or [{}])[0]
        except Exception:
            continue
        yield f, r


def corrective_presence(out_dir: str, min_obs: int = 3) -> dict:
    """Of the CURABLE thrashes in the corpus, how many carry an ACTIONABLE env corrective? This is
    the UPPER BOUND on what a re-surface mechanism could convert: it can only help where the env
    already said HOW to fix it. Reports per-curable-tool so the operator sees which tools are
    convertible-in-principle (actionable corrective present) vs opaque (error with no detail)."""
    all_corpus = [_events(r) for _f, r in _runs(os.path.join(out_dir, "*", "results_*.json"))]
    witness = feasibility_witness(all_corpus, min_obs=min_obs)

    per_tool = {}   # tool -> {runs, schema, reference, state, opaque, examples}
    for _f, r in _runs(os.path.join(out_dir, "*", "results_*.json")):
        tt = thrash_tools(_events(r))
        for tn in tt:
            if witness.get(tn) is Verdict.WALLED or witness.get(tn) is None:
                continue
            # the latest error of this tool in the run = what the re-surface would carry
            own_errs = [tr for tr in (r.get("tool_results") or [])
                        if str(tr.get("tool_name", "")) == tn and not _is_blocked_result(tr)
                        and _is_struct_error(_result_text(tr))]
            if not own_errs:
                continue
            corr = extract_corrective(_result_text(own_errs[-1]))
            d = per_tool.setdefault(tn, {"runs": 0, "schema": 0, "reference": 0,
                                         "state": 0, "opaque": 0, "examples": []})
            d["runs"] += 1
            d[{KIND_SCHEMA: "schema", KIND_REFERENCE: "reference",
               KIND_STATE: "state", KIND_OPAQUE: "opaque"}[corr.kind]] += 1
            if corr.schema_convertible and len(d["examples"]) < 2:
                d["examples"].append({
                    "missing": list(corr.missing_required),
                    "constraints": list(corr.constraints)[:2],
                })
    total_runs = sum(d["runs"] for d in per_tool.values())
    total_schema = sum(d["schema"] for d in per_tool.values())
    total_ref = sum(d["reference"] for d in per_tool.values())
    total_state = sum(d["state"] for d in per_tool.values())
    total_opaque = sum(d["opaque"] for d in per_tool.values())
    return {
        "per_tool": per_tool,
        "total_curable_thrash_runs": total_runs,
        "schema_convertible": total_schema,
        "reference": total_ref,
        "state": total_state,
        "opaque": total_opaque,
        "schema_convertible_rate": round(total_schema / total_runs, 3) if total_runs else 0.0,
    }


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(_HERE, "live_results_natural_ab"))
    ap.add_argument("--min-obs", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    pres = corrective_presence(args.out, args.min_obs)
    if args.json:
        print(json.dumps(pres, indent=2, default=str))
        return 0

    print("=" * 88)
    print("  SCHEMA-REFRESH — the byte-clean conversion mechanism for CURABLE thrashes (docs/198 §7)")
    print(f"  corpus: {args.out}")
    print("  Q: of the curable thrashes, which carry an env corrective a SCHEMA-REFRESH can act on")
    print("     (missing-field / type / format) vs a DIFFERENT class (reference / state / opaque)?")
    print("=" * 88)
    print(f"  {'curable tool':<28}{'runs':>6}{'SCHEMA':>8}{'ref':>6}{'state':>7}{'opaque':>8}")
    print("-" * 88)
    for tn, d in sorted(pres["per_tool"].items(), key=lambda kv: -kv[1]["runs"]):
        print(f"  {tn:<28}{d['runs']:>6}{d['schema']:>8}{d['reference']:>6}{d['state']:>7}{d['opaque']:>8}")
        for ex in d["examples"]:
            bits = []
            if ex["missing"]:
                bits.append(f"missing={ex['missing']}")
            if ex["constraints"]:
                bits.append(f"constraints={ex['constraints']}")
            if bits:
                print(f"      schema e.g. {'  '.join(bits)}")
    print("-" * 88)
    n = pres["total_curable_thrash_runs"]
    print(f"  TOTAL curable-thrash runs: {n}")
    print(f"    SCHEMA-convertible (re-surface field/type corrective): {pres['schema_convertible']} "
          f"({pres['schema_convertible_rate']:.0%})  <- the schema-refresh ceiling")
    print(f"    REFERENCE (NOT_FOUND -> needs a LOOKUP, not a schema):  {pres['reference']}")
    print(f"    STATE (already-exists/conflict -> needs a RE-PLAN):     {pres['state']}")
    print(f"    OPAQUE (no actionable detail -> early-halt):            {pres['opaque']}")
    print()
    print("  READ: the SCHEMA cells are where the env ALREADY said which field/type to fix and the")
    print("  agent did not act — a re-surface (DOS authors the FRAMING, the env authors the")
    print("  CORRECTIVE) is the byte-clean conversion lever. REFERENCE/STATE are curable but need a")
    print("  DIFFERENT lever (lookup / re-plan) — folding them into 'schema' would re-commit the")
    print("  docs/198 §0 category error one level down. OPAQUE -> early-halt. This is the $0 CEILING;")
    print("  the live A/B (curable_oversample recipe) measures how much of it a re-surface realizes.")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
