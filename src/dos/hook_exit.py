"""HEX — the hook exit-code classifier: *a plain shell script's exit code → an intervention verb.*

docs/226 — idea **C3** from the Claude Code source audit (docs/189). The cheapest
possible integration surface: a host has a shell script that checks something (a
linter, a policy probe, a smoke test) and signals its result the only way a plain
process can — an **exit code**. CC already gives this a meaning
(`src/utils/hooks.ts`): a command hook's `exit 0` is success (proceed), `exit 2` is
a *blocking error* (stop the action), and any other non-zero is a non-blocking error
(a warning that still proceeds). It is the same convention `git` hooks and
`pre-commit` use — universal, zero-ceremony, no JSON parser required.

DOS has rich hook adapters (`pretool_sensor`, `posttool_sensor`) that read the CC
JSON dialect, and a closed intervention vocabulary (`intervention.Intervention`:
OBSERVE‹WARN‹BLOCK‹DEFER). What it lacked was the *bridge* between the two for the
**unsophisticated** integration: "I just have a shell script that exits 2 — turn
that into a DOS intervention." This module is that bridge — a pure map from an exit
code to an `Intervention` verb.

It is the `liveness`/`productivity`/`breaker` shape — a pure verdict over
already-gathered state — for a different input:

    liveness.classify       (ProgressEvidence, policy)   -> LivenessVerdict
    productivity.classify    (WorkHistory, policy)         -> ProductivityVerdict
    breaker.classify         (BreakerCounts, policy)       -> BreakerVerdict
    hook_exit.classify_exit  (code, policy)                -> ExitVerdict
                             ^ THIS module

**Mechanism vs policy — the malloc split.** The mechanism is "look up the exit code
in a map." The policy — *which code means which verb* — is data, defaulted to CC's
convention (`0 → pass`, `2 → BLOCK`, other-nonzero → WARN) and declarable
per-workspace in `dos.toml [hook_exit]`. A host that wants `exit 3 = DEFER`, or
`exit 0 = OBSERVE` (record even on success), changes one line of data; the kernel's
lookup never changes. The classifier never knows what the script *did* — only the
code it returned. That is what makes it a universal cog: it is the `malloc` of
shell-hook integration, mechanism with the script's domain pushed entirely out.

**Why a script's exit code is sound evidence here.** The exit code is authored by
the *script process*, not by the judged agent — it is the script's verdict on the
agent's action, exactly the actor-witness split (docs/117): the byte-author (the
script) is not the judged party (the agent). So `classify_exit` reads an
agent-external signal, the same discipline `liveness` (git) and `exec_capability`
(the command shape) follow. The script is a deterministic JUDGE on the trust ladder;
this module routes its terse verdict into the kernel's vocabulary.

**Advisory, fail-safe.** The verdict RECOMMENDS an intervention; like every verb in
this family it never acts. And the safe-failure direction is baked into the default
map: an *unknown* non-zero code degrades to WARN (inform, do not block) — never to a
silent pass and never to a spurious BLOCK. A script that fails in a way the host did
not anticipate surfaces as a warning, the docs/143 −9 pp posture (a wrong BLOCK is
the expensive mistake; a WARN is cheap).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dos.intervention import Intervention


# ---------------------------------------------------------------------------
# The default convention — CC's `src/utils/hooks.ts` exit-code semantics, lifted
# verbatim, as data. `0` = proceed (no intervention); `2` = blocking error
# (BLOCK); any OTHER non-zero = non-blocking error (WARN, the fallback). Declared
# as a map so a workspace overrides it in `dos.toml [hook_exit]` — the
# closed-config-as-data pattern (`[lanes]`/`[reasons]`/`[exec_capability]`).
# ---------------------------------------------------------------------------
# The codes that map to a SPECIFIC verb. `0` is the special "pass" code (no
# intervention) — represented as None in the map so it is distinct from OBSERVE
# (OBSERVE records a verdict; PASS records nothing and proceeds). Every other
# non-zero code not named here falls to `fallback`.
_CC_EXIT_MAP: dict[int, Optional[Intervention]] = {
    0: None,                  # success — proceed, no intervention (the PASS code)
    2: Intervention.BLOCK,    # blocking error — CC's `exit 2` (the load-bearing one)
}
_CC_FALLBACK = Intervention.WARN  # any other non-zero — non-blocking error → inform


@dataclass(frozen=True)
class HookExitPolicy:
    """The exit-code → intervention map — policy, not mechanism.

    The same "mechanism is kernel, the map is config" split as `liveness`'s windows
    and `breaker`'s thresholds. Defaults to CC's convention; a workspace declares its
    own in `dos.toml [hook_exit]`, e.g. `3 = "DEFER"`, `0 = "OBSERVE"`.

      pass_code   — the exit code that means "proceed, no intervention" (default 0).
                    The script approved; nothing to actuate.
      mapping     — explicit `{code: Intervention}` for codes that map to a verb.
                    A code present here with value None is also treated as PASS (a
                    host can declare multiple success codes).
      fallback    — the verb for any non-zero code NOT in `mapping` and not the
                    `pass_code` (default WARN — inform, the fail-safe direction; never
                    a silent pass, never a spurious BLOCK on an unanticipated code).
    """

    pass_code: int = 0
    mapping: dict[int, Intervention] = field(
        default_factory=lambda: {2: Intervention.BLOCK}
    )
    fallback: Intervention = _CC_FALLBACK

    def with_mapping(self, more: dict) -> "HookExitPolicy":
        """A new policy with `more` `{code: Intervention}` entries merged in (host on-ramp)."""
        merged = dict(self.mapping)
        for code, verb in (more or {}).items():
            merged[int(code)] = verb if isinstance(verb, Intervention) else Intervention(str(verb))
        return HookExitPolicy(pass_code=self.pass_code, mapping=merged, fallback=self.fallback)


DEFAULT_POLICY = HookExitPolicy()


@dataclass(frozen=True)
class ExitVerdict:
    """The classifier's verdict: the intervention an exit code maps to (None = PASS).

    `intervention` is the `Intervention` the code maps to, or None when the code is
    the pass code (proceed, nothing to actuate — distinct from OBSERVE, which records
    a verdict). `code` is the exit code classified (echoed for the JSON consumer).
    `reason` is the one-line operator-facing summary. `matched` says whether the code
    was an EXPLICIT map entry (True) or fell to the fallback (False) — legible
    distrust: the consumer can tell a declared mapping from the catch-all.
    """

    code: int
    intervention: Optional[Intervention]
    reason: str
    matched: bool

    @property
    def passed(self) -> bool:
        """True iff the script approved — proceed, no intervention."""
        return self.intervention is None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "intervention": self.intervention.value if self.intervention else None,
            "reason": self.reason,
            "matched": self.matched,
        }


def classify_exit(
    code: int, policy: HookExitPolicy = DEFAULT_POLICY
) -> ExitVerdict:
    """Map a hook script's exit code → an intervention verb. PURE — no I/O.

    The ladder:
      1. PASS — `code == policy.pass_code` (default 0): the script approved. Proceed,
         no intervention (`intervention=None`). The success case.
      2. MAPPED — `code` is an explicit `policy.mapping` entry: the declared verb
         (default `2 → BLOCK`, CC's blocking-error code). `matched=True`.
      3. FALLBACK — any other non-zero code: `policy.fallback` (default WARN). The
         fail-safe catch-all — an unanticipated failure informs, never silently
         passes and never spuriously blocks. `matched=False`.

    `code` is the integer a host captured from `subprocess`/`$?`. The classifier
    reads only the code — never the script's stdout/stderr or what it did (that is
    the script's domain, pushed out; the kernel maps the terse signal).
    """
    # A code explicitly mapped to None (a host's extra success code) is also PASS.
    if code == policy.pass_code or (code in policy.mapping and policy.mapping[code] is None):
        return ExitVerdict(
            code=code,
            intervention=None,
            reason=f"exit {code} — the hook script approved; proceed (no intervention)",
            matched=code in policy.mapping or code == policy.pass_code,
        )
    verb = policy.mapping.get(code)
    if verb is not None:
        return ExitVerdict(
            code=code,
            intervention=verb,
            reason=(
                f"exit {code} → {verb.value} (a declared hook-exit mapping"
                + (" — CC's blocking-error code)" if code == 2 and verb is Intervention.BLOCK
                   else ")")
            ),
            matched=True,
        )
    return ExitVerdict(
        code=code,
        intervention=policy.fallback,
        reason=(
            f"exit {code} → {policy.fallback.value} (a non-zero code with no declared "
            f"mapping — the fail-safe fallback: inform, never silently pass or block)"
        ),
        matched=False,
    )
