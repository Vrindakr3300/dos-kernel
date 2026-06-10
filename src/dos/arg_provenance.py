"""ARG — the argument-provenance verdict: *did the model MINT this id, or RESOLVE it?*

docs/143 §5a/§7 (the EnterpriseOps-Gym audit) — the **survivor** binding. Of every
gate the audit floated for a cheap agent on a stateful enterprise benchmark, exactly
one passes DOS's own byte-inequality axiom (docs/141) cleanly: a check of
**provenance-of-a-string**. Before a mutating tool call fires, ask of each id/FK-shaped
argument:

  > did this value APPEAR in env-authored bytes the agent already saw (a prior tool
  > RESULT, or the task text), or did the model MINT it from nowhere?

That is a clean **byte-author** question — the gym MCP server authored the read-result
bytes; the judged agent did not — so it sidesteps the **mirror-verifier trap** (docs/141,
docs/143 §5a) entirely: it needs no answer key, no held-out final state, and **no
self-authored satisfaction predicate** ("is this the row the task *required*?" — the
forgeable-in-the-agent's-favor question this module must never ask). It attacks two
*named* benchmark failure modes (docs/143 §1b) that feed the Integrity (FK-validity)
verifier:

  * **Incorrect ID Resolution** — passing unverified IDs minted by the model instead of
    resolving the correct IDs through prior tool interactions.
  * **Missing Prerequisite Lookup** — creating an object without first querying the
    prereqs, so the FK it references was never read.

Why this is the kernel's to own, and where the line is
======================================================

`believe=True` here means **only** "no id arg was minted from nowhere" — it is NEVER a
claim that the args are *correct* (that would be a satisfaction predicate, the trap).
The structural guarantee that this module cannot launder a self-authored predicate is in
the type: the provenance corpus (`PriorResults`) is a tuple of `EnvBlob`, and an
`EnvBlob` can carry only an **env** `CorpusSource` (`TOOL_RESULT` / `TASK_TEXT`). There
is deliberately **no `AGENT_AUTHORED` member** — a boundary that tried to fold an
assistant turn into the corpus has no enum to tag it with, so model-authored bytes are
*unrepresentable* as evidence. That is the docs/143 §5a discipline made structural, the
same shape `evidence.believe_under_floor` uses (a forgeable-floor source can never grant
belief) — here pushed one step further: the forgeable class does not exist in the type.

The verdict is **advisory**: it REPORTS; it never raises, never dispatches, never mutates.
The consumer (a `dos_react`-style orchestrator wrapper, benchmark-side — NOT in the
kernel) reads `unsupported` and injects ONE nudge ToolMessage ("resolve `<value>` via a
read tool first") instead of dispatching the mutating call, pushing the cheap model to do
the prerequisite lookup it skipped. The verdict's only power is to nudge-MORE; it has no
output that can force a call through — **refuse-MORE-only by the shape of the type**, the
admission-seam / fail-to-abstain discipline re-aimed at the argument grain. The
per-arg-value re-injection cap (≤1, docs/143 §4) lives in the consumer; the pure verdict
cannot loop.

The two errors, and which one is safe
=====================================

Only two error directions are reachable, and the design biases hard toward the safe one:

  * **false-SUPPORTED** (a minted id coincidentally substrings the corpus) → the verdict
    declines to nudge → R1 degrades to the baseline for that call. SAFE — no worse than
    not having the gate.
  * **false-UNSUPPORTED** (a *legit derived* id — padded `INC0010023` from a bare env
    `10023`, a composite `user_42@acme.com` from env parts — wrongly flagged) → an
    unnecessary nudge wastes an iteration and, on a thrashing agent near its cap, can
    convert a would-pass run into a timeout (the docs/143 §8 feasible-task **kill-signal**).
    DANGEROUS. The component decomposition (Step D) + the derived-id containment rungs
    (Step E reverse-substring + numeric-pad-normalize) drive this rate toward ~0, which is
    what lets R1 clear its gate (Integrity UP, feasible-task rate FLAT).

So the whole module is tuned to **under-fire**: a missed mint is a silent safe ABSTAIN; a
false flag risks a real regression. Every ambiguous case resolves to ABSTAIN.

⚓ Pure kernel, I/O on the edge (the dos idiom — mirrors `liveness.classify`,
`churn.decide_coalesce`, `evidence.believe_under_floor`): `classify_call(ToolCall,
PriorResults, policy) -> ProvenanceVerdict` is a frozen dataclass in, a frozen verdict
out. The caller (the wrapper, at the benchmark boundary) flattens each prior tool RESULT
to a string and tags it with its env source BEFORE the call; the kernel never parses
JSON, never reads a file, never calls a clock. That is what lets the whole verdict be
unit-tested on frozen fixtures with zero benchmark/LLM/MCP access — the keystone the audit
calls "testable with zero benchmark access."
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# The closed source vocabulary — the structural non-self-authorship guarantee.
# ---------------------------------------------------------------------------
class CorpusSource(str, enum.Enum):
    """Where an `EnvBlob`'s bytes came from — and CRUCIALLY, *only env classes exist*.

    Mirrors `evidence.Accountability` in spirit (who authored the bytes) but is local
    and **closed to env-authored classes by construction**: there is deliberately no
    `AGENT_AUTHORED` member. The provenance corpus is built only of `EnvBlob`s, and an
    `EnvBlob` can be tagged with nothing but these two — so a boundary that tried to fold
    a model turn into the corpus has *no enum value to use* and the bytes cannot enter.
    The mirror-verifier trap (docs/143 §5a — grading the agent against bytes the agent
    authored) is thereby made **unrepresentable in the type**, not merely discouraged.

    `str`-valued so it round-trips a CLI token / JSON without a lookup table (the
    `Accountability` / `Liveness` idiom).

      TOOL_RESULT — bytes the gym MCP server authored: a prior read/tool RESULT the agent
                    observed but did not write. The primary provenance source.
      TASK_TEXT   — bytes the gym authored in the task prompt / policy doc. An id the task
                    itself names is env-authored (docs/143 §4 P1 flags task-text ids as a
                    needed first-class source, so a task-named id is never false-flagged).
    """

    TOOL_RESULT = "TOOL_RESULT"
    TASK_TEXT = "TASK_TEXT"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ProvenanceStance(str, enum.Enum):
    """The per-arg verdict — three-valued, the `EvidenceStance` analogue.

    `str`-valued so it round-trips a token / JSON / exit code without a lookup table.

      SUPPORTED   — id-shaped, a reference on a mutating call, AND every data-bearing
                    component traced to env-authored bytes. The "believe" rung.
      UNSUPPORTED — id-shaped, a reference on a mutating call, the corpus was non-empty,
                    AND ≥1 data-bearing component appears NOWHERE in env bytes → looks
                    model-minted. The ONLY stance that drives a nudge.
      ABSTAIN     — the fail-safe zero: not id-shaped, OR a read/non-mutating call, OR a
                    new-key (the create's own minted identity), OR the corpus is empty
                    (first call — we cannot prove mintage with zero env bytes, so we never
                    accuse). Honest no-signal; never a block.
    """

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    ABSTAIN = "ABSTAIN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ---------------------------------------------------------------------------
# Frozen inputs — the pure datum a caller gathers at the boundary and hands in.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EnvBlob:
    """One env-authored chunk of the provenance corpus — bytes the agent did NOT write.

    `text` is one prior tool RESULT (or the task text) already flattened to a string at
    the boundary (the wrapper does `json.dumps(result)` / `str(...)`; the kernel never
    parses JSON). `source` is the load-bearing field: it can ONLY be an env
    `CorpusSource`, so an `EnvBlob` is by construction not forgeable-floor evidence.
    """

    text: str
    source: CorpusSource


@dataclass(frozen=True)
class PriorResults:
    """The whole env-authored corpus accumulated before the call under scrutiny.

    `blobs` is a tuple of `EnvBlob` — every prior tool RESULT plus the task text, each
    tagged with its env source. Empty (`()`) on the very first call of an episode, which
    `classify_call` reads as "cannot prove mintage → ABSTAIN-all" (the load-bearing
    first-call safe direction). The blobs are kept WHOLE (not pre-tokenized) so an id
    embedded mid-prose ("close incident INC0010023 today") is still found by containment.
    """

    blobs: tuple[EnvBlob, ...] = ()


@dataclass(frozen=True)
class ToolArg:
    """One argument of the tool call, as the pure datum a provenance check sees.

    `value` is the raw value the model emitted (str | int | float | bool | None | list |
    dict); the fold provenance-checks scalars and recurses into list/dict. `is_reference`
    is the create's-own-key guard: the wrapper sets it False for the slot that holds the
    NEW object's OWN identity/primary key (resolved from the tool schema) — a brand-new
    minted natural key (a new email, a new title-slug) is minted-AND-correct and must
    never be nudged ("you cannot resolve an id you are inventing"). Defaults True (the
    common case: most args reference existing rows), so an un-annotating caller gets the
    gating behavior; the create's-own-key exemption is opt-in at the boundary.
    """

    name: str
    value: object
    is_reference: bool = True


@dataclass(frozen=True)
class ToolCall:
    """The tool call under scrutiny — the `AdmissionRequest` analogue.

    `is_mutating` is set by the wrapper from the tool schema (write-verb classifier). A
    read/non-mutating call is never gated — reads are how provenance ENTERS the corpus —
    so `is_mutating=False` short-circuits the whole fold to ABSTAIN-all. The wrapper's
    write-verb classifier is deliberately **fail-open** (when unsure, treat as a read):
    under-gating is the feasible-task-safe direction here, the explicit inversion of the
    kernel's usual fail-closed posture, because a false gate risks a real regression while
    a missed gate just degrades to baseline.
    """

    tool_name: str
    args: tuple[ToolArg, ...]
    is_mutating: bool = True


@dataclass(frozen=True)
class ProvenancePolicy:
    """The thresholds — mechanism is kernel, knobs are config (the `LivenessPolicy` seam).

    Defaults GENERIC; a host may declare its own in `dos.toml [arg_provenance]` read back
    through `SubstrateConfig` (the closed-config-as-data pattern).

      min_component_len — a component shorter than this is dropped from the must-trace set
                          (too collision-prone to demand OR to substring-match): a bare
                          "P1" / "42" / "US" standalone is not provenance-checkable. There
                          is deliberately NO fractional-support knob: the only honest rule
                          is "every data-bearing component traces" (a sub-1.0 leniency
                          would be a laundering leak — a mostly-minted id passing).
      case_sensitive    — casefold both sides by default. ServiceNow ids (INC0010023) are
                          case-stable, but DB echoes / emails / usernames vary; casefold
                          avoids a false-UNSUPPORTED on a re-cased legit id (fewest-false-
                          blocks bias).
    """

    min_component_len: int = 4
    case_sensitive: bool = False

    def __post_init__(self) -> None:
        if self.min_component_len < 1:
            raise ValueError("min_component_len must be >= 1")


DEFAULT_POLICY = ProvenancePolicy()


# ---------------------------------------------------------------------------
# Frozen verdicts — the folded answer, advisory only.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ArgProvenance:
    """One argument's provenance sub-verdict (legible distrust — the per-arg detail).

    `matched_in` names which env source(s) carried the traced components (the rung made
    visible). `components_unmatched` names the precise minted sub-ids — the minimal,
    exact target the nudge speaks ("resolve <those parts> via a read first"), so a nudge
    is never a vague "resolve your id."
    """

    arg_name: str
    value_repr: str
    stance: ProvenanceStance
    id_shaped: bool
    is_reference: bool
    matched_in: tuple[CorpusSource, ...]
    components_checked: tuple[str, ...]
    components_unmatched: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            "arg_name": self.arg_name,
            "value_repr": self.value_repr,
            "stance": self.stance.value,
            "id_shaped": self.id_shaped,
            "is_reference": self.is_reference,
            "matched_in": [s.value for s in self.matched_in],
            "components_checked": list(self.components_checked),
            "components_unmatched": list(self.components_unmatched),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProvenanceVerdict:
    """The folded top-level answer over a tool call — the `LivenessVerdict` analogue.

    `believe` is True iff NO arg is UNSUPPORTED — i.e. every id-shaped reference arg either
    traced to env bytes or the call had none to check. It means ONLY "no id was minted from
    nowhere," NEVER "the args are correct" (no satisfaction claim — the trap). `unsupported`
    is the arg names the nudge targets (empty ⟺ believe). `args` carries every per-arg
    sub-verdict (including abstained ones) for legibility. Advisory: never raises, never
    dispatches — the consumer reads `unsupported` and decides whether to nudge.
    """

    believe: bool
    args: tuple[ArgProvenance, ...]
    unsupported: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            "believe": self.believe,
            "args": [a.to_dict() for a in self.args],
            "unsupported": list(self.unsupported),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Detection + matching — pure, decidable from the corpus alone, no answer key.
# ---------------------------------------------------------------------------

# Step B negative filters — a value matching any of these is a quantity/literal, NOT an
# FK, so it is rejected as not-id-shaped BEFORE any positive test (the date/money/version/
# phone false-block killer). Anchored full-string. The datetime forms are real-data-
# hardened (docs/143 live run): a full ISO-8601 timestamp `2025-08-23T00:00:00Z` was being
# mis-split into id components (`23T00`, `59`), so the filter matches the whole stamp with
# its `T`/`:`/`Z`/offset, not just a bare `YYYY-MM-DD`.
_RE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)
_RE_TIME = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_RE_DECIMAL = re.compile(r"^\d+\.\d+$")
_RE_VERSION = re.compile(r"^v?\d+(\.\d+)+$")
# Phone-ish: must carry a phone SEPARATOR (a '-'/'+'/'('/space) — a BARE integer is NOT
# phone-ish (it is a numeric PK / FK). The old `^[\d\-+()\s]+$` matched every pure-digit
# string, wrongly negative-filtering numeric ids like `1179` (docs/143 real-data fix).
_RE_PHONEISH = re.compile(r"^[\d()][\d\-+()\s]*[\-+()\s][\d\-+()\s]*\d$")
_RE_EPOCH_MS = re.compile(r"^\d{13}$")  # a 13-digit ms-epoch timestamp (a quantity, not an FK)
_LITERAL_WORDS = frozenset({"true", "false", "null", "none"})

# Step C positive signatures.
_RE_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_RE_UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_HAS_DIGIT = re.compile(r"\d")
_RE_HAS_ALPHA = re.compile(r"[A-Za-z]")
# The character class an id-shaped mixed-alnum token may contain (no internal whitespace).
_RE_ID_CHARS = re.compile(r"^[A-Za-z0-9._:#/\-@]+$")
_RE_DIGIT_RUN = re.compile(r"\d+")

# The delimiter class a composite id splits on (Step D).
_DELIM_RE = re.compile(r"[@._:#/\-]")
# The tokenizer for the env corpus (Step E exact-match): id-delimiters + whitespace + the
# JSON/structural punctuation that wraps env values (braces, brackets, quotes, commas,
# parens, equals, semicolons). Without stripping these, a JSON value `10023` tokenizes as
# `10023}` and an exact/pad match misses — so the env corpus must be punctuation-clean.
_ENV_TOKEN_RE = re.compile(r"[@._:#/\-\s{}\[\]\"',()=;<>|]+")
# A "clean" id part: an optional alpha prefix then a trailing digit run (INC0010023,
# acme99, p0001) — the part whose DATA unit is just the digit run. Anything else that is
# alnum (hex, interleaved) is demanded WHOLE so we never demand a meaningless 1-char run.
_RE_PREFIX_THEN_DIGITS = re.compile(r"^[A-Za-z]*\d+$")

# Name-hint suffixes (Step C corroboration). Suffix-anchored, NOT substring — so
# `phone_number` / `version_number` / `due_to_date` are NOT hints (their substrings
# `_number`/`_to`/`_date` are excluded by anchoring to these exact tails).
_NAME_HINT_SUFFIXES = ("_id", "_sys_id", "sys_id", "_ref", "_key", "_email")

# Quantity-name stoplist (docs/143 real-data fix): an arg whose name signals a NUMBER, not
# an FK — a price, an amount, a count. A bare pure-digit value in such a slot is the model
# legitimately SETTING a quantity (contract_price=33414), never an id to resolve, so it must
# never be treated as id-shaped (it caused live false-flags). Matched as a name SUFFIX /
# whole-word so `unit_price`/`total_amount`/`max_results` hit but an `*_id` never does.
_QUANTITY_NAME_PARTS = (
    "price", "amount", "cost", "total", "count", "quantity", "qty", "size", "limit",
    "number", "num", "age", "duration", "score", "rate", "percent", "weight", "height",
    "width", "length", "balance", "fee", "rank", "position", "offset", "page", "max",
    "min", "priority", "level", "year", "month", "day", "hour", "minute", "second",
)


def _name_is_quantity(arg_name: str) -> bool:
    """True iff the arg NAME signals a quantity (price/amount/count/…), so a bare number in
    it is a value the model sets, not an FK to resolve. Matched on the trailing token of a
    snake/camel name so `unit_price`/`maxResults` hit while an `account_id` never does."""
    n = arg_name.casefold()
    last = n.replace("-", "_").split("_")[-1]
    return last in _QUANTITY_NAME_PARTS or any(n.endswith(q) for q in _QUANTITY_NAME_PARTS)

# Grammar stoplist (Step D) — pure-alpha composite parts that are domain GRAMMAR, not the
# data-bearing identifier portion: common TLDs + a few connective/scheme words the model
# may legitimately type. A pure-alpha part in this set is exempt from must-trace even when
# it is long enough to otherwise be demanded; a pure-alpha part NOT in this set and long
# enough (e.g. the org-name in user_42@acme.com / @evil.com) IS demanded, so a minted
# domain is caught while a real one traces. Kept deliberately small — over-listing turns a
# minted identifier word into exempt grammar (a laundering leak), under-listing risks a
# false-block on an exotic TLD (the safe direction: a false-block degrades, see module doc).
_GRAMMAR_WORDS = frozenset({
    "com", "org", "net", "edu", "gov", "mil", "int", "io", "co", "us", "uk", "ca", "au",
    "www", "http", "https", "mailto", "ftp", "api", "mail", "smtp", "imap",
})


def _casefold(s: str, policy: ProvenancePolicy) -> str:
    return s if policy.case_sensitive else s.casefold()


def _is_negative_filtered(s: str) -> bool:
    """Step B — True iff `s` is a quantity/literal (date/time/decimal/version/phone/bool),
    NOT an FK. Such a value is never id-shaped."""
    if _RE_ISO_DATE.match(s) or _RE_ISO_DATETIME.match(s) or _RE_TIME.match(s):
        return True
    if _RE_DECIMAL.match(s) or _RE_VERSION.match(s) or _RE_PHONEISH.match(s):
        return True
    if _RE_EPOCH_MS.match(s):
        return True
    if s.casefold() in _LITERAL_WORDS:
        return True
    # Pure prose: internal whitespace AND no embedded digit AND not email-shaped → free
    # text (a short_description), never an id.
    if " " in s and not _RE_HAS_DIGIT.search(s) and not _RE_EMAIL.match(s):
        return True
    return False


def _name_is_hint(arg_name: str) -> bool:
    """True iff the arg NAME suffix-matches an id-bearing slot name. Corroborating only —
    never promotes a Step-B-rejected value, and requires a positive value signature too."""
    n = arg_name.casefold()
    return any(n.endswith(suf) for suf in _NAME_HINT_SUFFIXES)


def _is_id_shaped(s: str, arg_name: str, policy: ProvenancePolicy) -> bool:
    """Step C — True iff `s` carries a POSITIVE id signature. Biased to under-fire: a
    missed id is a silent safe ABSTAIN; a false flag risks a false-block."""
    # Real-data recall lift (docs/143): a BARE SHORT INTEGER in a strong FK-name slot
    # (`group_id`, `caller_id`, `*_ref`) is the ServiceNow numeric-PK pattern (group_id=81).
    # The default min_component_len drops it, costing recall on the dominant
    # 'Incorrect ID Resolution' shape. Promote it to id-shaped down to len 2 — but ONLY
    # when the NAME corroborates (a bare number in a non-FK slot stays a quantity). The
    # int-equality matcher handles its collision risk, and the name-hint keeps precision
    # intact (a `limit`/`priority`/`page` value never reaches here). It must still survive
    # Step B (so a 13-digit epoch / a decimal is excluded before this).
    if (
        s.isdigit() and 2 <= len(s) < policy.min_component_len
        and _name_is_hint(arg_name) and not _name_is_quantity(arg_name)
        and not _is_negative_filtered(s)
    ):
        return True
    if len(s) < policy.min_component_len:
        return False
    if _is_negative_filtered(s):
        return False
    if " " in s:
        # An id token has no internal whitespace (email/prose handled above).
        return False
    if not _RE_ID_CHARS.match(s):
        return False
    # (iii) hex32 / UUID, (iv) email.
    if _RE_HEX32.match(s) or _RE_UUID.match(s) or _RE_EMAIL.match(s):
        return True
    # (i) mixed alnum.
    if _RE_HAS_DIGIT.search(s) and _RE_HAS_ALPHA.search(s):
        return True
    # (ii) pure-digit key of sufficient length (survived Step B, so not a date/decimal) —
    # UNLESS the name signals a quantity (price/amount/count), where a bare number is a value
    # the model sets, not an FK to resolve (the docs/143 contract_price=33414 false-flag).
    if s.isdigit() and len(s) >= policy.min_component_len and not _name_is_quantity(arg_name):
        return True
    # Name-hint corroboration: a long opaque pure-alpha token (no digit, no delimiter)
    # in an *_id/_ref/_key slot is an opaque key. Never fires on a short or Step-B value.
    if _name_is_hint(arg_name) and len(s) >= policy.min_component_len and s.isalnum():
        return True
    return False


def _data_bearing_components(s: str, policy: ProvenancePolicy) -> tuple[tuple[str, ...], bool]:
    """Step D — split `s` into components and return the DATA-BEARING ones (those that
    must trace) plus whether the value is genuinely id-shaped after decomposition.

    A component is:
      * DATA-BEARING (must trace) — a DIGIT-RUN anywhere (e.g. "INC0010023" → "0010023";
        the prefix is grammar), a high-entropy interleaved alnum token kept WHOLE (a hex/
        UUID chunk), OR a long non-grammar pure-alpha label in the DOMAIN position (the
        org label after an "@": the "acme"/"evil" in user_42@<x>.com — a minted domain
        must be caught, a real one resolves).
      * GRAMMAR (exempt) — a pure-alpha part OUTSIDE the domain position (the "INC" prefix,
        a "user"/"jane"/"doe" type-word or name, an enum word), and any TLD/scheme word in
        the stoplist. Domain grammar the model may legitimately supply; NOT demanded. This
        asymmetry — alpha-in-domain-position is data, alpha-elsewhere is grammar — is what
        lets the local-part "user" stay exempt (no false-block on the supported composite)
        while the org label is still checked.
      * DROPPED — a part shorter than min_component_len (a "US", a "v"): too collision-prone
        to demand or to match.

    The ENUM GUARD: if after decomposition there are ZERO data-bearing components (every
    part is grammar or dropped — "itil_admin", "in_progress"), the value is NOT genuinely
    id-shaped → the caller ABSTAINs. A role/status/enum token never nudges.

    REAL-DATA HARDENING (docs/143 live run, the §8 false-block kill-signal made concrete):
      * a UUID / 32-hex value is demanded WHOLE (one component), never split on its `-`
        delimiters — splitting `3fc71c6d-bfa1-4339-b089-…` demanded sub-chunks like `1`/`089`
        that don't independently trace, a guaranteed false-flag on a legit label id.
      * a digit-run in an EMAIL LOCAL part (`jason.smith10@…` → `10`) is a username
        discriminator, NOT a resolvable FK — it is grammar, never demanded. Only a digit-run
        long enough to be a real id (>= min_component_len) is demanded from a local-part token.
    """
    # A UUID or 32-hex value is ONE opaque identity — demand it whole, never split. (Step C
    # already accepted it as id-shaped; splitting it on '-' is the documented false-flag.)
    if _RE_UUID.match(s) or _RE_HEX32.match(s):
        return (s,), True

    # Split into the local region (before the first "@") and the domain region (after it).
    # A pure-alpha label is grammar in the local region, data-bearing in the domain region.
    at = s.find("@")
    local_s, domain_s = (s, "") if at < 0 else (s[:at], s[at + 1:])
    is_email = at >= 0
    local_parts = [p for p in _DELIM_RE.split(local_s) if p]
    domain_parts = [p for p in _DELIM_RE.split(domain_s) if p]
    demanded: list[str] = []
    for part, in_domain in (
        [(p, False) for p in local_parts] + [(p, True) for p in domain_parts]
    ):
        if not _RE_HAS_DIGIT.search(part):
            # Pure-alpha part. In the LOCAL region it is grammar (exempt) — the "INC"/"user"
            # type-word, a name. In the DOMAIN region a long, non-grammar label is the org
            # identity and IS data-bearing (a minted domain is caught while a real one
            # resolves); a stoplist TLD/scheme word stays grammar everywhere.
            if (
                in_domain
                and len(part) >= policy.min_component_len
                and part.casefold() not in _GRAMMAR_WORDS
            ):
                demanded.append(part)
            continue
        if _RE_PREFIX_THEN_DIGITS.match(part):
            # A clean alpha-prefix + trailing digit run (INC0010023, acme99, p0001): the
            # DATA unit is just the digit run (the prefix is grammar). One digit run — BUT in
            # an email LOCAL part the digit suffix is a username discriminator (smith10), not
            # an FK, so only demand it if it is long enough to be a real id.
            run = _RE_DIGIT_RUN.findall(part)
            if run:
                d = run[-1]
                if is_email and not in_domain and len(d) < policy.min_component_len:
                    continue  # username discriminator — grammar, not a resolvable FK
                demanded.append(d)
        else:
            # A high-entropy interleaved alnum token (hex/UUID chunk, a1b2c3…): demand the
            # WHOLE chunk as one unit. Demanding its individual 1-char digit runs would be
            # both meaningless (a "1" matches everything) and a false-block risk, so the
            # opaque token traces or it doesn't, atomically.
            demanded.append(part)
    # Dedup; drop any demanded component shorter than min_component_len UNLESS it is a
    # pure-digit run (a short numeric PK is real data — int-equality matching handles its
    # collision risk; a short non-digit chunk is too collision-prone to demand or match).
    seen: set[str] = set()
    out: list[str] = []
    for c in demanded:
        if len(c) < policy.min_component_len and not c.isdigit():
            continue
        if c not in seen:
            seen.add(c)
            out.append(c)
    return tuple(out), bool(out)


def _component_found(component: str, env_text: str, env_tokens: frozenset[str],
                     policy: ProvenancePolicy) -> bool:
    """Step E — True iff `component` traces to the env corpus. Several rungs, any one:

      (a) exact: equals an env token.
      (b) substring: is a substring of the joined env text (len-guarded).
      (c) reverse-substring: an env token (len-guarded) is a substring of the component
          — covers the model DERIVING a padded/prefixed id from a bare env fragment.
      (d) numeric-pad normalize: for a pure-digit component, compare zero-stripped /
          int-value forms against env digit tokens — the most common ServiceNow livelock
          ("0010023" derived from env bare int "10023" and vice versa).
    """
    c = _casefold(component, policy)
    # (a) exact token.
    if c in env_tokens:
        return True
    # (d) numeric-pad normalize (do before substring so int-equality is authoritative).
    if c.isdigit():
        c_int = c.lstrip("0") or "0"
        for tok in env_tokens:
            if tok.isdigit() and (tok.lstrip("0") or "0") == c_int:
                return True
    # (b) substring in the joined env text.
    if len(c) >= policy.min_component_len and c in env_text:
        return True
    # (c) reverse-substring: a sufficiently long env token sits inside the component.
    if len(c) >= policy.min_component_len:
        for tok in env_tokens:
            if len(tok) >= policy.min_component_len and tok in c:
                return True
        # numeric reverse: an env digit token's int form inside the component's digits.
        if c.isdigit():
            for tok in env_tokens:
                if tok.isdigit() and len(tok) >= policy.min_component_len:
                    stripped = tok.lstrip("0") or "0"
                    if stripped in c:
                        return True
    return False


def _flatten_leaves(value: object) -> list[object]:
    """Recurse a list/dict arg value to its scalar leaves (Step A.3). Each leaf is
    provenance-checked independently; the arg folds to UNSUPPORTED if ANY id-leaf is
    minted, SUPPORTED if all id-leaves trace, ABSTAIN if no leaf is id-shaped."""
    out: list[object] = []
    if isinstance(value, dict):
        for v in value.values():
            out.extend(_flatten_leaves(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_flatten_leaves(v))
    else:
        out.append(value)
    return out


def _build_env(prior: PriorResults, policy: ProvenancePolicy) -> tuple[str, dict[str, set[CorpusSource]]]:
    """Boundary-free corpus prep: the joined casefolded env text + a token→sources map.

    Returns (joined_text, token_sources) where token_sources maps each env token to the
    set of `CorpusSource`s that supplied it (for `matched_in`). Computed once per call.
    """
    texts: list[str] = []
    token_sources: dict[str, set[CorpusSource]] = {}
    for blob in prior.blobs:
        t = _casefold(blob.text, policy)
        texts.append(t)
        for tok in _ENV_TOKEN_RE.split(t):
            if tok:
                token_sources.setdefault(tok, set()).add(blob.source)
    return " ".join(texts), token_sources


def classify_arg(arg: ToolArg, prior: PriorResults,
                 policy: ProvenancePolicy = DEFAULT_POLICY) -> ArgProvenance:
    """Per-arg leaf — SUPPORTED / UNSUPPORTED / ABSTAIN for ONE argument. PURE.

    Recurses into list/dict values (fold: any id-leaf UNSUPPORTED → UNSUPPORTED; all
    id-leaves traced → SUPPORTED; no id-leaf → ABSTAIN). Assumes the call-level guards
    (read call, empty corpus) were applied by `classify_call`; a direct caller passing a
    non-empty `prior` gets the full check.
    """
    name = arg.name
    # Step A.1 — the create's-own-key exemption.
    if not arg.is_reference:
        return ArgProvenance(
            arg_name=name, value_repr=str(arg.value), stance=ProvenanceStance.ABSTAIN,
            id_shaped=False, is_reference=False, matched_in=(), components_checked=(),
            components_unmatched=(),
            reason="new-key / own-identity slot — not a reference to resolve",
        )

    # Step A.3 — recurse composite container values.
    if isinstance(arg.value, (list, tuple, dict)):
        leaves = _flatten_leaves(arg.value)
        any_id = False
        unmatched_all: list[str] = []
        matched_sources: set[CorpusSource] = set()
        checked_all: list[str] = []
        any_unsupported = False
        for leaf in leaves:
            sub = classify_arg(ToolArg(name=name, value=leaf, is_reference=True), prior, policy)
            checked_all.extend(sub.components_checked)
            if sub.id_shaped:
                any_id = True
            matched_sources.update(sub.matched_in)
            if sub.stance is ProvenanceStance.UNSUPPORTED:
                any_unsupported = True
                unmatched_all.extend(sub.components_unmatched)
        if not any_id:
            return ArgProvenance(
                arg_name=name, value_repr=str(arg.value), stance=ProvenanceStance.ABSTAIN,
                id_shaped=False, is_reference=True, matched_in=(), components_checked=(),
                components_unmatched=(),
                reason="container arg with no id-shaped leaf — nothing to provenance-check",
            )
        if any_unsupported:
            return ArgProvenance(
                arg_name=name, value_repr=str(arg.value), stance=ProvenanceStance.UNSUPPORTED,
                id_shaped=True, is_reference=True, matched_in=tuple(sorted(matched_sources, key=lambda s: s.value)),
                components_checked=tuple(checked_all), components_unmatched=tuple(unmatched_all),
                reason="at least one id in the container did not appear in env-authored bytes",
            )
        return ArgProvenance(
            arg_name=name, value_repr=str(arg.value), stance=ProvenanceStance.SUPPORTED,
            id_shaped=True, is_reference=True, matched_in=tuple(sorted(matched_sources, key=lambda s: s.value)),
            components_checked=tuple(checked_all), components_unmatched=(),
            reason="every id in the container traced to env-authored bytes",
        )

    # Step A.2 — None / bool are never ids.
    if arg.value is None or isinstance(arg.value, bool):
        return ArgProvenance(
            arg_name=name, value_repr=str(arg.value), stance=ProvenanceStance.ABSTAIN,
            id_shaped=False, is_reference=True, matched_in=(), components_checked=(),
            components_unmatched=(), reason="flag/None value — never an id",
        )

    s = str(arg.value).strip()
    if not _is_id_shaped(s, name, policy):
        return ArgProvenance(
            arg_name=name, value_repr=s, stance=ProvenanceStance.ABSTAIN,
            id_shaped=False, is_reference=True, matched_in=(), components_checked=(),
            components_unmatched=(), reason="not id/FK-shaped — quantity, literal, or prose",
        )

    env_text, token_sources = _build_env(prior, policy)
    env_tokens = frozenset(token_sources)

    # WHOLE-VALUE DIRECT MATCH (the primary rung — docs/143 live run). The overwhelmingly
    # common honest case is the model passing an id it read back VERBATIM (`INC_004`,
    # `msg_001`, a UUID). If the entire value appears in the env corpus — as an exact token
    # OR a substring of the joined text — it is RESOLVED, full stop. We answer here BEFORE
    # decomposing, because decomposition is a heuristic for *derived/composite* ids and on a
    # verbatim id it can demand a too-short sub-run (`004`) that the matcher then misses,
    # a guaranteed false-flag. Direct containment needs no hashing or fuzzy match — the id
    # is the same bytes the env authored, so a plain substring is the exact, honest test.
    cf_whole = _casefold(s, policy)
    if cf_whole in env_tokens or cf_whole in env_text:
        srcs = token_sources.get(cf_whole)
        if not srcs:
            srcs = set()
            for tok, ss in token_sources.items():
                if cf_whole in tok or tok in cf_whole:
                    srcs.update(ss)
        return ArgProvenance(
            arg_name=name, value_repr=s, stance=ProvenanceStance.SUPPORTED,
            id_shaped=True, is_reference=True,
            matched_in=tuple(sorted(srcs, key=lambda x: x.value)),
            components_checked=(s,), components_unmatched=(),
            reason=f"the id {s!r} appears verbatim in env-authored bytes (direct match)",
        )

    components, genuinely_id = _data_bearing_components(s, policy)
    if not genuinely_id:
        # Step D enum guard: delimiter present but no data-bearing component (itil_admin).
        return ArgProvenance(
            arg_name=name, value_repr=s, stance=ProvenanceStance.ABSTAIN,
            id_shaped=False, is_reference=True, matched_in=(), components_checked=(),
            components_unmatched=(),
            reason="enum/role/status token — no data-bearing component to resolve",
        )

    unmatched: list[str] = []
    matched_sources: set[CorpusSource] = set()
    for c in components:
        cf = _casefold(c, policy)
        if _component_found(c, env_text, env_tokens, policy):
            # Record which source(s) supplied a hit (best-effort: exact-token map, else
            # tag as the union of sources whose text contains it).
            hit_sources = token_sources.get(cf)
            if hit_sources:
                matched_sources.update(hit_sources)
            else:
                for blob_tok, srcs in token_sources.items():
                    if cf in blob_tok or blob_tok in cf:
                        matched_sources.update(srcs)
        else:
            unmatched.append(c)

    if unmatched:
        return ArgProvenance(
            arg_name=name, value_repr=s, stance=ProvenanceStance.UNSUPPORTED,
            id_shaped=True, is_reference=True,
            matched_in=tuple(sorted(matched_sources, key=lambda x: x.value)),
            components_checked=components, components_unmatched=tuple(unmatched),
            reason=(
                f"id-shaped reference {s!r} has component(s) {unmatched} that appear in no "
                f"env-authored bytes — looks model-minted (resolve via a read first)"
            ),
        )
    return ArgProvenance(
        arg_name=name, value_repr=s, stance=ProvenanceStance.SUPPORTED,
        id_shaped=True, is_reference=True,
        matched_in=tuple(sorted(matched_sources, key=lambda x: x.value)),
        components_checked=components, components_unmatched=(),
        reason=f"every data-bearing component of {s!r} traced to env-authored bytes",
    )


def classify_call(call: ToolCall, prior: PriorResults,
                  policy: ProvenancePolicy = DEFAULT_POLICY) -> ProvenanceVerdict:
    """The top-level fold over a tool call — the `liveness.classify` shape. PURE.

    Call-level guards first (each → ABSTAIN-all, believe=True):
      * a read / non-mutating call — reads are how provenance ENTERS, never gated.
      * an empty corpus — the first call of an episode; with zero env bytes we cannot
        prove mintage, so we never accuse (the load-bearing first-call safe direction).
    Else maps `classify_arg` over the args; `believe = not any UNSUPPORTED`;
    `unsupported = the UNSUPPORTED arg names` (what the consumer's nudge targets).
    """
    if not call.is_mutating:
        return ProvenanceVerdict(
            believe=True, args=(), unsupported=(),
            reason="read / non-mutating call — provenance not gated (reads source it)",
        )
    if not prior.blobs:
        return ProvenanceVerdict(
            believe=True,
            args=tuple(
                ArgProvenance(
                    arg_name=a.name, value_repr=str(a.value), stance=ProvenanceStance.ABSTAIN,
                    id_shaped=False, is_reference=a.is_reference, matched_in=(),
                    components_checked=(), components_unmatched=(),
                    reason="empty corpus (first call) — cannot prove mintage, abstain",
                )
                for a in call.args
            ),
            unsupported=(),
            reason="empty env corpus — first call of the episode, nothing to check against",
        )

    arg_verdicts = tuple(classify_arg(a, prior, policy) for a in call.args)
    unsupported = tuple(a.arg_name for a in arg_verdicts if a.stance is ProvenanceStance.UNSUPPORTED)
    believe = not unsupported
    if believe:
        reason = "no id/FK argument was minted from nowhere (all traced or none to check)"
    else:
        reason = (
            f"{len(unsupported)} id/FK argument(s) appear model-minted: "
            f"{', '.join(unsupported)} — resolve via a read tool first"
        )
    return ProvenanceVerdict(
        believe=believe, args=arg_verdicts, unsupported=unsupported, reason=reason,
    )
