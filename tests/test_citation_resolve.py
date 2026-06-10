"""Tests for the legal-citation witness driver (`dos.drivers.citation_resolve`).

The docs/277 §6 #1 experiment, the docs/279 build: a non-git artifact oracle that
answers "does this cited case EXIST in a third-party reporter, and does the quote
MATCH?" — the Tier-1 legal slot the field admits "no benchmark captures." Two halves,
tested independently the way the evidence-source family is built:

  * `classify()` is PURE — `classify(CitationEvidence, CitationPolicy) -> CitationVerdict`.
    These tests pin its four-state ladder (RESOLVED_MATCH / RESOLVED_MISMATCH /
    UNRESOLVED / ABSTAIN) on FROZEN evidence, no network. The load-bearing properties:
    a fabrication (no carrying cluster) is UNRESOLVED; a real reporter SLOT carrying a
    DIFFERENT case than claimed is UNRESOLVED (the collision guard); an unreachable
    corpus NEVER fabricates a RESOLVED (ABSTAIN, the fail-safe); and the quote rung
    refutes a mis-quote ONLY against the FULL opinion, abstaining on a partial snippet
    (the precision discipline — a noisy resolver is worse than none).

  * `gather()`/`_http_get_json()` is the boundary I/O. These tests poison `urlopen` so
    the suite never touches the network, and prove every failure mode (network error,
    timeout, rate-limit, malformed JSON) degrades to an honest unreachable evidence
    object → ABSTAIN, never a raise and never a fabricated RESOLVED.

Plus the seam pins: the `EvidenceSource` face maps the verdict onto the
ATTESTED/REFUTED/NO_SIGNAL vocabulary correctly, a fabrication produces a non-forgeable
REFUTED that can redden a verify, a real match grants belief under `believe_under_floor`,
and the driver obeys the one-way import arrow (the kernel never imports it).
"""
from __future__ import annotations

import urllib.error

import pytest

from dos.drivers import citation_resolve as cr
from dos.drivers.citation_resolve import (
    Citation,
    CitationEvidence,
    CitationPolicy,
    CitationResolveSource,
    ResolvedCluster,
    classify,
)
from dos.evidence import Accountability, EvidenceStance, believe_under_floor, gather_evidence


def _cluster(name, *cites, text="", full=False):
    return ResolvedCluster(name=name, citations=tuple(cites), opinion_text=text, text_is_full=full)


class TestClassifyLadder:
    def test_no_cluster_is_unresolved(self):
        # The Mata fabrication: no reporter carries 925 F.3d 1339.
        ev = CitationEvidence(cite="925 F.3d 1339",
                              claimed_name="Varghese v. China Southern Airlines", clusters=())
        assert classify(ev).verdict is Citation.UNRESOLVED

    def test_real_match_resolves(self):
        ev = CitationEvidence(cite="576 U.S. 644", claimed_name="Obergefell v. Hodges",
                              clusters=(_cluster("Obergefell v. Hodges", "135 S. Ct. 2584", "576 U.S. 644"),))
        v = classify(ev)
        assert v.verdict is Citation.RESOLVED_MATCH
        assert "Obergefell" in v.matched_name

    def test_collision_is_unresolved(self):
        # 92 F.3d 1074 is a real SLOT but resolves to a DIFFERENT case than claimed.
        ev = CitationEvidence(cite="92 F.3d 1074", claimed_name="Hyatt v. N. Cent. Airlines",
                              clusters=(_cluster("Grilli v. Metropolitan Life Insurance Company", "92 F.3d 1074"),))
        v = classify(ev)
        assert v.verdict is Citation.UNRESOLVED
        assert "DIFFERENT case" in v.reason

    def test_name_guard_off_admits_slot(self):
        # With require_name_match False, the bare slot resolving is enough.
        ev = CitationEvidence(cite="92 F.3d 1074", claimed_name="Hyatt v. N. Cent. Airlines",
                              clusters=(_cluster("Grilli v. Metropolitan Life", "92 F.3d 1074"),))
        v = classify(ev, CitationPolicy(require_name_match=False))
        assert v.verdict is Citation.RESOLVED_MATCH

    def test_unreachable_is_abstain_never_resolved(self):
        ev = CitationEvidence(cite="576 U.S. 644", reachable=False, detail="timeout")
        assert classify(ev).verdict is Citation.ABSTAIN

    def test_empty_cite_is_abstain(self):
        ev = CitationEvidence(cite="", reachable=False)
        assert classify(ev).verdict is Citation.ABSTAIN

    def test_quote_mismatch_only_on_full_text(self):
        # Full opinion, quote absent -> REFUTED mismatch.
        ev = CitationEvidence(cite="576 U.S. 644", claimed_name="Obergefell v. Hodges",
                              quote="the right to bear arms shall not be infringed",
                              clusters=(_cluster("Obergefell v. Hodges", "576 U.S. 644",
                                                 text="The Fourteenth Amendment requires a State to license...",
                                                 full=True),))
        assert classify(ev).verdict is Citation.RESOLVED_MISMATCH

    def test_quote_absent_from_snippet_abstains_not_refutes(self):
        # A SNIPPET (full=False) is partial — the quote's absence proves nothing; we
        # must NOT refute (the docs/279 §2 precision fix). Existence still stands.
        ev = CitationEvidence(cite="576 U.S. 644", claimed_name="Obergefell v. Hodges",
                              quote="requires a State to license a marriage between two people of the same sex",
                              clusters=(_cluster("Obergefell v. Hodges", "576 U.S. 644",
                                                 text="Justice Kennedy delivered the opinion of the Court.",
                                                 full=False),))
        assert classify(ev).verdict is Citation.RESOLVED_MATCH

    def test_quote_present_in_full_text_matches(self):
        ev = CitationEvidence(cite="576 U.S. 644", claimed_name="Obergefell v. Hodges",
                              quote="requires a State to license a marriage",
                              clusters=(_cluster("Obergefell v. Hodges", "576 U.S. 644",
                                                 text="The Amendment requires a State to license a marriage between two people.",
                                                 full=True),))
        assert classify(ev).verdict is Citation.RESOLVED_MATCH

    def test_short_quote_does_not_refute(self):
        # A quote below quote_min_len is too generic to witness — abstain, never refute.
        ev = CitationEvidence(cite="576 U.S. 644", claimed_name="Obergefell v. Hodges",
                              quote="the Court", clusters=(_cluster("Obergefell v. Hodges", "576 U.S. 644",
                                                 text="Nothing relevant here.", full=True),))
        assert classify(ev).verdict is Citation.RESOLVED_MATCH


class TestBoundaryFailSafe:
    """Poison urlopen — every failure degrades to an unreachable evidence -> ABSTAIN."""

    def test_network_error_is_unreachable(self, monkeypatch):
        def boom(*a, **k):
            raise urllib.error.URLError("dns down")
        monkeypatch.setattr(cr.urllib.request, "urlopen", boom)
        ev = cr.gather("576 U.S. 644")
        assert ev.reachable is False
        assert classify(ev).verdict is Citation.ABSTAIN

    def test_rate_limit_is_unreachable(self, monkeypatch):
        def boom(*a, **k):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        monkeypatch.setattr(cr.urllib.request, "urlopen", boom)
        ev = cr.gather("576 U.S. 644")
        assert ev.reachable is False
        assert "rate-limited" in ev.detail

    def test_empty_cite_short_circuits_without_network(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("must not call the network for an empty cite")
        monkeypatch.setattr(cr.urllib.request, "urlopen", boom)
        ev = cr.gather("")
        assert ev.reachable is False

    def test_good_search_read_parses_clusters(self, monkeypatch):
        import io
        import json as _json
        payload = {"results": [{"caseName": "Obergefell v. Hodges",
                                "citation": ["576 U.S. 644", "135 S. Ct. 2584"],
                                "snippet": "Justice Kennedy delivered the opinion."}]}

        class _Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(req, *a, **k):
            return _Resp(_json.dumps(payload).encode())
        monkeypatch.setattr(cr.urllib.request, "urlopen", fake)
        ev = cr.gather("576 U.S. 644", claimed_name="Obergefell v. Hodges")
        assert ev.reachable is True
        assert ev.clusters and ev.clusters[0].name == "Obergefell v. Hodges"
        # snippet -> text_is_full stays False (so the quote rung won't false-refute)
        assert ev.clusters[0].text_is_full is False
        assert classify(ev).verdict is Citation.RESOLVED_MATCH

    def test_malformed_json_is_unreachable(self, monkeypatch):
        import io

        class _Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(req, *a, **k):
            return _Resp(b"not json{{{")
        monkeypatch.setattr(cr.urllib.request, "urlopen", fake)
        ev = cr.gather("576 U.S. 644")
        assert ev.reachable is False


class TestEvidenceSourceFace:
    def test_unresolved_maps_to_nonforgeable_refute(self, monkeypatch):
        monkeypatch.setattr(cr, "resolve",
                            lambda cite, **k: cr.CitationVerdict(Citation.UNRESOLVED, "fab",
                                                                 CitationEvidence(cite=cite)))
        src = CitationResolveSource()
        facts = src.gather("925 F.3d 1339 || Varghese v. China Southern", None)
        assert facts.stance is EvidenceStance.REFUTED
        assert facts.accountability is Accountability.THIRD_PARTY
        # A non-forgeable REFUTED reddens a verify.
        assert believe_under_floor([facts]).refuted is True
        assert believe_under_floor([facts]).believe is False

    def test_match_maps_to_attest_and_grants_belief(self, monkeypatch):
        monkeypatch.setattr(cr, "resolve",
                            lambda cite, **k: cr.CitationVerdict(Citation.RESOLVED_MATCH, "ok",
                                                                 CitationEvidence(cite=cite)))
        src = CitationResolveSource()
        facts = src.gather("576 U.S. 644 || Obergefell v. Hodges", None)
        assert facts.stance is EvidenceStance.ATTESTED
        assert believe_under_floor([facts]).believe is True

    def test_abstain_maps_to_no_signal(self, monkeypatch):
        monkeypatch.setattr(cr, "resolve",
                            lambda cite, **k: cr.CitationVerdict(Citation.ABSTAIN, "no corpus",
                                                                 CitationEvidence(cite=cite)))
        src = CitationResolveSource()
        facts = src.gather("576 U.S. 644", None)
        assert facts.stance is EvidenceStance.NO_SIGNAL
        assert facts.reachable is False

    def test_subject_unpacks_cite_name_quote(self):
        c, n, q = CitationResolveSource._unpack("925 F.3d 1339 || Varghese v. China || it held X")
        assert (c, n, q) == ("925 F.3d 1339", "Varghese v. China", "it held X")

    def test_gather_evidence_wraps_a_raising_source_failsafe(self, monkeypatch):
        # A source that raises must degrade to NO_SIGNAL via gather_evidence, never an attest.
        def boom(cite, **k):
            raise RuntimeError("provider exploded")
        monkeypatch.setattr(cr, "resolve", boom)
        src = CitationResolveSource()
        facts = gather_evidence(src, "576 U.S. 644 || Obergefell", None)
        assert facts.stance is EvidenceStance.NO_SIGNAL


class TestStructuralPins:
    def test_to_dict_is_json_shaped(self):
        import json as _json
        ev = CitationEvidence(cite="576 U.S. 644", claimed_name="Obergefell v. Hodges",
                              clusters=(_cluster("Obergefell v. Hodges", "576 U.S. 644"),))
        d = classify(ev).to_dict()
        _json.dumps(d)  # must be serializable
        assert d["verdict"] == "RESOLVED_MATCH"
        assert d["evidence"]["clusters"][0]["name"] == "Obergefell v. Hodges"

    def test_source_is_third_party_class_level(self):
        assert CitationResolveSource.accountability is Accountability.THIRD_PARTY
        assert CitationResolveSource.name == "citation_resolve"

    def test_kernel_does_not_import_this_driver(self):
        # The one-way arrow: nothing under src/dos/*.py (outside drivers/) imports it.
        import pathlib
        import dos
        root = pathlib.Path(dos.__file__).resolve().parent
        offenders = []
        for p in root.glob("*.py"):  # kernel modules only, not drivers/
            txt = p.read_text(encoding="utf-8", errors="replace")
            if "citation_resolve" in txt:
                offenders.append(p.name)
        assert offenders == [], f"kernel modules import the driver: {offenders}"
