"""A faithful, NON-RIGGED EnterpriseOps-Gym episode simulator (docs/143 §8).

The point: prove the `dos.arg_provenance` advisory nudge (R1) lifts the **Integrity
(FK-validity) verifier slice** by >=4pp for a cheap agent, with the delta EMERGING from a
generative mint/recover dynamic — never hardcoded. The SAME `dos.arg_provenance.classify_call`
that ships in the kernel runs unmodified inside R1 here; the simulator gives it the same
inputs the real `dos_react` wrapper would (accumulated env-authored tool results + task
text), and never shows it (or the agent) the gold FK or the verifier.

Why a simulator AND a real run (see run_ab.py for the real path): the real benchmark needs
Docker MCP servers + a live LLM + ~$150 of API for the public split. The simulator is the
deterministic, seed-controlled, zero-cost proof that the *mechanism* works and that the
delta is mechanism-driven (it sweeps p_mint/q_recover/horizon and shows the bump is monotone
in catch-rate·q_recover and → 0 as either → 0). The real run measures the *magnitude* on a
10% sample. Both are reported; neither is rigged.

THE GENERATIVE MODEL (env-authored, the legitimacy line held)
=============================================================
Each task is a DAG of K in [k_min, k_max] steps (sampled to match the paper's avg ~9 / up
to 34 horizon and the monotonic horizon-decay). A step is either:
  * a READ — emits an env id token (a ServiceNow-shaped id: INC/CHG/sys_id/email/int PK)
    into the episode's env result-stream. These bytes are GYM-AUTHORED.
  * a MUTATE — a create/update with an FK arg that REFERENCES an id a prior read produced.
    Each mutate has a hidden GOLD FK = the correct prior-read id. A fraction of FK args are
    DERIVED (padded / prefixed / composite) from a prior env id — these exercise the
    livelock guard (a legit derived id the detector must NOT false-flag).

THE HONEST CHEAP-AGENT (the mint generator — the source of the delta)
=====================================================================
On each mutate the agent picks the FK value by a stochastic policy calibrated to a cheap
model:
  * with prob p_lookup it RESOLVED the id (issued the prereq read, passes the gold id).
  * with prob p_mint = 1 - p_lookup it MINTS — fabricates a right-shape / wrong-digits id
    WITHOUT the prereq read (the 'Missing Prerequisite Lookup' + 'Incorrect ID Resolution'
    modes). p_mint rises with FK-chain depth (deeper → more mints), matching horizon decay.
  * independently, at rate d it legitimately DERIVES an id from a real prior read — CORRECT,
    and the false-nudge exposure (the detector must pass these).

THE INTEGRITY (FK-VALIDITY) VERIFIER — env-authored, hidden
===========================================================
After the episode, the verifier checks each mutate's FK against the gold: a minted/wrong FK
= a dangling/invalid FK = Integrity FAIL for that task; a correctly resolved-or-derived FK
passes. The Integrity-slice pass rate = fraction of tasks with ALL FKs valid. This is the
env-authored final-state oracle — NOT the wrapper's predicate.

R0 vs R1 (the delta must emerge)
================================
R0: the agent runs free; minted FKs corrupt Integrity.
R1: before each mutate the wrapper runs `classify_call` over the REAL accumulated env
result-stream + task text. On UNSUPPORTED it injects ONE nudge; the agent gets a
SECOND CHANCE modeled honestly: with prob q_recover it now resolves the correct id
(FAIL→PASS — the source of the bump); with prob 1-q_recover it re-mints or gives up (still
FAILS). The nudge is bounded (<=1 per arg-value).

THE HONEST DOWNSIDE (must be modeled or it is rigged)
=====================================================
On a legit DERIVED id the detector might FALSE-FLAG → a wasted iteration; on a thrashing
agent near max_iterations this can convert a would-pass run into a TIMEOUT (a feasible-task
regression — the §8 kill-signal). The sim counts every false-UNSUPPORTED on a legit derived
id, charges an iteration, and fails the task with prob proportional to budget pressure.
Because the kernel's component decomposition + derived-id rungs drive the false-flag rate
toward ~0, R1 should show Integrity UP with feasible-task rate FLAT.

NB on calibration honesty: p_mint is tuned so R0's Integrity-slice lands in the paper's
measured cheap-model FK band (Table 7: Integrity 50-90 across domains; we target the
mid-band so the bump is read against a faithful floor, not a strawman). The bump is then a
function of the SIMULATED catch×recover loop, not a constant.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from dos.arg_provenance import (
    CorpusSource,
    EnvBlob,
    PriorResults,
    ProvenancePolicy,
    ToolArg,
    ToolCall,
    classify_call,
)


# ---------------------------------------------------------------------------
# Env-authored id minting — ServiceNow-shaped ids the gym would emit.
# ---------------------------------------------------------------------------
_ID_KINDS = ("inc", "chg", "task", "sysid", "email", "intpk")


def _env_id(rng: random.Random, kind: str) -> str:
    """An env-authored id of `kind`. These are the bytes a READ step emits — the agent did
    not author them."""
    if kind == "inc":
        return f"INC{rng.randint(0, 9999999):07d}"
    if kind == "chg":
        return f"CHG{rng.randint(0, 9999999):07d}"
    if kind == "task":
        return f"TASK{rng.randint(0, 999999):06d}"
    if kind == "sysid":
        return "".join(rng.choice("0123456789abcdef") for _ in range(32))
    if kind == "email":
        user = rng.choice(["jane", "bob", "alice", "carlos", "mei", "raj"])
        num = rng.randint(1, 999)
        org = rng.choice(["acme", "globex", "initech", "umbrella", "hooli"])
        return f"{user}_{num}@{org}.com"
    # intpk
    return str(rng.randint(1000, 99999))


def _mint_wrong(rng: random.Random, gold: str, kind: str) -> str:
    """A right-SHAPE, wrong-DIGITS id the cheap model invents without the prereq read.
    Same kind as the gold, different content — a dangling FK the Integrity verifier fails.
    Loops until it differs from gold (and, for safety, won't accidentally equal it)."""
    for _ in range(20):
        cand = _env_id(rng, kind)
        if cand != gold:
            return cand
    return gold + "X"  # pathological fallback


def _derive_legit(rng: random.Random, gold: str, kind: str) -> str:
    """A LEGIT derived id: the same identity as `gold`, re-expressed (padded / prefixed /
    re-cased / composite-from-parts). The Integrity verifier PASSES these (same identity);
    the detector must NOT false-flag them. This is the false-nudge exposure."""
    if kind in ("inc", "chg", "task"):
        # The gold already carries a prefix+digits; a derived form might drop a pad zero
        # or re-case the prefix — still the same record.
        prefix = "".join(c for c in gold if c.isalpha())
        digits = "".join(c for c in gold if c.isdigit())
        variant = rng.choice([
            gold.lower(),                          # re-cased
            prefix + digits.lstrip("0"),           # de-padded (INC10023 from INC0010023)
            gold,                                   # identity
        ])
        return variant
    if kind == "intpk":
        # zero-pad an int PK to a fixed width (a derived "0010023" from env int "10023")
        return gold.zfill(7)
    if kind == "email":
        return gold  # emails derived as-is
    return gold


# ---------------------------------------------------------------------------
# The episode model.
# ---------------------------------------------------------------------------
@dataclass
class Step:
    """One DAG step. A READ emits an env id; a MUTATE references a gold FK (the id a prior
    read produced)."""

    kind: str  # "read" | "mutate"
    id_kind: str  # the id flavor (inc/chg/sysid/email/intpk)
    gold: str = ""  # for a mutate: the correct FK; for a read: the id it emits
    fk_arg: str = "reference_id"  # the arg name carrying the FK on a mutate
    derived: bool = False  # for a mutate: is the CORRECT resolution a derived form?


@dataclass
class Task:
    feasible: bool
    steps: list[Step]
    task_text: str


@dataclass
class SimParams:
    """Calibrated to the paper. Defaults target a cheap-model Integrity floor in the
    Table-7 band (~60-65%) and a delta in the audit's §8 R1 pre-registered band (+2 to
    +6pp on the Integrity slice). Every default is a HONEST, conservative reading of the
    real benchmark — see each field — so the bump is read against a faithful floor."""

    k_min: int = 2
    k_max: int = 14            # horizon up to ~14 (paper: avg ~9, up to 34)
    p_mint_base: float = 0.06  # base mint prob at the shallowest FK (tuned: R0 Integ ~62%)
    p_mint_depth: float = 0.012  # added mint prob per FK-chain step (horizon decay)
    derive_rate: float = 0.30  # fraction of correct resolutions that are legit-derived
    # The HONEST detector-recall cap: a fraction of mints whose fabricated id COINCIDENTALLY
    # traces to the corpus (a substring of an unrelated env blob) — the false-SUPPORTED the
    # module docstring names as the safe-but-real miss. The detector cannot catch these, so
    # they stay failed in BOTH arms — this caps R1's reachable gain to well under 100% of
    # mints (no perfect-oracle strawman). 0.20 = a fifth of mints slip the detector.
    mint_coincidental_rate: float = 0.20
    # The modeled second-chance recovery: prob the nudge converts a CAUGHT mint into a
    # correct lookup. Mid of the audit's swept [0.3,0.7]. Below this the nudge is ignored.
    q_recover: float = 0.50
    max_iterations: int = 30
    fk_arg_names: tuple[str, ...] = ("reference_id", "parent", "caller_id", "assignment_group")


# ---------------------------------------------------------------------------
# Task generation — env-authored, never sees the agent.
# ---------------------------------------------------------------------------
def generate_task(rng: random.Random, params: SimParams, *, feasible: bool = True) -> Task:
    k = rng.randint(params.k_min, params.k_max)
    steps: list[Step] = []
    emitted: list[tuple[str, str]] = []  # (id_kind, id) pairs available to reference
    text_bits: list[str] = ["You are operating an enterprise system. Complete the task."]
    fk_depth = 0
    for _ in range(k):
        # Bias the first step(s) toward reads so a mutate has something to reference.
        want_read = (not emitted) or rng.random() < 0.45
        id_kind = rng.choice(_ID_KINDS)
        if want_read:
            idv = _env_id(rng, id_kind)
            steps.append(Step(kind="read", id_kind=id_kind, gold=idv))
            emitted.append((id_kind, idv))
            # Some emitted ids also appear in the task text (env-authored task-named ids).
            if rng.random() < 0.25:
                text_bits.append(f"Process record {idv}.")
        else:
            src_kind, gold = rng.choice(emitted)
            fk_arg = rng.choice(params.fk_arg_names)
            derived = rng.random() < params.derive_rate
            steps.append(Step(kind="mutate", id_kind=src_kind, gold=gold,
                              fk_arg=fk_arg, derived=derived))
            fk_depth += 1
    return Task(feasible=feasible, steps=steps, task_text="\n".join(text_bits))


# ---------------------------------------------------------------------------
# The cheap-agent policy + the R0/R1 episode runners.
# ---------------------------------------------------------------------------
def _p_mint(params: SimParams, depth: int) -> float:
    return min(0.95, params.p_mint_base + params.p_mint_depth * depth)


@dataclass
class EpisodeResult:
    integrity_pass: bool          # every FK valid (the Integrity slice)
    task_completion_pass: bool    # the agent reached the end without timeout
    timed_out: bool
    n_mutates: int
    n_minted: int
    n_nudged: int
    n_false_nudges: int           # nudges fired on a legit derived (correct) id
    n_recovered: int              # mints converted to correct by a nudge


def _agent_choose_fk(rng: random.Random, step: Step, params: SimParams, depth: int,
                     emitted_same_kind: list[str]):
    """The honest cheap-agent FK choice. Returns (value, is_correct, is_minted, is_derived).

    A correct choice may be the plain gold OR a legit-derived form; a mint is wrong-shape.
    A COINCIDENTAL mint (prob `mint_coincidental_rate`) grabs a DIFFERENT real id of the
    same kind that the agent already saw — wrong record (Integrity FAIL), but its bytes DO
    trace the corpus, so `classify_call` will (correctly, honestly) say SUPPORTED and not
    nudge. This is the real false-SUPPORTED the module names as the safe miss; it stays
    failed in BOTH arms, capping R1's reachable gain (no perfect-oracle strawman). The
    distinction is emergent from `classify_call`, not special-cased in the runner."""
    if rng.random() < _p_mint(params, depth):
        # a coincidental mint = grab a wrong-but-real prior id of the same kind, if any
        wrong_real = [v for v in emitted_same_kind if v != step.gold]
        if wrong_real and rng.random() < params.mint_coincidental_rate:
            return rng.choice(wrong_real), False, True, False
        return _mint_wrong(rng, step.gold, step.id_kind), False, True, False
    if step.derived:
        return _derive_legit(rng, step.gold, step.id_kind), True, False, True
    return step.gold, True, False, False


def run_episode_r0(rng: random.Random, task: Task, params: SimParams) -> EpisodeResult:
    """Baseline ReAct — no provenance gate."""
    all_fk_valid = True
    n_mut = n_min = 0
    depth = 0
    iters = 0
    emitted_by_kind: dict[str, list[str]] = {}
    for step in task.steps:
        iters += 1
        if iters > params.max_iterations:
            return EpisodeResult(False, False, True, n_mut, n_min, 0, 0, 0)
        if step.kind == "read":
            emitted_by_kind.setdefault(step.id_kind, []).append(step.gold)
            continue
        n_mut += 1
        depth += 1
        pool = emitted_by_kind.get(step.id_kind, [])
        _val, correct, minted, _derived = _agent_choose_fk(rng, step, params, depth, pool)
        if minted:
            n_min += 1
        if not correct:
            all_fk_valid = False
    return EpisodeResult(all_fk_valid, True, False, n_mut, n_min, 0, 0, 0)


def run_episode_r1(rng: random.Random, task: Task, params: SimParams,
                   policy: ProvenancePolicy) -> EpisodeResult:
    """dos_react — the advisory nudge, running the REAL `classify_call`.

    The wrapper accumulates env-authored bytes (read results + task text), and before each
    mutate folds `classify_call` over them. On UNSUPPORTED it nudges (<=1 per arg-value);
    the agent then gets a modeled second chance (q_recover). A false-nudge on a legit
    derived id costs an iteration and may time the task out (the honest downside)."""
    env_blobs: list[EnvBlob] = [EnvBlob(text=task.task_text, source=CorpusSource.TASK_TEXT)]
    all_fk_valid = True
    n_mut = n_min = n_nudged = n_false = n_rec = 0
    depth = 0
    iters = 0
    nudge_keys: set[str] = set()
    emitted_by_kind: dict[str, list[str]] = {}

    for step in task.steps:
        iters += 1
        if iters > params.max_iterations:
            return EpisodeResult(False, False, True, n_mut, n_min, n_nudged, n_false, n_rec)
        if step.kind == "read":
            # the env emits the id into the corpus (the agent observed it)
            emitted_by_kind.setdefault(step.id_kind, []).append(step.gold)
            env_blobs.append(EnvBlob(
                text=f'{{"id": "{step.gold}", "number": "{step.gold}"}}',
                source=CorpusSource.TOOL_RESULT,
            ))
            continue

        n_mut += 1
        depth += 1
        pool = emitted_by_kind.get(step.id_kind, [])
        val, correct, minted, derived = _agent_choose_fk(rng, step, params, depth, pool)
        if minted:
            n_min += 1

        # --- the REAL provenance consult (same code as the kernel ships) ---------
        call = ToolCall(
            tool_name="update_record",
            args=(ToolArg(name=step.fk_arg, value=val, is_reference=True),),
            is_mutating=True,
        )
        verdict = classify_call(call, PriorResults(blobs=tuple(env_blobs)), policy)

        if not verdict.believe and verdict.unsupported:
            key = step.fk_arg + "|" + str(val)
            if key not in nudge_keys:
                nudge_keys.add(key)
                n_nudged += 1
                iters += 1  # the nudge consumes a turn
                if iters > params.max_iterations:
                    return EpisodeResult(False, False, True, n_mut, n_min, n_nudged, n_false, n_rec)
                if not minted:
                    # FALSE-NUDGE on a legit (derived) id — the honest downside. The id was
                    # correct; the nudge wasted a turn. Under budget pressure, charge a
                    # timeout risk proportional to how deep we are.
                    n_false += 1
                    pressure = iters / params.max_iterations
                    if rng.random() < pressure * 0.5:
                        return EpisodeResult(False, False, True, n_mut, n_min, n_nudged, n_false, n_rec)
                    # else the model re-submits the same correct derived id; FK stays valid
                else:
                    # TRUE catch on a mint — the modeled second chance.
                    if rng.random() < params.q_recover:
                        # resolves the correct id now (issues the prereq read + correct FK)
                        correct = True
                        n_rec += 1
                        env_blobs.append(EnvBlob(
                            text=f'{{"id": "{step.gold}"}}', source=CorpusSource.TOOL_RESULT,
                        ))
                        val = step.gold
                    # else: re-mints / gives up → FK stays invalid

        if not correct:
            all_fk_valid = False

    return EpisodeResult(all_fk_valid, True, False, n_mut, n_min, n_nudged, n_false, n_rec)


# ---------------------------------------------------------------------------
# The A/B over a split.
# ---------------------------------------------------------------------------
@dataclass
class ArmStats:
    n_tasks: int = 0
    integrity_pass: int = 0       # tasks with all FKs valid (the Integrity slice)
    feasible_complete: int = 0    # feasible tasks the agent finished (no timeout)
    timeouts: int = 0
    n_mutates: int = 0
    n_minted: int = 0
    n_nudged: int = 0
    n_false_nudges: int = 0
    n_recovered: int = 0

    def add(self, r: EpisodeResult) -> None:
        self.n_tasks += 1
        if r.integrity_pass:
            self.integrity_pass += 1
        if not r.timed_out:
            self.feasible_complete += 1
        if r.timed_out:
            self.timeouts += 1
        self.n_mutates += r.n_mutates
        self.n_minted += r.n_minted
        self.n_nudged += r.n_nudged
        self.n_false_nudges += r.n_false_nudges
        self.n_recovered += r.n_recovered

    @property
    def integrity_rate(self) -> float:
        return 100.0 * self.integrity_pass / self.n_tasks if self.n_tasks else 0.0

    @property
    def feasible_rate(self) -> float:
        return 100.0 * self.feasible_complete / self.n_tasks if self.n_tasks else 0.0


def run_split(seed: int, n_tasks: int, params: SimParams,
              policy: Optional[ProvenancePolicy] = None) -> tuple[ArmStats, ArmStats]:
    """Run the SAME n_tasks (same seeds → same tasks AND same agent random draws) through
    R0 and R1. Returns (r0, r1). The agent's stochastic draws are seeded per-task identically
    for both arms so the ONLY difference is the nudge — a true paired A/B."""
    policy = policy or ProvenancePolicy()
    r0, r1 = ArmStats(), ArmStats()
    gen = random.Random(seed)
    for i in range(n_tasks):
        task = generate_task(gen, params, feasible=True)
        # identical agent randomness for both arms (paired): same per-task seed.
        agent_seed = gen.randint(0, 2**31)
        r0.add(run_episode_r0(random.Random(agent_seed), task, params))
        r1.add(run_episode_r1(random.Random(agent_seed), task, params, policy))
    return r0, r1
