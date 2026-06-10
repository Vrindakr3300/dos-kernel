"""Open-loop arm — believe the workers; no oracle, no arbiter.

This is the plain-orchestrator baseline (`README.md`): the loop calls each
worker, gets a `{shipped: true, sha}` claim, and **banks it verbatim**. It has
no ground-truth check and no concurrency control, so:

  * every claimed-shipped phase is counted as shipped — INCLUDING the lies and
    flakes (the worker said `shipped: true`; the loop has no way to know better);
  * concurrent writes to the same shared file silently clobber each other — the
    loop never sees the collision (last-write-wins, undetected data loss).

It runs the SAME workload and the SAME failure model as the closed loop — the
only difference is that it believes the output instead of adjudicating it. The
defects it banks are real properties of its own run, which the closed loop will
later reveal (the §6.2 honesty point: the open loop produced these, measured or
not).
"""
from __future__ import annotations

from . import metrics
from .agent import FailureModel
from .metrics import Event, score, Metrics
from .workload import Workload, interleave


def run(workload: Workload, model: FailureModel, *, run_seed: int,
        kappa: float = metrics.DEFAULT_KAPPA,
        review_mu: float = metrics.DEFAULT_REVIEW_MU) -> tuple[Metrics, list[Event]]:
    events: list[Event] = []
    workers = {e.name: model.worker(e.name) for e in workload.efforts}

    # ground-truth shipped set (for honest metric 4) — NOT visible to the arm's
    # decisions; only the scorer reads real_ship events. The arm itself believes
    # `claimed_shipped` blindly.
    really_shipped: set[tuple[str, str]] = set()

    # Same concurrency window as the closed loop (so both arms count the SAME
    # physical collisions — apples to apples). An in-flight write to a shared file
    # is recorded with the step it expires; a later real write to the same file
    # while a DIFFERENT effort's write is still in flight is a silent overwrite the
    # open loop suffers undetected (the closed loop's arbiter refuses these).
    window = max(1, workload.n_efforts - 1)
    inflight: dict[str, list[tuple[str, int]]] = {}   # file -> [(effort, expires_at)]

    for step, phase in enumerate(interleave(workload, seed=run_seed)):
        w = workers[phase.effort]
        key = (phase.effort, phase.phase_id)

        # The open loop has no oracle, so "already shipped?" is whatever it last
        # banked — and it banks lies, so its notion of shipped is corrupt. It
        # re-attempts nothing on purpose (no replan), so rework here is only the
        # workload's own accidental repeats; we still surface the ground-truth flag.
        claim = w.attempt(phase, already_shipped=(key in really_shipped))

        # every attempt costs an action; a thrash step costs an extra no-progress action
        events.append(Event("action", phase.effort, phase.phase_id))
        if w.will_thrash():
            events.append(Event("action", phase.effort, phase.phase_id))
            events.append(Event("thrash", phase.effort, phase.phase_id))

        # GROUND TRUTH bookkeeping (scorer-only)
        if claim.really_committed:
            events.append(Event("real-ship", phase.effort, phase.phase_id))
            really_shipped.add(key)
            # detect silent overwrites on shared files (undetected by the arm)
            for f in claim.wrote_files:
                if not f.startswith("shared/"):
                    continue
                holders = [(e, x) for (e, x) in inflight.get(f, []) if x > step]
                if any(e != phase.effort for (e, x) in holders):
                    prev = next(e for (e, x) in holders if e != phase.effort)
                    events.append(Event(
                        "silent-overwrite", phase.effort, phase.phase_id,
                        detail=f"{f} clobbered (concurrent writer {prev})"))
                    # docs/81 §2.2/§4.2: a banked silent overwrite is a latent
                    # conflict that DETONATES downstream as a hand-merge. The open
                    # loop pays it later; we record the deferred bill its own output
                    # already incurred (not a penalty — a cost it produced).
                    events.append(Event(
                        "conflict-detonation", phase.effort, phase.phase_id))
                holders.append((phase.effort, step + window))
                inflight[f] = holders
        if claim.is_rework:
            events.append(Event("rework", phase.effort, phase.phase_id))

        # THE ARM'S DECISION: believe the claim. No verification.
        if claim.claimed_shipped:
            events.append(Event("banked-shipped", phase.effort, phase.phase_id))
            # docs/81 §2.3/§4.2: NOTHING adjudicated completeness, so EVERY banked
            # "done" must be confirmed by a human → it enters the review queue. This
            # is the 100% human-review fraction that drives the Faros paradox.
            events.append(Event("human-review", phase.effort, phase.phase_id))
            if claim.is_lie:
                # the arm banked a falsehood and does NOT know it
                events.append(Event("banked-lie", phase.effort, phase.phase_id))

    return score("open-loop", events, total_phases=workload.total_phases,
                 horizon=workload.n_phases_each, kappa=kappa, review_mu=review_mu), events
