"""docs/296 — the operator-armed SELF_MODIFY override: read the arm file, dispose the deny.

The SELF_MODIFY refusal is a PURE verdict and stays one: a tool call whose
footprint hits the kernel's own runtime files IS self-modification, armed
window or not. What this module adds is the ENFORCEMENT-side disposition the
trust ladder always named but never wired (ORACLE → JUDGE → HUMAN, and
`dos man wedge SELF_MODIFY`'s "the operator's explicit 'I am deliberately
editing the kernel between loop runs'"): the operator hand-writes a small,
expiring arm file, and the PRE hook — the PEP-side emitter, one rung ABOVE
the verdict — converts the deny it would have rendered into an
ALLOW-with-note while that window is open. PDP decides; PEP disposes.

The arm file, hand-typed by the operator at ``.dos/override/self-modify.toml``::

    until  = 2026-06-10T23:30:00Z          # hard deadline; REQUIRED
    reason = "issue #11 — refuse-reason rename"   # REQUIRED; lands in the note
    scope  = ["src/dos/arbiter.py"]        # optional; absent = the whole T1 set

Two halves, the house split:

* ``read_override`` — boundary I/O: parse the arm file under the workspace
  root into a frozen ``OverrideFacts``, or None. FAIL-CLOSED on every branch:
  a missing, unparseable, or incomplete arm file can only fail to admit,
  never fail to deny.
* ``dispose`` — PURE: facts + the refused call's reason-class/targets +
  ``now`` in, the override note out (None = no disposition; the deny stands).
  Only a ``SELF_MODIFY`` refusal is ever converted — the arm file is a
  self-modify instrument and must never wave through a collision or budget
  deny. A SCOPED window with an unparseable footprint stays denied (we
  cannot show the targets are inside the scope).

Deliberately ABSENT: any arming surface. There is no ``dos override arm``
verb and nothing here writes the file — any verb an agent's shell can call
is an arming path an agent can take, so arming is the operator's hand on the
file, full stop (the docs/296 asymmetry: anyone may disarm, only the human
arms). The hook layer additionally DENIES an agent write that touches
``ARM_RELPATH`` (see ``pretool_sensor``), and that perimeter deny is never
subject to ``dispose`` — a window must not be able to extend itself.

Threat model, stated honestly (docs/296): this raises the bar for
COOPERATIVE agents exactly as far as the SELF_MODIFY guard itself does — no
further. An agent with arbitrary exec can write any file through a
subprocess; the guard was never proof against that, and this module claims
nothing stronger. What it buys: the sanctioned human override becomes a
recorded, expiring, scoped protocol move instead of an invisible
out-of-band script.

Kernel litmus: stdlib-only, no host names, no vendor names; I/O confined to
``read_override`` (the boundary); ``dispose`` is a pure function of its
inputs. Lineage: docs/296 (this module is its Phase 1).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path, PurePosixPath
from typing import Optional


# The arm file's workspace-relative home. Inside `.dos/` (the gitignored DOS
# state dir) so an armed window can never be accidentally committed.
ARM_RELPATH = PurePosixPath(".dos/override/self-modify.toml")

# The ONLY reason-class `dispose` may convert (see the module docstring).
_OVERRIDABLE_REASON_CLASS = "SELF_MODIFY"


@dataclasses.dataclass(frozen=True)
class OverrideFacts:
    """The operator's armed window, as parsed data (frozen — evidence, not state)."""

    until: dt.datetime          # hard deadline; always tz-aware after parsing
    reason: str                 # the operator's why — lands in the audit note
    scope: tuple[str, ...] = () # normalized relative paths; () = the whole T1 set
    source: str = ""            # where it was read from (display only)


def arm_path(root: Path) -> Path:
    """The arm file's absolute path under a workspace root."""
    return Path(root).joinpath(*ARM_RELPATH.parts)


def _norm(path_text: str) -> str:
    """One normalized spelling for a workspace-relative path: posix slashes,
    no leading ``./``, casefolded (the same fold the lane trees use — path
    compares on a case-insensitive FS must not depend on typed case)."""
    text = str(path_text or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/").casefold()


def touches_arm_path(targets) -> bool:
    """True iff any target path IS (or is inside) the arm file's directory.

    The perimeter test the hook runs BEFORE admission: an agent write that
    lands anywhere under ``.dos/override/`` is refused outright, and that
    refusal is never converted by ``dispose`` (a window must not extend
    itself)."""
    arm_dir = _norm(str(ARM_RELPATH.parent))
    arm_file = _norm(str(ARM_RELPATH))
    for t in targets or ():
        n = _norm(t)
        if not n:
            continue
        # Match the workspace-relative spelling AND any absolute spelling
        # that ends on it (the event may carry either form).
        if n == arm_file or n.endswith("/" + arm_file):
            return True
        if n == arm_dir or n.endswith("/" + arm_dir) or ("/" + arm_dir + "/") in ("/" + n + "/"):
            return True
    return False


def _coerce_until(value) -> Optional[dt.datetime]:
    """The deadline, tz-aware, or None (fail-closed).

    TOML yields a real datetime for a bare ``until = 2026-…Z``; a quoted
    string is parsed via ``fromisoformat`` (py3.11 accepts the trailing Z).
    A NAIVE value is read as the operator's LOCAL wall clock — the friendly
    reading of a hand-typed time — and made aware before comparing."""
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()  # naive → the local wall clock, made aware
    return parsed


def read_override(root: Path) -> Optional[OverrideFacts]:
    """Parse the arm file under ``root`` → ``OverrideFacts``, or None (fail-closed).

    Boundary I/O. None on: missing file, unreadable file, TOML that does not
    parse, missing/blank ``reason``, missing/invalid ``until``, or a ``scope``
    that is not a list of strings. A malformed override can only fail to
    admit, never fail to deny."""
    p = arm_path(root)
    try:
        raw = p.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        import tomllib  # py3.11+
    except ModuleNotFoundError:  # pragma: no cover — py<3.11 with no backport
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            return None
    try:
        data = tomllib.loads(raw)
    except Exception:  # noqa: BLE001 — any parse fault is the fail-closed branch
        return None
    if not isinstance(data, dict):
        return None
    until = _coerce_until(data.get("until"))
    reason = data.get("reason")
    if until is None or not isinstance(reason, str) or not reason.strip():
        return None
    scope_raw = data.get("scope", [])
    if not isinstance(scope_raw, list) or not all(isinstance(s, str) for s in scope_raw):
        return None
    scope = tuple(_norm(s) for s in scope_raw if str(s).strip())
    return OverrideFacts(until=until, reason=reason.strip(), scope=scope, source=str(p))


def _in_scope(target: str, scope: tuple[str, ...]) -> bool:
    """True iff a normalized target equals a scope entry or sits under a
    scope entry read as a directory."""
    n = _norm(target)
    for s in scope:
        if n == s or n.startswith(s + "/"):
            return True
    return False


def dispose(
    reason_class: str,
    targets: tuple[str, ...],
    facts: Optional[OverrideFacts],
    *,
    now: dt.datetime,
) -> Optional[str]:
    """The PURE disposition: the override note, or None (the deny stands).

    Converts iff ALL of: facts present; the refusal is ``SELF_MODIFY`` (never
    a collision/budget deny); ``now`` is inside the window; and — when the
    window is scoped — every target is provably inside the scope (a scoped
    window with no parseable targets stays denied). The returned note is the
    ``additionalContext`` the hook emits in place of the deny, naming the
    deadline and the operator's reason so the admit is on the record next to
    the verdict it overrode."""
    if facts is None:
        return None
    if str(reason_class or "") != _OVERRIDABLE_REASON_CLASS:
        return None
    here = now if now.tzinfo is not None else now.astimezone()
    if here > facts.until:
        return None
    if facts.scope:
        if not targets:
            return None
        if not all(_in_scope(t, facts.scope) for t in targets):
            return None
    return (
        f"operator override armed until {facts.until.isoformat()} — admitting "
        f"supervised kernel edit: {facts.reason}. The SELF_MODIFY verdict itself "
        f"is unchanged; this is the operator's window (docs/296). "
        f"Disarm any time: dos override disarm"
    )
