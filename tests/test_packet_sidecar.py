"""FQ-419/FQ-420 — the `.prompts.json` sidecar WRITE contract + producer verify.

`dos.preflight` owned the read half (`test_preflight_sidecar.py`); this pins the
write half that closes the loop. The blocking finding: the reference renderer
emitted the packet `.md` and exit-0 WITHOUT writing the prompt sidecar, so every
clean-validating packet shipped without its worker prompt bodies and `/fanout`
refused one rung later on `body_empty_picks` — 6+ consecutive dispatch runs
wedged across the apply/tailor/CD lanes (7d ship-rate 0.0%, 2026-06-01).

Two contracts are pinned here:

  1. **write/read round-trip** — a sidecar written by `write_packet_sidecar`
     loads back through `dos.preflight.load_packet_sidecar` as `SIDECAR_PRESENT`
     with non-empty bodies. The two share the `SIDECAR_SCHEMA` token by import,
     so they cannot drift to different strings (the drift `dos.wedge_reason`
     exists to end, applied to the sidecar schema).

  2. **producer-side verify** — `assert_packet_shippable` re-opens the artifact
     and refuses a dropped (absent), corrupt, or empty-body sidecar when the
     packet rendered picks, but does NOT false-refuse a genuine 0-pick DRAIN.
     This is the kernel-does-not-believe-the-renderer guarantee at the source.

Pure stdlib + tmp_path; no git / subprocess (the module does only the one
sidecar read/write).
"""

from __future__ import annotations

import json
from pathlib import Path

from dos import packet_sidecar as ps
from dos import preflight


def _packet(dir_path: Path, stem: str = "next-up-2026-06-01-1") -> Path:
    p = dir_path / f"{stem}.md"
    p.write_text("# next-up packet\n\nLast commit: `deadbeef`\n", encoding="utf-8")
    return p


def _renderer_picks(n: int = 2) -> list[dict]:
    """Renderer-shaped picks — the shape `cmd_render` passes to the serializer."""
    return [
        {
            "n": i,
            "plan_id": "CD",
            "phase_id": f"CD{i}",
            "phase_title": "do the thing",
            "files": [f"src/cd{i}.py"],
            "subagent_type": "general-purpose",
            "prompt_text": f"REAL prompt body for pick {i}",
        }
        for i in range(1, n + 1)
    ]


class TestSchemaIsSingleSourced:
    def test_reader_default_schema_is_the_writer_constant(self):
        # The reader imports SIDECAR_SCHEMA from packet_sidecar for its default;
        # this asserts the two are the same object/string (no drift possible).
        assert preflight.SIDECAR_SCHEMA == ps.SIDECAR_SCHEMA
        assert ps.SIDECAR_SCHEMA == "next-up-prompts-v1"

    def test_sidecar_path_naming_matches_reader(self):
        # The writer and reader must derive the sibling `.prompts.json` path the
        # same way, or a written sidecar lands where the reader does not look.
        pkt = Path("/tmp/next-up-2026-06-01-9.md")
        assert ps.sidecar_path_for(pkt).name == "next-up-2026-06-01-9.prompts.json"


class TestWriteReadRoundTrip:
    def test_written_sidecar_reads_back_present_with_bodies(self, tmp_path):
        pkt = _packet(tmp_path)
        side = ps.write_packet_sidecar(pkt, _renderer_picks(2))
        assert side.exists()

        out = preflight.load_packet_sidecar(pkt)
        assert out["sidecar_status"] == preflight.SIDECAR_PRESENT
        assert out["source"] == "sidecar"
        assert out["schema"] == ps.SIDECAR_SCHEMA
        assert len(out["picks"]) == 2
        assert all(p["prompt_text"] for p in out["picks"])

    def test_written_payload_carries_contract_fields(self, tmp_path):
        pkt = _packet(tmp_path)
        ps.write_packet_sidecar(pkt, _renderer_picks(1))
        doc = json.loads(ps.sidecar_path_for(pkt).read_text(encoding="utf-8"))
        assert doc["schema"] == ps.SIDECAR_SCHEMA
        pick = doc["picks"][0]
        # the fields the downstream consumer (merge_picks_with_verdicts) reads
        for f in ("n", "plan_id", "phase_id", "phase_title", "files", "prompt_text"):
            assert f in pick, f"sidecar pick missing contract field {f}"

    def test_pick_without_n_gets_positional_number(self, tmp_path):
        pkt = _packet(tmp_path)
        ps.write_packet_sidecar(pkt, [{"plan_id": "X", "phase_id": "X1", "prompt_text": "body"}])
        doc = json.loads(ps.sidecar_path_for(pkt).read_text(encoding="utf-8"))
        assert doc["picks"][0]["n"] == 1

    def test_internal_pick_fields_are_dropped(self, tmp_path):
        # A renderer pick carries internal state (anchors/audit/…) the worker
        # launch does not need; the serializer projects onto the contract only.
        pkt = _packet(tmp_path)
        ps.write_packet_sidecar(
            pkt,
            [{"n": 1, "plan_id": "X", "phase_id": "X1", "prompt_text": "b",
              "anchors": ["secret"], "audit": {"x": 1}, "one_hop_metric": "z"}],
        )
        pick = json.loads(ps.sidecar_path_for(pkt).read_text(encoding="utf-8"))["picks"][0]
        assert "anchors" not in pick and "audit" not in pick and "one_hop_metric" not in pick


class TestAssertPacketShippable:
    def test_good_sidecar_passes(self, tmp_path):
        pkt = _packet(tmp_path)
        ps.write_packet_sidecar(pkt, _renderer_picks(2))
        v = ps.assert_packet_shippable(pkt, rendered_pick_count=2)
        assert v.refuse is False
        assert v.reason_code == ps.SHIPPABLE_OK

    def test_absent_sidecar_with_picks_refuses(self, tmp_path):
        # The FQ-420 root drop: renderer rendered picks but never wrote the sidecar.
        pkt = _packet(tmp_path)  # no sidecar written
        v = ps.assert_packet_shippable(pkt, rendered_pick_count=2)
        assert v.refuse is True
        assert v.reason_code == ps.SHIPPABLE_ABSENT
        assert "sidecar_dropped:absent" in (v.reason or "")

    def test_corrupt_sidecar_refuses(self, tmp_path):
        pkt = _packet(tmp_path)
        ps.sidecar_path_for(pkt).write_text("{ not valid json", encoding="utf-8")
        v = ps.assert_packet_shippable(pkt, rendered_pick_count=1)
        assert v.refuse is True
        assert v.reason_code == ps.SHIPPABLE_CORRUPT

    def test_empty_body_picks_refuse_and_are_named(self, tmp_path):
        pkt = _packet(tmp_path)
        ps.write_packet_sidecar(
            pkt,
            [
                {"n": 1, "plan_id": "X", "phase_id": "X1", "prompt_text": "real"},
                {"n": 2, "plan_id": "X", "phase_id": "X2", "prompt_text": ""},
                {"n": 3, "plan_id": "X", "phase_id": "X3", "prompt_text": "   "},
            ],
        )
        v = ps.assert_packet_shippable(pkt, rendered_pick_count=3)
        assert v.refuse is True
        assert v.reason_code == ps.SHIPPABLE_EMPTY_BODIES
        assert v.empty_body_picks == [2, 3]

    def test_drain_zero_picks_does_not_false_refuse(self, tmp_path):
        # A genuine empty DRAIN packet has 0 rendered picks and no sidecar —
        # refusing it here would mislabel a true drain as a renderer drop.
        pkt = _packet(tmp_path)  # no sidecar
        v = ps.assert_packet_shippable(pkt, rendered_pick_count=0)
        assert v.refuse is False
        assert v.reason_code == ps.SHIPPABLE_OK

    def test_envelope_is_json_able(self, tmp_path):
        pkt = _packet(tmp_path)
        v = ps.assert_packet_shippable(pkt, rendered_pick_count=2)  # absent → refuse
        env = v.envelope()
        json.dumps(env)  # must not raise
        assert env["refuse"] is True
        assert env["reason_code"] == ps.SHIPPABLE_ABSENT


class TestBuildContextRecognisesWrittenSidecar:
    """End-to-end: a packet whose sidecar was written by `write_packet_sidecar`
    must NOT trip the dropped-sidecar refuse in `build_context` (the whole point
    — the producer now satisfies the consumer's contract)."""

    def test_written_sidecar_clears_the_dropped_refuse(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPATCH_WORKSPACE", str(tmp_path))
        monkeypatch.setenv("DISPATCH_NEXT_UP_DIR", str(tmp_path / "next-up"))
        pkt = _packet(tmp_path)
        ps.write_packet_sidecar(pkt, _renderer_picks(2))

        ctx = preflight.build_context(pkt)
        assert ctx["packet"]["sidecar_status"] == preflight.SIDECAR_PRESENT
        assert not any(
            str(r).startswith("sidecar_dropped:") for r in ctx["refuse_reasons"]
        )
