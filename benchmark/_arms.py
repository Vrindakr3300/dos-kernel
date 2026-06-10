"""Shared benchmark *arm* vocabulary — the single source of truth for the DOS_*
env knobs that select an experimental arm.

WHY THIS EXISTS. Before standardization every benchmark hand-set raw `DOS_*`
environment variables, and the canonical mapping {arm-name -> env} lived inline
in `enterpriseops/live_ab.py:_ARM_ENV`. That is the cure for env-knob soup — a
named arm the operator asks for, never a hand-set variable — so it is lifted
here ONE level, to be shared by `live_ab.py` (re-imported, single source) and by
the standardized runner (`benchmark/_run.py` via `benchmark/registry.py`).

This module is pure stdlib data + two helpers. It imports nothing from `dos` and
nothing from a benchmark; it is a leaf the way `dos.reasons`/`dos.stamp` are
seam-data leaves of the kernel. Benchmarks (the consumer side) import it; the
kernel never does (the one-way arrow, enforced by tests/test_bench_layering.py).
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, Mapping

# ---------------------------------------------------------------------------
# The intervention-arm vocabulary (lifted verbatim from live_ab.py:_ARM_ENV).
# Each arm name maps to the DOS_* env it sets; everything NOT named is popped
# between arms by clear_dos_knobs() so one arm's flag never leaks into the next.
# ---------------------------------------------------------------------------
ARM_ENV: Dict[str, Dict[str, str]] = {
    # --- the OBSERVE/DEFER/WARN/BLOCK intervention ladder (docs/144/151) ---
    "none":  {"DOS_CONSULT": "0"},
    "defer": {"DOS_CONSULT": "1", "DOS_INTERVENTION": "DEFER"},
    "warn":  {"DOS_CONSULT": "1", "DOS_INTERVENTION": "WARN"},
    "block": {"DOS_CONSULT": "1", "DOS_INTERVENTION": "BLOCK"},
    # --- the rewindable / restart FIX arms (docs/171/172/176) ---
    "rewind":         {"DOS_CONSULT": "1", "DOS_INTERVENTION": "BLOCK", "DOS_REWIND": "1"},
    "rewind_natural": {"DOS_CONSULT": "0", "DOS_REWIND_NATURAL": "1"},
    "stall":          {"DOS_CONSULT": "0", "DOS_STALL": "1"},
    "resurface":      {"DOS_CONSULT": "0", "DOS_DANGLING": "1"},
    "restart":        {"DOS_CONSULT": "1", "DOS_INTERVENTION": "BLOCK", "DOS_RESTART": "1"},
    "restart_seeded": {"DOS_CONSULT": "1", "DOS_INTERVENTION": "BLOCK",
                       "DOS_RESTART": "1", "DOS_RESTART_SEED": "1"},
    # --- the curable-CONVERSION arm (docs/200/205): on a NATURAL same-tool thrash, re-surface the
    # env's OWN schema/reference/state corrective as a forcing function (an ADDITIVE re-prompt, never
    # a subtract). CONSULT=0 so it rides the post-dispatch ENV-failure stream like rewind_natural —
    # it is NOT a mint verdict. DOS authors only the framing; every corrective byte is the env's. ---
    "schema_refresh": {"DOS_CONSULT": "0", "DOS_SCHEMA_REFRESH": "1"},
    # --- the toolathlon live A/B arm: the ONLY delta is the DOS_WARN flag ---
    "observe": {},
    "warn_stream": {"DOS_WARN": "1"},
}

# Every DOS knob ANY arm can set — popped between arms so a process-wide flag
# (DOS_PRECURSOR / DOS_DANGLING are process-wide) never contaminates the next
# arm's baseline (the docs/152 refutation). Superset of every key in ARM_ENV
# plus the knobs an arm implies downstream (DOS_WARN_ONLY, DOS_PRECURSOR*,
# DOS_TERMINAL_ERROR) that live_ab.py also clears.
ALL_DOS_KNOBS = (
    "DOS_CONSULT", "DOS_INTERVENTION", "DOS_WARN", "DOS_WARN_ONLY", "DOS_DANGLING",
    "DOS_PRECURSOR", "DOS_PRECURSOR_GRAMMAR", "DOS_REWIND", "DOS_REWIND_NATURAL",
    "DOS_STALL", "DOS_TERMINAL_ERROR", "DOS_RESTART", "DOS_RESTART_SEED",
    "DOS_SCHEMA_REFRESH",
)


def clear_dos_knobs(env: Mapping[str, str] = None) -> None:
    """Pop every DOS_* arm knob from the given env (default os.environ), so a
    prior arm's flag cannot leak into the next run."""
    target = os.environ if env is None else env
    for k in ALL_DOS_KNOBS:
        target.pop(k, None)


def arm_env(arm: str) -> Dict[str, str]:
    """The DOS_* env a named arm sets. Raises KeyError on an unknown arm so the
    runner refuses-don't-guess rather than silently running the baseline."""
    return dict(ARM_ENV[arm])


def known_arms() -> Iterable[str]:
    return sorted(ARM_ENV)
