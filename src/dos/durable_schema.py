"""The schema-evolution floor — every durable record declares its own format (docs/107 §6).

> **The substrate survives the kernel changing because each record declares its
> own format and the reader refuses what it cannot soundly read — the same
> distrust posture the kernel takes toward agents, turned on its own history.**

`CLAUDE.md` calls DOS a "durable substrate," and the whole resumable-work design
(docs/107) assumes a record written by `v0.6` stays *readable and resumable* by
`v0.9`. Nothing in the kernel enforced that. A journal entry, a `run.json`, a
checkpoint payload, an intent-ledger line written under one kernel version is read
back under another — and when the format moved in between, the reader either
silently misparses it (the worst outcome: resuming from a *misread* intent) or
crashes. This module is the contract that forecloses both.

It is the **time axis** of the same closed-enum-as-data discipline `dos.reasons` /
`dos.stamp` apply to the *workspace* axis (see `docs/HACKING.md`): the format is
data the record *declares*, not a constant the reading code *assumes*. Three
disciplines (docs/107 §6), all policy/format — none a new syscall:

  1. **Every durable record carries a `schema:` tag.** Already true of `run.json`
     (`home.SCHEMA`); this generalizes it to *every* persisted record and gives it
     one shape: ``{family, version}`` (a string family name + an int version),
     declared by the WRITER. A reader keys its parse on the record's own tag,
     never on "what kernel version am I."
  2. **Evolution is additive and forward-compatible by default.** A new *field* is
     optional-with-a-default (the `ProgressEvidence` dataclass-default idiom), so a
     newer reader sees an older record's *absence* of a field as the default, and
     an older reader sees a newer record's *extra* field as ignorable. A new *op*
     in a closed vocabulary is skipped by an older replay fold (the
     `lane_journal._STATE_MUTATING_OPS` gate already does this). **Additive
     evolution does NOT bump the version** — that is the whole point: the version
     is the *non-additive*, break-the-reader signal, reserved for a genuine shape
     change. So a reader's `understands` ceiling rarely moves.
  3. **A non-additively-newer record is refuse-don't-guess.** When a record's
     `version` exceeds what the reader understands for that family, the reader must
     **refuse to interpret it** — a typed `UNREADABLE_NEWER` classification a
     caller surfaces as `UNRESUMABLE`/`INDETERMINATE`, never a silent best-effort
     parse. This is the kernel's whole reflex — *when you can't verify, refuse;
     don't fabricate* — applied to its own persisted past.

This module is PURE stdlib (a near-leaf, like `reasons`/`stamp`): it stamps a tag,
reads a tag, and classifies one record's readability against a declared ceiling.
The actual reads/writes live in the durable surfaces (`intent_ledger`,
`lane_journal`, `run_id`); they call `tag()` when they write and `classify()` when
they read. A genuine breaking migration is an explicit operator-run fold (a `dos …
migrate`, the `compact()` shape — a pure old→new transform), never an implicit
in-place reinterpretation; this module supplies the *detection* (the reader knows
it cannot read the record) that makes such a fold necessary rather than silent.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Mapping

# The key every durable record carries. A single name so a grep over the
# persisted surfaces ("which records declare a schema?") has one answer, and so a
# reader never guesses where the tag lives. Value shape: ``{"family": str,
# "version": int}`` — `family` names the record kind (one per durable surface),
# `version` is the WRITER's format version (bumped ONLY on a non-additive change).
SCHEMA_KEY = "schema"


@dataclass(frozen=True)
class SchemaTag:
    """A durable record's self-declared format: ``(family, version)``.

    `family` — the record kind, a stable string (e.g. ``"intent-ledger"``,
        ``"lane-journal"``, ``"run"``). One family per durable surface; the reader
        matches on it so two surfaces' versions never collide.
    `version` — the WRITER's format version, a 1-based int. Bumped ONLY on a
        NON-additive change (a removed/renamed/retyped field, a changed semantic).
        An additive change (a new optional field, a new op) does NOT bump it — that
        is what keeps an older reader forward-compatible without a migration.

    `str`-mirroring `to_dict`/`from_obj` so it round-trips through a JSONL line
    losslessly, the `RunId.to_dict` idiom.
    """

    family: str
    version: int = 1

    def __post_init__(self) -> None:
        # An EMPTY family is permitted at the TAG level — it is the legacy
        # bare-int sentinel (`home.SCHEMA`'s `"schema": 1`, which predates
        # families), parsed by `from_obj` and bridged to a named reader by
        # `classify`. A WRITER must still name a family: `tag()` rejects an empty
        # one (see its body), so a fresh record is never untyped — only a record
        # read back from the pre-family past is.
        if not isinstance(self.family, str):
            raise ValueError("a schema family must be a string")
        if self.version < 1:
            raise ValueError("a schema version is 1-based (got {!r})".format(self.version))

    def to_dict(self) -> dict:
        return {"family": self.family, "version": self.version}

    @classmethod
    def from_obj(cls, obj: Any) -> "SchemaTag | None":
        """Parse a tag out of a record's ``schema`` value. None if absent/malformed.

        Tolerant by design — a record with NO tag, or a tag of the wrong shape, is
        not a crash here: it yields ``None``, and `classify` maps that to the
        explicit `UNTAGGED` classification a caller decides how to treat (the
        torn-tail / `_CORRUPT` posture, lifted to the tag axis). Two accepted
        shapes:
          * the canonical ``{"family": "...", "version": N}`` dict, and
          * a legacy BARE INT (``"schema": 1`` — the `home.SCHEMA` shape that
            predates families): read as family ``""`` at that version, so an
            untyped-family reader can still gate on the integer (see
            `classify`'s `family=""` wildcard).
        """
        if isinstance(obj, bool):  # bool is an int subclass — exclude it explicitly
            return None
        if isinstance(obj, int):
            # Legacy bare-int tag (home.SCHEMA): no family, just a version.
            try:
                return cls(family="", version=int(obj))
            except ValueError:
                return None
        if isinstance(obj, Mapping):
            fam = obj.get("family")
            ver = obj.get("version")
            if not isinstance(fam, str) or isinstance(ver, bool) or not isinstance(ver, int):
                return None
            try:
                return cls(family=fam, version=ver)
            except ValueError:
                return None
        return None


class Readability(str, enum.Enum):
    """How a reader may treat one durable record, given its declared schema tag.

    `str`-valued so it round-trips a `--json` token without a lookup table
    (`Liveness` / `gate_classify.Verdict` idiom). The whole point is the asymmetry
    between READABLE/IGNORABLE (proceed) and UNREADABLE_NEWER (refuse) — the
    refuse-don't-guess floor.
    """

    READABLE = "READABLE"                  # version ≤ the reader's ceiling — parse it
    UNREADABLE_NEWER = "UNREADABLE_NEWER"  # version > the ceiling — REFUSE (don't guess)
    UNTAGGED = "UNTAGGED"                  # no/malformed tag — caller decides (legacy floor)
    WRONG_FAMILY = "WRONG_FAMILY"          # a tag for a DIFFERENT family — not this reader's record

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_soundly_readable(self) -> bool:
        """True iff a reader may parse the record's body without guessing.

        READABLE only. UNREADABLE_NEWER is the refuse case; WRONG_FAMILY is not
        this reader's record at all; UNTAGGED is the legacy floor the CALLER must
        decide on explicitly (a fold over a mixed old/new file treats it
        permissively as the family's v1; a strict reader may refuse) — so neither
        is "soundly readable" without a caller policy, and this property stays
        conservative (the safe direction for a durability guard).
        """
        return self is Readability.READABLE


@dataclass(frozen=True)
class ReadabilityVerdict:
    """The typed result of `classify` — the classification + the record's own tag.

    Carries `tag` (what the record DECLARED, or None when UNTAGGED/WRONG-shaped)
    and `ceiling` (what the reader UNDERSTANDS) so a surfaced refusal is legible:
    "this `intent-ledger` record is v3 but this kernel reads ≤ v2 — run
    `dos runs migrate`," not a bare "can't read it." The `reason` is that
    one-liner. `to_dict` is the `--json` shape (the `LivenessVerdict.to_dict`
    idiom).
    """

    readability: Readability
    reason: str
    family: str
    ceiling: int
    tag: SchemaTag | None = None

    def to_dict(self) -> dict:
        return {
            "readability": self.readability.value,
            "reason": self.reason,
            "family": self.family,
            "ceiling": self.ceiling,
            "tag": self.tag.to_dict() if self.tag is not None else None,
        }


def tag(family: str, version: int = 1) -> dict:
    """The ``{"schema": {"family", "version"}}`` fragment a WRITER merges into a record.

    Pure constructor — the write-side half of the contract. A durable surface's
    entry builder does ``{**durable_schema.tag("intent-ledger", INTENT_LEDGER_SCHEMA), …}``
    so every persisted record self-declares its format with one call and one shape.
    A WRITER must name a family (an empty one is the legacy READ-side sentinel, not
    a legal write) and a 1-based version — both raise here, surfaced loudly the way
    a malformed `[stamp]` table is: a writer that stamps a bad tag is a kernel bug,
    not silent data.
    """
    if not family:
        raise ValueError("a written schema tag must name a family (empty is the legacy read-only sentinel)")
    return {SCHEMA_KEY: SchemaTag(family=family, version=version).to_dict()}


def classify(
    record: Mapping[str, Any],
    *,
    family: str,
    understands: int,
) -> ReadabilityVerdict:
    """Classify whether THIS reader may soundly parse one durable `record`. PURE.

    The read-side half of the contract, and the refuse-don't-guess gate. The
    reader declares the `family` it is reading and `understands` — the MAX version
    of that family it knows how to parse (its ceiling). The verdict:

      * **READABLE** — the record's tag is this family at a version ≤ `understands`.
        Parse the body. (The additive-evolution contract means a `v1` reader
        reading a `v1` record still ignores any *extra fields* a later writer
        added — that is the body parser's job, not this gate's; this gate only
        decides "is the VERSION within my ceiling.")
      * **UNREADABLE_NEWER** — the tag is this family but at a version GREATER than
        `understands`: a non-additive change this kernel predates. **Refuse** — the
        caller surfaces `UNRESUMABLE`/`INDETERMINATE`, never a best-effort parse of
        a shape it does not know. This is the §6 floor.
      * **WRONG_FAMILY** — the tag names a DIFFERENT family. Not this reader's
        record (e.g. a lane-journal entry handed to an intent-ledger reader); the
        caller skips it rather than misreading it as its own.
      * **UNTAGGED** — no tag, or a malformed one. The legacy floor: records that
        predate the tag contract, or a torn write. The caller decides — a tolerant
        replay over a file that mixes pre-tag and tagged records treats UNTAGGED as
        the family's implicit v1 (and `is_soundly_readable` stays False so the
        decision is never implicit). A `family=""` ceiling reader (the legacy
        bare-int `home.SCHEMA` case) treats a bare-int tag of the right version as
        READABLE — the back-compat bridge.

    Conservative on every unknown — the safe direction for a *durability* guard, the
    `WorkspaceFacts(None)`-is-conservative and `git_delta`-degrades-to-empty rule:
    when in doubt about whether a record is soundly readable, do not claim it is.
    """
    parsed = SchemaTag.from_obj(record.get(SCHEMA_KEY))
    if parsed is None:
        return ReadabilityVerdict(
            readability=Readability.UNTAGGED,
            reason=(
                f"record carries no {SCHEMA_KEY!r} tag (or a malformed one) — "
                f"a pre-tag/legacy or torn record; caller decides (treated as "
                f"{family!r} v1 by a tolerant fold, refused by a strict reader)"
            ),
            family=family,
            ceiling=understands,
            tag=None,
        )
    # Family match. A reader declaring family "" is the legacy bare-int gate: it
    # accepts a bare-int (family-"") tag, and ALSO any family at its version (it is
    # the "I only care about the integer version" reader). A named-family reader
    # accepts ONLY its own family; a bare-int tag (family "") handed to a named
    # reader is treated as that reader's family by version (the home.SCHEMA bridge:
    # a legacy untyped record is the named surface's record at that version).
    if parsed.family and family and parsed.family != family:
        return ReadabilityVerdict(
            readability=Readability.WRONG_FAMILY,
            reason=(
                f"record declares family {parsed.family!r} but this reader reads "
                f"{family!r} — not this reader's record; skip it"
            ),
            family=family,
            ceiling=understands,
            tag=parsed,
        )
    if parsed.version > understands:
        return ReadabilityVerdict(
            readability=Readability.UNREADABLE_NEWER,
            reason=(
                f"record is {family or parsed.family!r} v{parsed.version} but this "
                f"kernel reads ≤ v{understands} — a non-additive format change this "
                f"version predates; REFUSING to guess (run the explicit migration "
                f"fold, never a best-effort parse)"
            ),
            family=family,
            ceiling=understands,
            tag=parsed,
        )
    return ReadabilityVerdict(
        readability=Readability.READABLE,
        reason=(
            f"{family or parsed.family!r} v{parsed.version} ≤ ceiling v{understands} "
            f"— soundly readable"
        ),
        family=family,
        ceiling=understands,
        tag=parsed,
    )


# ---------------------------------------------------------------------------
# The structured-refusal surface (docs/115 primitive 4). The refuse-don't-guess
# floor above is a per-reader READ GATE; this is the token + wire shape that lets
# it surface through the kernel's CLOSED refusal vocabulary, carrying the supported
# set the way MCP's `UnsupportedProtocolVersionError(-32004)` carries
# `{supported, requested}` (a normative MUST DOS's durable_schema predates).
# ---------------------------------------------------------------------------

# The `reason_class` token a refusal carries when a durable record is unreadable
# because its schema version is newer than this kernel understands. Declared in
# `dos.reasons.BASE_REASONS` (category MISROUTE — a record this kernel can't soundly
# parse is work to route elsewhere, the SELF_MODIFY sibling), so it is emittable /
# verifiable / refusable / `dos man wedge`-documented like every other refuse.
SCHEMA_UNREADABLE_REASON = "SCHEMA_UNREADABLE"


def unreadable_refusal_payload(verdict: "ReadabilityVerdict") -> dict:
    """Render an UNREADABLE_NEWER verdict as the MCP `{supported, requested}` shape.

    PURE. Turns the read-gate's `ReadabilityVerdict` into the structured-refusal
    payload a caller (a resuming successor, a cross-version fleet member, the MCP
    server) gets WITH the refusal, so it can re-negotiate or migrate instead of
    failing blind. The shape mirrors MCP's `-32004` body:

      * ``reason_class`` — the closed-vocabulary token (``SCHEMA_UNREADABLE``);
      * ``family``       — which durable surface the record belongs to;
      * ``requested``    — the record's own declared version (what it needs);
      * ``supported``    — ``[1 .. ceiling]``, the versions THIS kernel can read
                           (the "supported set" — MCP returns the same so the caller
                           knows what to fall back to);
      * ``detail``       — the legible one-liner (`ReadabilityVerdict.reason`).

    Defensive on the non-newer cases (a caller should only render this for an
    UNREADABLE_NEWER verdict): `requested` falls back to the ceiling when the
    record carried no parseable tag, so the payload is always well-formed.
    """
    requested = verdict.tag.version if verdict.tag is not None else verdict.ceiling
    supported = list(range(1, verdict.ceiling + 1))
    return {
        "reason_class": SCHEMA_UNREADABLE_REASON,
        "family": verdict.family,
        "requested": requested,
        "supported": supported,
        "detail": verdict.reason,
    }
