"""docs/107 §6 / Phase 1 — the schema-evolution floor.

Pins the refuse-don't-guess durability contract: a durable record declares its
own ``schema`` tag, an additive (extra-field / new-op) change stays forward-safe,
and a NON-additively-newer record is REFUSED (typed `UNREADABLE_NEWER`), never
silently misparsed. Pure-stdlib unit tests on hand-built record dicts — no I/O,
no live crash, the `liveness.classify` test posture.
"""

from __future__ import annotations

import json

from dos import durable_schema as ds
from dos.durable_schema import Readability, SchemaTag


# --------------------------------------------------------------------------
# SchemaTag — the self-declared format, and its round-trip.
# --------------------------------------------------------------------------


def test_tag_helper_emits_canonical_fragment():
    frag = ds.tag("intent-ledger", 1)
    assert frag == {"schema": {"family": "intent-ledger", "version": 1}}


def test_tag_round_trips_through_jsonl():
    frag = ds.tag("lane-journal", 2)
    line = json.dumps({**frag, "op": "ACQUIRE"}, sort_keys=True)
    back = json.loads(line)
    parsed = SchemaTag.from_obj(back["schema"])
    assert parsed == SchemaTag(family="lane-journal", version=2)


def test_tag_rejects_empty_family_and_bad_version():
    import pytest

    # An empty family is LEGAL on the SchemaTag type — it is the legacy bare-int
    # read-side sentinel (`from_obj(1) == SchemaTag("", 1)`). A bad VERSION still
    # raises at the type level.
    assert SchemaTag(family="", version=1) == SchemaTag("", 1)
    with pytest.raises(ValueError):
        SchemaTag(family="x", version=0)
    # But a WRITER must always name a family: tag() rejects an empty one, so a
    # fresh record is never untyped (only a record read from the pre-family past).
    with pytest.raises(ValueError):
        ds.tag("", 1)
    with pytest.raises(ValueError):
        ds.tag("x", 0)


def test_from_obj_tolerates_malformed_and_legacy_shapes():
    # Canonical dict.
    assert SchemaTag.from_obj({"family": "run", "version": 3}) == SchemaTag("run", 3)
    # Legacy bare int (the home.SCHEMA shape) → family "" at that version.
    assert SchemaTag.from_obj(1) == SchemaTag("", 1)
    # A bool is NOT a version (even though bool subclasses int).
    assert SchemaTag.from_obj(True) is None
    # Malformed: missing/typed-wrong fields → None (not a crash).
    assert SchemaTag.from_obj({"family": "run"}) is None
    assert SchemaTag.from_obj({"version": 2}) is None
    assert SchemaTag.from_obj({"family": 5, "version": 2}) is None
    assert SchemaTag.from_obj({"family": "run", "version": "2"}) is None
    assert SchemaTag.from_obj({"family": "run", "version": True}) is None
    assert SchemaTag.from_obj("not-a-tag") is None
    assert SchemaTag.from_obj(None) is None


# --------------------------------------------------------------------------
# classify — the refuse-don't-guess gate (the heart of §6).
# --------------------------------------------------------------------------


def test_same_version_is_readable():
    rec = {**ds.tag("intent-ledger", 1), "op": "INTENT"}
    v = ds.classify(rec, family="intent-ledger", understands=1)
    assert v.readability is Readability.READABLE
    assert v.readability.is_soundly_readable


def test_older_record_is_readable_by_newer_reader():
    # A v1 record read by a kernel that understands up to v3: within ceiling.
    rec = {**ds.tag("intent-ledger", 1), "op": "INTENT"}
    v = ds.classify(rec, family="intent-ledger", understands=3)
    assert v.readability is Readability.READABLE


def test_additive_extra_field_does_not_affect_the_gate():
    # The additive contract: a later writer added an extra field but DID NOT bump
    # the version (additive ≠ version bump). An older reader at the SAME ceiling
    # still classifies it READABLE — the gate is on version, the body parser
    # ignores the extra field.
    rec = {**ds.tag("intent-ledger", 1), "op": "INTENT", "a_field_added_later": 42}
    v = ds.classify(rec, family="intent-ledger", understands=1)
    assert v.readability is Readability.READABLE


def test_newer_version_is_refused_never_guessed():
    # The load-bearing §6 case: a v3 record read by a kernel that only understands
    # v2. REFUSE — never a best-effort parse of a shape it does not know.
    rec = {**ds.tag("intent-ledger", 3), "op": "INTENT"}
    v = ds.classify(rec, family="intent-ledger", understands=2)
    assert v.readability is Readability.UNREADABLE_NEWER
    assert not v.readability.is_soundly_readable
    # The refusal is legible: it names the family, the record version, and the
    # ceiling so a surfaced verdict can tell the operator to migrate.
    assert "v3" in v.reason and "v2" in v.reason
    assert v.tag == SchemaTag("intent-ledger", 3)
    assert v.ceiling == 2


def test_wrong_family_is_not_this_readers_record():
    rec = {**ds.tag("lane-journal", 1), "op": "ACQUIRE"}
    v = ds.classify(rec, family="intent-ledger", understands=1)
    assert v.readability is Readability.WRONG_FAMILY
    assert not v.readability.is_soundly_readable


def test_untagged_record_is_the_legacy_floor():
    # A pre-tag record (no schema key) → UNTAGGED, not a crash, and NOT silently
    # readable: the caller must decide (a tolerant fold treats it as v1; a strict
    # reader refuses). is_soundly_readable stays False so the decision is explicit.
    rec = {"op": "INTENT"}
    v = ds.classify(rec, family="intent-ledger", understands=1)
    assert v.readability is Readability.UNTAGGED
    assert not v.readability.is_soundly_readable


def test_malformed_tag_is_untagged_not_a_crash():
    rec = {"schema": {"family": "intent-ledger"}, "op": "INTENT"}  # no version
    v = ds.classify(rec, family="intent-ledger", understands=1)
    assert v.readability is Readability.UNTAGGED


def test_legacy_bare_int_tag_bridges_to_a_named_reader():
    # The home.SCHEMA bridge: a record tagged with a bare int (family "") read by a
    # named-family reader is treated as that reader's record at that version.
    rec = {"schema": 1, "op": "INTENT"}
    v = ds.classify(rec, family="run", understands=1)
    assert v.readability is Readability.READABLE
    # And a bare-int v2 still refused by a v1 reader.
    rec2 = {"schema": 2, "op": "INTENT"}
    v2 = ds.classify(rec2, family="run", understands=1)
    assert v2.readability is Readability.UNREADABLE_NEWER


def test_verdict_to_dict_is_json_round_trippable():
    rec = {**ds.tag("intent-ledger", 5), "op": "INTENT"}
    v = ds.classify(rec, family="intent-ledger", understands=2)
    d = v.to_dict()
    assert json.loads(json.dumps(d)) == d
    assert d["readability"] == "UNREADABLE_NEWER"
    assert d["tag"] == {"family": "intent-ledger", "version": 5}
