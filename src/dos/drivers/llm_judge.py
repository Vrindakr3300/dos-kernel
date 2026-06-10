"""dos.drivers.llm_judge — the OPTIONAL LLM adjudicator (outside the kernel line).

The kernel's judge (`dos judge` → `picker_oracle.classify`) is **deterministic by
construction**: it cross-checks a no-pick verdict's self-reported `reason_class`
against on-disk state and emits a provable `oracle_disagrees`. That is the right
default — the kernel's whole thesis is "the part that doesn't believe the agents,"
and it must never grow an LLM-provider branch (the DSP "Bulkhead" axiom).

But the deterministic oracle can only *abstain* on the `UNCLASSIFIED` rows — a
no-pick whose `reason_class` is a legacy / hand-authored token it has no
cross-check for. Those are exactly the rows an LLM adjudicator can usefully rule
on. So the LLM judge lives **here, in a driver** — outside the kernel boundary,
where provider surface is allowed (`drivers/__init__.py`: "they import the
kernel; the kernel never imports them"). The kernel CLI's `dos judge` points
here on an abstain; nothing in the kernel imports this module.

Contract (the honest part):
  * **Deterministic-first.** This driver runs `picker_oracle` first and returns
    its verdict verbatim whenever the oracle did NOT abstain. The LLM is consulted
    ONLY for the `UNCLASSIFIED` residue — it never overrides a provable verdict.
  * **Graceful when no provider.** The actual model call goes through one seam,
    `_call_provider`. With no provider wired (no `DOS_LLM_JUDGE_CMD`, no SDK),
    the seam returns an abstention and the driver reports "unadjudicated —
    configure a provider," never a crash and never a hard dependency. The package
    stays installable and the kernel stays pure.
  * **A judge is advisory.** This driver emits a verdict; it does not mutate any
    lease/registry/plan. Acting on its ruling is the operator's call (or a
    separately-wired automation), exactly as the decision-queue actions are
    emit-and-exit. The LLM never *believes itself into* a state change.

Usage:
    python -m dos.drivers.llm_judge <run_ts>            # adjudicate one run
    python -m dos.drivers.llm_judge <run_ts> --json     # machine-readable
    DOS_LLM_JUDGE_CMD='claude -p --model claude-haiku-4-5' python -m dos.drivers.llm_judge <run_ts>
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
from typing import Optional

# Imports the kernel — never the other way round (the driver rule).
from dos import config as _config
from dos import picker_oracle


# The env var naming the provider command. It must read a prompt on stdin and
# write the adjudication on stdout. `claude -p` is the canonical fit, but ANY
# command honoring that contract works — the driver is provider-agnostic at this
# seam, which is what keeps the kernel provider-invariant: the coupling lives in
# the operator's env, not in the code.
ENV_JUDGE_CMD = "DOS_LLM_JUDGE_CMD"


@dataclasses.dataclass(frozen=True)
class LlmVerdict:
    """The driver's adjudication of one no-pick run.

    `engine` is `"oracle"` when the deterministic judge ruled (the LLM was not
    needed), `"llm"` when the model adjudicated the UNCLASSIFIED residue, or
    `"unadjudicated"` when the oracle abstained AND no provider is wired.
    `agrees_with_picker` mirrors the inverse of the oracle's `oracle_disagrees`
    for the deterministic path; for the LLM path it is the model's own call.
    """

    run_ts: str
    engine: str                       # "oracle" | "llm" | "unadjudicated"
    cause: str                        # the no_pick_cause (oracle) or LLM-stated cause
    agrees_with_picker: Optional[bool]
    rationale: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "run_ts": self.run_ts,
            "engine": self.engine,
            "cause": self.cause,
            "agrees_with_picker": self.agrees_with_picker,
            "rationale": self.rationale,
            "evidence": list(self.evidence),
        }


def _call_provider(prompt: str) -> str | None:
    """The provider seam. Returns the model's raw stdout, or None if unavailable.

    Honors `$DOS_LLM_JUDGE_CMD` (a shell command reading the prompt on stdin,
    writing the verdict on stdout). Never raises — any failure (no command set,
    command missing, timeout, non-zero exit) returns None so the caller degrades
    to an "unadjudicated" verdict. This is the ONE place a provider is touched;
    keeping it a single guarded seam is what lets the package ship with zero LLM
    dependency while still allowing an operator to wire one in by env var.
    """
    cmd = os.environ.get(ENV_JUDGE_CMD)
    if not cmd:
        return None
    try:
        # shell=True so an operator can set a full `claude -p --model …` string.
        p = subprocess.run(
            cmd,
            shell=True,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    out = (p.stdout or b"").decode("utf-8", errors="replace").strip()
    return out or None


def _build_prompt(verdict: picker_oracle.PickerVerdict) -> str:
    """The adjudication prompt for the UNCLASSIFIED residue.

    Deliberately asks for a strict, skeptical ruling — the LLM stands in for the
    deterministic cross-check the oracle could not perform, so it must DEFAULT to
    distrusting the picker's self-report (the kernel's posture), not rubber-stamp it.
    """
    return (
        "You are a strict adjudicator for a dispatch system. A picker reported a "
        "NO-PICK (it found no dispatchable work) and gave a free-text reason, but "
        "the deterministic oracle could not classify it (no known reason_class to "
        "cross-check). Decide whether the picker's no-pick is BELIEVABLE given its "
        "stated reason, or whether it looks like a picker bug (work likely existed). "
        "Default to skepticism: if the reason is vague or unfalsifiable, lean "
        "'disagree'. Answer in two lines:\n"
        "VERDICT: <agree|disagree>\n"
        "WHY: <one sentence>\n\n"
        f"Run: {verdict.run_ts}\n"
        f"Lane: {verdict.lane}\n"
        f"Picker's stated reason: {verdict.picker_reason or '(none given)'}\n"
    )


def _parse_llm_reply(reply: str) -> tuple[Optional[bool], str]:
    """Parse the model's `VERDICT:`/`WHY:` reply into (agrees, rationale).

    Tolerant: a reply that doesn't match the format yields (None, <raw reply>) so
    an off-format model degrades to "ruled, but unparseable" rather than a crash.
    """
    agrees: Optional[bool] = None
    why = reply.strip()
    for line in reply.splitlines():
        low = line.strip().lower()
        if low.startswith("verdict:"):
            val = low.split(":", 1)[1].strip()
            if "agree" in val and "disagree" not in val:
                agrees = True
            elif "disagree" in val:
                agrees = False
        elif low.startswith("why:"):
            why = line.split(":", 1)[1].strip()
    return agrees, why


def adjudicate(run_ts: str, config: _config.SubstrateConfig | None = None) -> LlmVerdict:
    """Adjudicate one no-pick run: deterministic-first, LLM for the residue.

    Returns an `LlmVerdict`. Never raises on a provider problem — it degrades to
    an `engine="unadjudicated"` verdict the caller can report honestly.
    """
    cfg = _config.ensure(config)
    state = picker_oracle._load_yaml(cfg.paths.execution_state)
    oracle_verdict = picker_oracle._classify_one(run_ts, state)
    cause = (oracle_verdict.no_pick_cause.value
             if oracle_verdict.no_pick_cause else "UNCLASSIFIED")

    # Deterministic-first: if the oracle could classify it, the LLM is not needed.
    if cause != "UNCLASSIFIED":
        return LlmVerdict(
            run_ts=run_ts,
            engine="oracle",
            cause=cause,
            agrees_with_picker=not oracle_verdict.oracle_disagrees,
            rationale=(
                "deterministic oracle ruled — LLM not consulted "
                f"(oracle_disagrees={oracle_verdict.oracle_disagrees})"
            ),
            evidence=oracle_verdict.evidence,
        )

    # UNCLASSIFIED residue — consult the LLM through the guarded seam.
    reply = _call_provider(_build_prompt(oracle_verdict))
    if reply is None:
        return LlmVerdict(
            run_ts=run_ts,
            engine="unadjudicated",
            cause="UNCLASSIFIED",
            agrees_with_picker=None,
            rationale=(
                "oracle abstained (no reason_class to verify) and no LLM provider "
                f"is wired — set ${ENV_JUDGE_CMD} to a `claude -p`-style command to "
                "adjudicate the residue"
            ),
            evidence=oracle_verdict.evidence,
        )
    agrees, why = _parse_llm_reply(reply)
    return LlmVerdict(
        run_ts=run_ts,
        engine="llm",
        cause="UNCLASSIFIED",
        agrees_with_picker=agrees,
        rationale=why,
        evidence=oracle_verdict.evidence + (f"llm: {reply[:200]}",),
    )


# ---------------------------------------------------------------------------
# The generic Judge-protocol occupant of the JUDGE rung (dos.judges, Axis 6).
# ---------------------------------------------------------------------------
#
# `adjudicate()` above is the original, picker-specific entry: it rules on a no-pick
# `run_ts`. `LlmJudge` is the *domain-neutral* face of the same machinery — it
# implements `dos.judges.Judge`, so it plugs into the trust ladder, the
# `dos judge-eval` instrument, and any consumer of the generic seam, ruling on an
# arbitrary `Claim` rather than only a no-pick row. It is the reference occupant of
# the JUDGE rung: a researcher's own judge implements the same `rule(claim, config)`
# shape, and `compose_deterministic_first` composes it under the same discipline.
#
# It reuses `_call_provider` verbatim (one provider seam, env-configured), so the
# kernel stays provider-invariant and the package ships with zero LLM dependency.
# The disciplines hold: advisory-only (it returns a `JudgeVerdict`, mutates nothing),
# and fail-to-abstain — with no provider wired, or on any provider error, `rule`
# ABSTAINS (never AGREE), so a missing model degrades to "ask a human," never to a
# rubber-stamp. (The `run_judge` wrapper would catch a raise too; `LlmJudge.rule`
# additionally abstains *gracefully* on the expected no-provider path so the verdict
# carries a useful "wire $DOS_LLM_JUDGE_CMD" message rather than a stack trace.)


def _build_claim_prompt(claim) -> str:
    """A skeptical adjudication prompt for a generic `Claim`.

    Same posture as `_build_prompt` (the picker version): the model stands in for a
    cross-check the deterministic oracle could not perform, so it must DEFAULT to
    distrust — the kernel's stance. It is shown the claim, the agent's narration, and
    the forgery-resistant evidence, and asked whether the narration is supported.
    """
    ev = "\n".join(f"  - {e}" for e in (claim.evidence or ())) or "  (none provided)"
    return (
        "You are a strict adjudicator for an autonomous-agent substrate. An agent "
        "asserted a claim and gave a justification (its NARRATION), and the system "
        "gathered some forgery-resistant EVIDENCE (git lines, file state). The "
        "deterministic oracle could not settle this claim, so it falls to you. Decide "
        "whether the claim is BELIEVABLE GIVEN THE EVIDENCE — not given the narration, "
        "which you should distrust. Default to skepticism: if the evidence does not "
        "support the claim, answer 'disagree'; if you genuinely cannot tell from the "
        "evidence, answer 'abstain' (do NOT guess 'agree'). Answer in two lines:\n"
        "VERDICT: <agree|disagree|abstain>\n"
        "WHY: <one sentence>\n\n"
        f"CLAIM: {claim.claim_text}\n"
        f"AGENT NARRATION: {claim.stated_reason or '(none given)'}\n"
        f"EVIDENCE:\n{ev}\n"
    )


def _parse_three_valued(reply: str):
    """Parse a `VERDICT: agree|disagree|abstain` / `WHY:` reply into a JudgeVerdict.

    Tolerant: an off-format reply (no recognizable VERDICT line) → ABSTAIN, never a
    guessed AGREE — the conservative direction, consistent with the whole seam. A
    'disagree' substring is checked before 'agree' because "disagree" contains
    "agree".
    """
    from dos.judges import JudgeVerdict
    why = reply.strip()
    stance = None
    for line in reply.splitlines():
        low = line.strip().lower()
        if low.startswith("verdict:"):
            val = low.split(":", 1)[1].strip()
            if "abstain" in val:
                stance = "abstain"
            elif "disagree" in val:
                stance = "disagree"
            elif "agree" in val:
                stance = "agree"
        elif low.startswith("why:"):
            why = line.split(":", 1)[1].strip()
    if stance == "agree":
        return JudgeVerdict.agree(why, evidence=(f"llm: {reply[:200]}",))
    if stance == "disagree":
        return JudgeVerdict.disagree(why, evidence=(f"llm: {reply[:200]}",))
    return JudgeVerdict.abstain(
        why if stance == "abstain" else
        "LLM reply did not carry a parseable VERDICT — abstaining (never guess agree)",
        evidence=(f"llm: {reply[:200]}",),
    )


class LlmJudge:
    """The reference LLM occupant of the JUDGE rung — a `dos.judges.Judge`.

    Rules on a generic `Claim` via the `$DOS_LLM_JUDGE_CMD` provider seam, skeptical
    by default, advisory-only, fail-to-abstain. With no provider wired it abstains
    with a "configure a provider" message — so it is always safe to register and
    eval, even on a box with no model. Register it under the `dos.judges` entry-point
    group (or pass an instance directly to `judge_eval`):

        [project.entry-points."dos.judges"]
        llm = "dos.drivers.llm_judge:LlmJudge"
    """

    name = "llm"

    def rule(self, claim, config):
        from dos.judges import JudgeVerdict
        reply = _call_provider(_build_claim_prompt(claim))
        if reply is None:
            return JudgeVerdict.abstain(
                f"no LLM provider wired (set ${ENV_JUDGE_CMD} to a `claude -p`-style "
                f"command) — abstaining, which routes this claim to a human."
            )
        return _parse_three_valued(reply)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dos.drivers.llm_judge",
        description=__doc__.splitlines()[0],
    )
    ap.add_argument("run_ts", help="the chained-run dir to adjudicate (e.g. 20260531T010000Z)")
    ap.add_argument("--workspace", default=None,
                    help="workspace root (default: $DISPATCH_WORKSPACE or cwd)")
    ap.add_argument("--job", action="store_true", help="use the job-repo taxonomy")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    args = ap.parse_args(argv)

    if args.job:
        _config.set_active(_config.job_config(args.workspace))
    else:
        _config.set_active(_config.default_config(args.workspace))

    verdict = adjudicate(args.run_ts)
    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2, default=str))
    else:
        print(f"RUN         {verdict.run_ts}")
        print(f"ENGINE      {verdict.engine}")
        print(f"CAUSE       {verdict.cause}")
        agree_s = (
            "-" if verdict.agrees_with_picker is None
            else ("agrees with picker" if verdict.agrees_with_picker
                  else "DISAGREES — likely picker bug")
        )
        print(f"VERDICT     {agree_s}")
        print(f"WHY         {verdict.rationale}")
        if verdict.evidence:
            print("EVIDENCE    " + "\n            ".join(verdict.evidence))
    # Exit code mirrors the kernel judge: 1 on a disagreement (a picker bug), else 0.
    return 1 if verdict.agrees_with_picker is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
