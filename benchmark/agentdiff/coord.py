"""F3 — the coordination A/B on Agent-Diff: the SECOND state-witness environment (docs/245).

WHY THIS MODULE EXISTS (objection O3: "both results live on tau2 — one benchmark, one
domain"). The fleet program measured coordination payoff on tau2 (docs/233 + F2: natural
collisions, J off the env DB-hash). The witness discipline is supposed to be
environment-agnostic — it needs only a state verdict the agent can't author. This module is
the proof: the SAME kernel arbiter call (`dos.arbiter.arbitrate`, byte-identical), the same
believe-vs-adjudicate fold, re-aimed at Agent-Diff, where the witness is the PRODUCTION
`AssertionEngine` (the env's own gold-spec verdict) instead of tau2's DB-hash. One port turns
"single-benchmark" into "two independent witnesses agree."

THE SHAPE (mirrors `agentprocessbench/writeadmit/coord_loop.py` + `natural_collisions.py`):

  1. NATURAL CONTENTION ($0)  — do independent Agent-Diff tasks naturally assert on the SAME
     entity row? The contention key is env-authored (the gold spec's `entity` + a fully
     row-pinning `where`); the agent authors none of it. Tasks within a service share one
     seed workspace (`info.seed_template`), so two tasks naming one row really do contend
     when run concurrently against a shared backend.
  2. THE COMPOSE ($0)         — the canonical lost update under full-object write-back (the
     PUT semantics the wrapped services — Slack/Linear/Box/calendar — actually have): agent B,
     having read the row BEFORE agent A's write landed, writes the whole row back and silently
     reverts A's field. NAIVE = B's write-back computed against the ORIGINAL row (stale).
     SERIAL = B re-derived against the post-A row (what the arbiter's refusal forces).
  3. THE WITNESS              — the production `AssertionEngine.evaluate(net_diff)` over each
     task's OWN gold assertions on the shared row (selected verbatim, never edited). The
     verdict bytes are the engine's; the assertion bytes are the task author's; this module
     authors only the synthetic row states the engine compares — the same actor/witness split
     as `frozen_witness.py`.
  4. THE ARBITER              — `dos.arbiter.arbitrate` over the region `<service>/<entity>/
     <row>`: the second concurrent lease on the SAME row is REFUSED (serialized); a lease on a
     DIFFERENT row is ADMITTED (the refuse-MORE-only floor — coordination must not tax
     disjoint work).

PAYOFF J (the docs/179 FLIP, per naturally-contending pair): J += 1 iff the naive compose
LOST an update (≥1 task's asserted change refuted by the engine) AND the serialized compose
landed BOTH (engine confirms both) AND the arbiter refused the second concurrent lease. The
classification is driven entirely by the ENGINE's verdicts:

  LOST_UPDATE_PREVENTED — naive refutes ≥1, serial confirms both  → J=1 (the payoff row)
  CONVERGENT_BENIGN     — naive already confirms both (e.g. two tasks archiving the same
                          channel: same field, same value)        → J=0, correctly benign
  TRUE_CONFLICT         — even serial cannot confirm both (same field, different values;
                          delete-vs-update) → J=0; the arbiter still serializes (no SILENT
                          loss — the second writer sees the first's state), but ordering
                          alone cannot make both specs land; reported, never counted.

$0, no model, no network, no Docker: the dataset is the local JSONL clone; the engine is the
near-stdlib production leaf `frozen_witness` already imports. Everything here is deterministic.
"""
from __future__ import annotations

import itertools
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from .dataset import BenchTask, load_tasks


# --- the arbiter region mapper (byte-same kernel call as tau2's coord_loop) -------------

def row_region(service: str, entity: str, row_key: str) -> list[str]:
    """An entity ROW as a path-like arbiter region. Two agents on the same row produce
    overlapping trees -> `dos.arbiter` refuses the second (serializes). The Agent-Diff
    analogue of tau2's `reservations/<id>` — the mapper is still one line."""
    return [f"{service}/{entity}/{row_key}"]


def arbiter_admits(region: list[str], live_leases: list[dict]) -> bool:
    """Would dos.arbiter ADMIT a lease on `region` given the live leases? Pure, no I/O.

    The SAME call `agentprocessbench/writeadmit/coord_loop.arbiter_admits` makes — the kernel
    surface under both benchmarks is one function, `arbitrate(request, live_leases)`; only the
    region STRING (a tau2 reservation vs an Agent-Diff row) differs. That identity is F3's
    point: nothing in the kernel is re-fit per environment.
    """
    from dos import arbiter
    dec = arbiter.arbitrate(
        requested_lane=region[0],
        requested_kind="keyword",
        requested_tree=region,
        live_leases=live_leases,
    )
    outcome = getattr(dec, "outcome", None)
    outcome = outcome.value if hasattr(outcome, "value") else str(outcome)
    return outcome in ("acquire", "ACQUIRE")


# --- natural contention ($0; the F2-STEP-1 probe, re-aimed at Agent-Diff) ----------------

def _pinned_where_key(where: dict[str, Any]) -> Optional[str]:
    """Canonical row key for a FULLY ROW-PINNING `where` — else None.

    Row-pinning = every predicate is a bare scalar or `{"eq": scalar}` (a fully-determined
    row selector, e.g. `{"channel_id": "C05ALPHA"}` / `{"identifier": {"eq": "ENG-1"}}`).
    A predicate region (`{"is_dm": {"eq": true}}`, regex/contains, or an empty `{}`) names a
    SET of rows, not a row — two tasks sharing one are not necessarily writing the same row,
    so they are excluded (the conservative direction: the natural rate reported is a floor).
    """
    if not where:
        return None
    parts: list[tuple[str, Any]] = []
    for k, pred in sorted(where.items()):
        if isinstance(pred, dict):
            if set(pred.keys()) == {"eq"} and not isinstance(pred["eq"], (dict, list)):
                parts.append((k, pred["eq"]))
            else:
                return None
        elif isinstance(pred, (str, int, float, bool)):
            parts.append((k, pred))
        else:
            return None
    return json.dumps(parts, sort_keys=True)


def changed_row_keys(task: BenchTask) -> dict[tuple[str, str, str], dict[str, Any]]:
    """The row-pinned CHANGED assertions of a task: (service, entity, row_key) -> assertion.

    Only `diff_type == "changed"` assertions contend as LOST UPDATES (an added/removed row is
    not an existing row two writers can write back); only row-pinned wheres qualify (see
    `_pinned_where_key`). The assertion dict is the gold spec's verbatim object.
    """
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for a in task.gold_spec.get("assertions", []) or []:
        if a.get("diff_type") != "changed":
            continue
        ent = a.get("entity")
        key = _pinned_where_key(a.get("where", {}) or {})
        if ent and key is not None:
            out[(task.service, ent, key)] = a
    return out


@dataclass(frozen=True)
class ContentionReport:
    n_write_tasks: int
    n_tasks_with_pinned_changed: int
    n_pairs: int                      # pairs of tasks that each pin >=1 changed row
    n_colliding_pairs: int            # pairs sharing >=1 pinned changed row
    natural_pairwise_rate: float
    sites: dict                       # "<service>/<entity>/<row>" -> sorted task ids
    verdict: str                      # GO | KILL
    note: str = ""


def natural_contention(split: str = "test") -> ContentionReport:
    """Measure the NATURAL row-level contention rate in the Agent-Diff task distribution.

    The same $0 question `natural_collisions.measure` answered for tau2: do independent
    tasks, as AUTHORED, target the same entity row? If yes, the contention sites are real
    conflict pairs that fall out of the distribution (not pinned by us)."""
    tasks = [t for t in load_tasks(split) if t.is_write_task]
    keyed = {t.test_id: changed_row_keys(t) for t in tasks}
    naming = {tid: set(keys) for tid, keys in keyed.items() if keys}

    pairs = list(itertools.combinations(sorted(naming.items()), 2))
    colliding = [(a, b) for (a, ka), (b, kb) in pairs if ka & kb]
    rate = (len(colliding) / len(pairs)) if pairs else 0.0

    by_row: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for tid, keys in naming.items():
        for k in keys:
            by_row[k].add(tid)
    sites = {f"{s}/{e}/{w}": sorted(ts) for (s, e, w), ts in by_row.items() if len(ts) >= 2}

    verdict = "GO" if sites else "KILL"
    note = ("natural row-level contention exists — the coordination A/B draws its pairs "
            "from the task distribution, not a pin." if sites else
            "no two tasks pin the same changed row — a natural coordination A/B is not "
            "available on this split; only constructed pairs would remain.")
    return ContentionReport(
        n_write_tasks=len(tasks), n_tasks_with_pinned_changed=len(naming),
        n_pairs=len(pairs), n_colliding_pairs=len(colliding),
        natural_pairwise_rate=round(rate, 4), sites=sites, verdict=verdict, note=note)


# --- the compose: full-object write-back (the lost-update mechanism) ---------------------

_SENTINEL_ABSENT = object()


def _new_value(change: Any) -> Any:
    """The post-write value a task's `expected_changes` entry implies for a field.

    `{"to": {"eq": v}}` / `{"to": v}` -> v;  `{"to": {"exists": false}}` -> ABSENT (the field
    is removed);  a bare scalar -> itself. Predicates that don't determine one concrete value
    (regex/contains/gt...) return ABSENT-as-None marker `_SENTINEL_ABSENT` is NOT used — they
    return the string '__satisfies_predicate__' so the compose still has a value to carry;
    the engine then judges whatever the gold predicate says (such pairs classify as
    TRUE_CONFLICT or refute honestly rather than being silently dropped)."""
    to = change.get("to") if isinstance(change, dict) else change
    if isinstance(to, dict):
        if "eq" in to and not isinstance(to["eq"], (dict, list)):
            return to["eq"]
        if to.get("exists") is False:
            return _SENTINEL_ABSENT
        return "__satisfies_predicate__"
    return to


def _old_value(fld: str, change: Any, new: Any) -> Any:
    """The pre-write value for a field: the gold `from` if declared, else a type-consistent
    placeholder GUARANTEED to differ from `new` (so the engine sees a real change)."""
    if isinstance(change, dict):
        frm = change.get("from", None)
        if frm is not None and not isinstance(frm, (dict, list)):
            return frm
    if new is _SENTINEL_ABSENT:
        return f"__orig_{fld}__"      # the field WAS set; the write removes it
    if isinstance(new, bool):
        return not new
    if isinstance(new, (int, float)):
        return new + 1
    return f"__orig_{fld}__"


def change_set(assertion: dict[str, Any]) -> dict[str, Any]:
    """A changed-assertion's write as {field: new_value} (values per `_new_value`)."""
    return {f: _new_value(c) for f, c in (assertion.get("expected_changes", {}) or {}).items()}


def original_row(where: dict[str, Any], *assertions: dict[str, Any]) -> dict[str, Any]:
    """Synthesize the shared row's ORIGINAL state: the where-identity fields plus every
    asserted field at its pre-write value (gold `from` when declared, placeholder else)."""
    row: dict[str, Any] = {}
    for k, pred in (where or {}).items():
        row[k] = pred["eq"] if isinstance(pred, dict) and "eq" in pred else pred
    for a in assertions:
        for fld, chg in (a.get("expected_changes", {}) or {}).items():
            if fld not in row:
                row[fld] = _old_value(fld, chg, _new_value(chg))
    return row


def write_back(snapshot: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """One agent's write under full-object PUT semantics: the row becomes the agent's
    snapshot with its own changes applied — every OTHER field reverts to the snapshot.
    This is the lost-update mechanism itself: a stale snapshot silently reverts a peer."""
    row = dict(snapshot)
    for fld, val in changes.items():
        if val is _SENTINEL_ABSENT:
            row.pop(fld, None)
        else:
            row[fld] = val
    return row


def compose_final(orig: dict[str, Any], changes_a: dict[str, Any],
                  changes_b: dict[str, Any], *, serialized: bool) -> dict[str, Any]:
    """The row's FINAL state after A writes then B writes.

    NAIVE  (serialized=False): B's write-back was computed against `orig` (B read the row
            before A's write landed) — A's fields revert to `orig` (the lost update).
    SERIAL (serialized=True):  B's write-back was computed against the post-A row (what the
            arbiter's refusal of the concurrent lease forces) — both changes land.
    """
    after_a = write_back(orig, changes_a)
    b_snapshot = after_a if serialized else orig
    return write_back(b_snapshot, changes_b)


def net_diff(entity: str, orig: dict[str, Any], final: dict[str, Any]) -> dict[str, list]:
    """The OBSERVED diff the env differ would compute from before/after DB snapshots: one
    update row (before=orig, after=final), or an empty diff if nothing changed."""
    if final == orig:
        return {"inserts": [], "updates": [], "deletes": []}
    return {"inserts": [],
            "updates": [{"__table__": entity, "before": dict(orig), "after": dict(final)}],
            "deletes": []}


# --- the per-pair adjudication ------------------------------------------------------------

LOST_UPDATE_PREVENTED = "LOST_UPDATE_PREVENTED"
CONVERGENT_BENIGN = "CONVERGENT_BENIGN"
TRUE_CONFLICT = "TRUE_CONFLICT"


def classify_pair(naive_a_passed: bool, naive_b_passed: bool,
                  serial_a_passed: bool, serial_b_passed: bool) -> str:
    """The pair's class, driven ENTIRELY by the engine's four verdicts (pure, no I/O):

    naive both pass            -> CONVERGENT_BENIGN   (nothing was lost; J=0 is correct)
    serial both pass, naive not-> LOST_UPDATE_PREVENTED (the arbiter's serialization is
                                  exactly what recovers the lost write; the J row)
    serial cannot land both    -> TRUE_CONFLICT       (ordering preserves no-silent-loss but
                                  cannot make both specs land; reported, never counted)
    """
    if naive_a_passed and naive_b_passed:
        return CONVERGENT_BENIGN
    if serial_a_passed and serial_b_passed:
        return LOST_UPDATE_PREVENTED
    return TRUE_CONFLICT


@dataclass(frozen=True)
class PairResult:
    site: str                      # "<service>/<entity>/<row_key>"
    task_a: str
    task_b: str
    classification: str
    naive_a_passed: bool
    naive_b_passed: bool
    serial_a_passed: bool
    serial_b_passed: bool
    arbiter_serialized: bool       # the 2nd concurrent lease on the shared row was REFUSED
    disjoint_admitted: bool        # control: a lease on a DIFFERENT row was ADMITTED
    j: int                         # 1 iff LOST_UPDATE_PREVENTED and arbiter_serialized
    naive_failures: tuple[str, ...] = ()   # forensic: the engine NAMING the lost update


def _restricted_spec(assertion: dict[str, Any], gold_spec: dict[str, Any]) -> dict[str, Any]:
    """The task's gold spec RESTRICTED to its assertion on the shared row — the assertion
    object verbatim (never edited), plus the spec-level ignore_fields carried through. The
    coordination question is about the shared row; the task's other assertions assert
    effects outside the contended region."""
    spec: dict[str, Any] = {"assertions": [assertion]}
    if gold_spec.get("ignore_fields"):
        spec["ignore_fields"] = gold_spec["ignore_fields"]
    return spec


def coordinate_pair(task_a: BenchTask, task_b: BenchTask,
                    site: tuple[str, str, str]) -> PairResult:
    """Adjudicate one naturally-contending pair on its shared row, both arms, $0.

    Order is fixed (A writes first, B second) — the same single-direction convention as
    tau2's `coord_loop` (A1 cancels, A2 follows); the lost update is order-symmetric for
    disjoint-field pairs (either order, the stale second writer reverts the first)."""
    from .frozen_witness import evaluate_diff  # lazy: needs the clone (the engine)

    service, entity, _ = site
    a_assert = changed_row_keys(task_a)[site]
    b_assert = changed_row_keys(task_b)[site]
    where = a_assert.get("where", {}) or {}

    orig = original_row(where, a_assert, b_assert)
    ch_a, ch_b = change_set(a_assert), change_set(b_assert)

    final_naive = compose_final(orig, ch_a, ch_b, serialized=False)
    final_serial = compose_final(orig, ch_a, ch_b, serialized=True)
    diff_naive = net_diff(entity, orig, final_naive)
    diff_serial = net_diff(entity, orig, final_serial)

    spec_a = _restricted_spec(a_assert, task_a.gold_spec)
    spec_b = _restricted_spec(b_assert, task_b.gold_spec)
    w_na, w_nb = evaluate_diff(spec_a, diff_naive), evaluate_diff(spec_b, diff_naive)
    w_sa, w_sb = evaluate_diff(spec_a, diff_serial), evaluate_diff(spec_b, diff_serial)

    cls = classify_pair(w_na.passed, w_nb.passed, w_sa.passed, w_sb.passed)

    # the kernel arbiter: same-row 2nd lease refused (serialize); other-row lease admitted.
    row_key = site[2]
    region = row_region(service, entity, row_key)
    held = [{"lane": region[0], "kind": "keyword", "tree": region, "owner": task_a.test_id}]
    serialized = not arbiter_admits(region, held)
    other = row_region(service, entity, f"__disjoint_control_{row_key[:8]}__")
    disjoint_ok = arbiter_admits(other, held)

    j = 1 if (cls == LOST_UPDATE_PREVENTED and serialized) else 0
    return PairResult(
        site=f"{service}/{entity}/{row_key}", task_a=task_a.test_id, task_b=task_b.test_id,
        classification=cls,
        naive_a_passed=w_na.passed, naive_b_passed=w_nb.passed,
        serial_a_passed=w_sa.passed, serial_b_passed=w_sb.passed,
        arbiter_serialized=serialized, disjoint_admitted=disjoint_ok, j=j,
        naive_failures=tuple(f for w in (w_na, w_nb) for f in w.failures)[:4],
    )


# --- the A/B fold over all natural pairs ---------------------------------------------------

@dataclass(frozen=True)
class CoordABResult:
    split: str
    contention: ContentionReport
    pairs: tuple[PairResult, ...] = field(default_factory=tuple)

    @property
    def j_total(self) -> int:
        return sum(p.j for p in self.pairs)

    @property
    def n_lost_update(self) -> int:
        return sum(1 for p in self.pairs if p.classification == LOST_UPDATE_PREVENTED)

    @property
    def n_benign(self) -> int:
        return sum(1 for p in self.pairs if p.classification == CONVERGENT_BENIGN)

    @property
    def n_true_conflict(self) -> int:
        return sum(1 for p in self.pairs if p.classification == TRUE_CONFLICT)

    @property
    def all_serialized(self) -> bool:
        return all(p.arbiter_serialized for p in self.pairs) if self.pairs else False

    @property
    def all_disjoint_admitted(self) -> bool:
        return all(p.disjoint_admitted for p in self.pairs) if self.pairs else False


def frozen_coord_ab(split: str = "test") -> CoordABResult:
    """Run the believe-vs-adjudicate coordination A/B over every NATURAL pair, $0.

    believe   = the naive compose is what a coordination-free fleet publishes (B's stale
                write-back silently reverts A) — the engine refutes the reverted task.
    adjudicate= the arbiter refuses the 2nd concurrent lease, forcing the serialized compose
                — the engine confirms both tasks' changes landed.
    """
    report = natural_contention(split)
    tasks = {t.test_id: t for t in load_tasks(split)}
    results: list[PairResult] = []
    for site_str in sorted(report.sites):
        tids = report.sites[site_str]
        service, entity, row_key = site_str.split("/", 2)
        site = (service, entity, row_key)
        for a, b in itertools.combinations(tids, 2):
            results.append(coordinate_pair(tasks[a], tasks[b], site))
    return CoordABResult(split=split, contention=report, pairs=tuple(results))


def print_summary(split: str = "test") -> int:
    res = frozen_coord_ab(split)
    c = res.contention
    print(f"=== F3 — coordination A/B on Agent-Diff (split={split!r}, $0, production witness) ===")
    print(f"  write tasks                    {c.n_write_tasks}")
    print(f"  tasks pinning a changed row    {c.n_tasks_with_pinned_changed}")
    print(f"  task pairs / colliding         {c.n_pairs} / {c.n_colliding_pairs}"
          f"   (natural pairwise rate {c.natural_pairwise_rate:.2%})")
    print(f"  natural contention sites       {len(c.sites)}  -> verdict {c.verdict}")
    for p in res.pairs:
        print(f"\n  {p.task_a} + {p.task_b}  on {p.site}")
        print(f"    naive:  A={'PASS' if p.naive_a_passed else 'REFUTED'}"
              f"  B={'PASS' if p.naive_b_passed else 'REFUTED'}"
              f"   serial: A={'PASS' if p.serial_a_passed else 'REFUTED'}"
              f"  B={'PASS' if p.serial_b_passed else 'REFUTED'}")
        print(f"    class={p.classification}  arbiter_serialized={p.arbiter_serialized}"
              f"  disjoint_admitted={p.disjoint_admitted}  J={p.j}")
        if p.j and p.naive_failures:
            print(f"    engine names the lost update: {p.naive_failures[0][:140]}")
    print(f"\n  pairs: {len(res.pairs)}  lost-update-prevented (J): {res.j_total}"
          f"  benign: {res.n_benign}  true-conflict: {res.n_true_conflict}")
    print(f"  arbiter serialized every contended pair: {res.all_serialized}"
          f"   admitted every disjoint control: {res.all_disjoint_admitted}")
    print(f"\n  J = {res.j_total} lost updates the arbiter-serialized compose lands and the"
          f"\n      naive compose silently reverts — adjudicated by Agent-Diff's OWN engine."
          f"\n      (tau2's DB-hash said the same thing on its pairs: two witnesses agree.)")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(print_summary("train" if "--train" in sys.argv else "test"))
