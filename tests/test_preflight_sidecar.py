"""FQ-420 — the dropped/corrupt `.prompts.json` sidecar refuse contract.

The blocking finding (7d ship-rate 0.0%): `/next-up` returns a packet that HAS
picks but drops the prompt sidecar; the preflight's markdown fallback rehydrates
the picks with empty bodies, so every `/fanout` refuses on `body_empty_picks` —
naming the *symptom*, never the *cause*. These tests pin the kernel contract
that makes the dropped sidecar a loud, named refuse signal pointing at the root
(the renderer), distinct from a genuinely empty DRAIN packet.

The preflight is pure-ish: `load_packet_sidecar` and `_sidecar_dropped_refusal`
take a path / values and do no git or subprocess I/O, so they are the unit
surface here. One `build_context` integration test confirms the wiring (its git
/ subprocess probes degrade gracefully against a bare tmp dir).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dos import preflight


def _write_packet(dir_path: Path, *, picks: int = 2) -> Path:
    """A minimal /next-up packet markdown with `picks` rendered picks."""
    lines = ["# next-up packet", "", "Last commit: `deadbeef`", "", "Packet schema: `next-up-packet-v1`", ""]
    for n in range(1, picks + 1):
        lines.append(f"### {n}. RS RS{n} — do the thing")
        lines.append("")
    p = dir_path / "next-up-2026-06-01-1.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _write_sidecar(packet_path: Path, *, picks: int = 2, corrupt: bool = False) -> Path:
    side = packet_path.with_name(packet_path.stem + ".prompts.json")
    if corrupt:
        side.write_text("{ this is not valid json", encoding="utf-8")
        return side
    payload = {
        "schema": "next-up-prompts-v1",
        "picks": [
            {
                "n": n, "plan_id": "RS", "phase_id": f"RS{n}",
                "phase_title": "do the thing", "files": [f"src/rs{n}.py"],
                "prompt_text": "real prompt body here",
            }
            for n in range(1, picks + 1)
        ],
    }
    side.write_text(json.dumps(payload), encoding="utf-8")
    return side


class TestSidecarStatus:
    def test_present_sidecar_reports_present(self, tmp_path):
        pkt = _write_packet(tmp_path, picks=2)
        _write_sidecar(pkt, picks=2)
        out = preflight.load_packet_sidecar(pkt)
        assert out["sidecar_status"] == preflight.SIDECAR_PRESENT
        assert out["source"] == "sidecar"
        assert len(out["picks"]) == 2

    def test_absent_sidecar_reports_absent_and_falls_back_to_markdown(self, tmp_path):
        pkt = _write_packet(tmp_path, picks=2)  # no sidecar written
        out = preflight.load_packet_sidecar(pkt)
        assert out["sidecar_status"] == preflight.SIDECAR_ABSENT
        assert out["source"] == "markdown"
        # markdown fallback still finds the picks (with empty bodies)
        assert len(out["picks"]) == 2
        assert all(p["prompt_text"] == "" for p in out["picks"])

    def test_corrupt_sidecar_reports_corrupt_not_absent(self, tmp_path):
        # The load-bearing distinction: a sidecar on disk but unreadable is
        # CORRUPT, not ABSENT — a half-written drop, named separately.
        pkt = _write_packet(tmp_path, picks=2)
        _write_sidecar(pkt, corrupt=True)
        out = preflight.load_packet_sidecar(pkt)
        assert out["sidecar_status"] == preflight.SIDECAR_CORRUPT
        assert out["source"] == "markdown"  # fell through to header parse


class TestSidecarDroppedRefusal:
    def test_absent_with_picks_refuses(self):
        refuse, reason = preflight._sidecar_dropped_refusal(
            preflight.SIDECAR_ABSENT, rendered_pick_count=3
        )
        assert refuse is True
        assert reason is not None and reason.startswith("sidecar_dropped:absent")

    def test_corrupt_with_picks_refuses(self):
        refuse, reason = preflight._sidecar_dropped_refusal(
            preflight.SIDECAR_CORRUPT, rendered_pick_count=1
        )
        assert refuse is True
        assert reason is not None and reason.startswith("sidecar_dropped:corrupt")

    def test_present_never_refuses(self):
        refuse, _ = preflight._sidecar_dropped_refusal(
            preflight.SIDECAR_PRESENT, rendered_pick_count=3
        )
        assert refuse is False

    def test_empty_drain_packet_does_not_false_refuse(self):
        # A genuine empty DRAIN packet has 0 rendered picks and legitimately no
        # sidecar — refusing it here would mislabel a true drain as a drop.
        refuse, _ = preflight._sidecar_dropped_refusal(
            preflight.SIDECAR_ABSENT, rendered_pick_count=0
        )
        assert refuse is False


class TestBuildContextWiring:
    """End-to-end: a packet with picks but a dropped sidecar must surface
    `refuse=True` with the sidecar cause listed BEFORE the body_empty symptom.
    """

    def test_dropped_sidecar_refuses_root_before_symptom(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPATCH_WORKSPACE", str(tmp_path))
        # keep the verdict-envelope / next-up dir probes inside the tmp tree
        monkeypatch.setenv("DISPATCH_NEXT_UP_DIR", str(tmp_path / "next-up"))
        pkt = _write_packet(tmp_path, picks=2)  # no sidecar → dropped

        ctx = preflight.build_context(pkt)

        assert ctx["refuse"] is True
        assert ctx["packet"]["sidecar_status"] == preflight.SIDECAR_ABSENT
        reasons = ctx["refuse_reasons"]
        # the dropped-sidecar root cause is present AND ordered first
        assert any(r.startswith("sidecar_dropped:absent") for r in reasons)
        assert reasons[0].startswith("sidecar_dropped:absent")
        # the body_empty symptom is still reported (both true), just after
        assert any(r.startswith("body_empty_picks=") for r in reasons)

    def test_present_sidecar_does_not_refuse_on_sidecar(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPATCH_WORKSPACE", str(tmp_path))
        monkeypatch.setenv("DISPATCH_NEXT_UP_DIR", str(tmp_path / "next-up"))
        pkt = _write_packet(tmp_path, picks=2)
        _write_sidecar(pkt, picks=2)  # real bodies

        ctx = preflight.build_context(pkt)

        assert ctx["packet"]["sidecar_status"] == preflight.SIDECAR_PRESENT
        # no sidecar_dropped reason regardless of any other gate
        assert not any(
            str(r).startswith("sidecar_dropped:") for r in ctx["refuse_reasons"]
        )


class TestFQ336TerminalClaimOverlap:
    """`list_active_filtered` must NOT flag a row whose claim_status is terminal
    (done/stale/released/expired) as an in-flight overlap, even while its legacy
    `status` field still lags at in_progress.

    FQ-336 (2026-06-05): the false-collision twin of the /next-up picker
    false-DRAIN. A claim that shipped (claim_status: done) but whose `status`
    field was not flipped sat in active_work for up to 14 days; treating it as an
    overlap re-blocked a phase the picker (next_up_context._trim_active_work)
    already correctly freed.
    """

    def _filtered(self, monkeypatch, rows, picks):
        import json as _json
        monkeypatch.setattr(
            preflight, "_run", lambda *a, **k: (0, _json.dumps(rows), "")
        )
        return preflight.list_active_filtered(set(picks))

    def test_done_claim_not_an_overlap(self, monkeypatch):
        rows = [
            {"id": "a", "plan": "FTA", "phase": "FTA2",
             "status": "in_progress", "claim_status": "done", "dispatched_by": "old"},
            {"id": "b", "plan": "AB", "phase": "AB3a",
             "status": "in_progress", "claim_status": "working", "dispatched_by": "old"},
        ]
        _filtered, overlap = self._filtered(
            monkeypatch, rows, {"FTA/FTA2", "AB/AB3a", "FTA2", "AB3a"}
        )
        assert "FTA2" not in overlap   # done claim → freed
        assert "AB3a" in overlap       # working claim → still blocks

    def test_stale_and_expired_claims_not_overlaps(self, monkeypatch):
        rows = [
            {"id": "a", "plan": "P", "phase": "P1",
             "status": "in_progress", "claim_status": "stale", "dispatched_by": "x"},
            {"id": "b", "plan": "P", "phase": "P2",
             "status": "in_progress", "claim_status": "expired", "dispatched_by": "x"},
            {"id": "c", "plan": "P", "phase": "P3",
             "status": "in_progress", "claim_status": "released", "dispatched_by": "x"},
        ]
        _filtered, overlap = self._filtered(
            monkeypatch, rows, {"P/P1", "P/P2", "P/P3", "P1", "P2", "P3"}
        )
        assert overlap == []  # all terminal → none block

    def test_working_claim_still_overlaps(self, monkeypatch):
        rows = [
            {"id": "a", "plan": "P", "phase": "P1",
             "status": "in_progress", "claim_status": "working", "dispatched_by": "x"},
        ]
        _filtered, overlap = self._filtered(monkeypatch, rows, {"P/P1", "P1"})
        assert overlap == ["P1"]  # genuinely live → blocks
