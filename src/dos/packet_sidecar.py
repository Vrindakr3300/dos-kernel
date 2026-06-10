"""The `.prompts.json` packet sidecar — the WRITE half of the contract.

FQ-419/FQ-420 root cure. `dos.preflight` already owns the *read* half of the
prompt sidecar — `load_packet_sidecar` (PRESENT/ABSENT/CORRUPT), the
`_sidecar_dropped_refusal` gate, and the `build_context` wiring that refuses a
packet whose `.prompts.json` is missing. But nothing owned the *write* half:
the reference userland renderer (`scripts/next_up_render.py:cmd_render`) emitted
the human packet `.md` and printed `Saved:` / exit-0 **without ever writing the
machine-readable `.prompts.json` the orchestrator actually launches workers
from.** Producer and consumer were out of contract — the schema token
`next-up-prompts-v1` was a *default* in the reader and **defined nowhere**, so
the renderer simply didn't emit it.

The cost was structural and recurring: every clean-validating packet shipped
without its prompt bodies, and the failure surfaced only one rung downstream as
a `/fanout` `body_empty_picks` refuse — naming the symptom, never the cause. By
2026-06-01 it had wedged 6+ consecutive `/dispatch` runs across the apply,
tailor, and CD lanes (7d live ship-rate 0.0%).

This module closes the loop, the same way `dos.wedge_reason` closed the
no-pick-reason drift: **one place declares the schema, and both ends import
it.** It carries two kernel responsibilities:

  1. ``write_packet_sidecar(packet_path, picks)`` — the canonical serializer.
     The renderer calls this; `dos.preflight.load_packet_sidecar` reads exactly
     what it writes. The schema token (`SIDECAR_SCHEMA`) lives here and the
     reader imports it, so the two can never drift to different strings.

  2. ``assert_packet_shippable(packet_path, rendered_pick_count)`` — the
     PRODUCER-side verify. This is the DOS thesis applied at the source
     (dispatch-os-vision §0, *the kernel is the part that doesn't believe the
     agents*): the renderer is an unreliable, self-narrating worker; its exit-0
     `Saved:` is a self-report. The kernel does not believe it — it re-opens the
     artifact it was told exists and refuses if the prompt bodies are absent,
     corrupt, or empty. Catching the drop here (one rung *above* `/fanout`)
     turns a downstream `body_empty_picks` mystery into a loud, typed
     `RENDERER_SIDECAR_DROPPED` refusal that points straight at the renderer.

Pure stdlib (mirrors `preflight` / `wedge_reason` leaf-import character) so the
renderer can import it without dragging heavy deps. The `WedgeReason` import is
the only intra-package dependency, and it is itself a leaf module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Single-source the prompt-sidecar schema token. `dos.preflight.load_packet_sidecar`
# imports THIS constant for its `d.get("schema", SIDECAR_SCHEMA)` default, so the
# writer and reader can never disagree on the string. (Before this module the
# token was a bare literal default in the reader and was emitted by no writer at
# all — the exact producer/consumer drift `dos.wedge_reason` exists to end.)
SIDECAR_SCHEMA = "next-up-prompts-v1"

# The fields a sidecar pick carries — the contract `dos.preflight` consumes
# downstream (`load_packet_sidecar` → `merge_picks_with_verdicts`). `prompt_text`
# is the load-bearing one (the worker's actual prompt body); the rest are
# routing/observability metadata. A writer that omits `prompt_text`, or writes it
# empty, is exactly the drop this module refuses.
_PICK_FIELDS = (
    "n",
    "plan_id",
    "phase_id",
    "phase_title",
    "phase_chain",
    "doc_path",
    "subagent_type",
    "mode",
    "pick_kind",
    "files",
    "gates_on",
    "reserve_paths",
    "prompt_text",
)


def sidecar_path_for(packet_path: Path) -> Path:
    """The `.prompts.json` path beside a packet `.md` — the one naming rule.

    `next-up-2026-06-01-13.md` → `next-up-2026-06-01-13.prompts.json`. Kept here
    (not inlined at the call sites) so the writer and `dos.preflight`'s reader
    derive the sibling path through the *same* function — a future rename touches
    one line. Mirrors `load_packet_sidecar`'s
    `packet_path.with_name(packet_path.stem + ".prompts.json")`.
    """
    return packet_path.with_name(packet_path.stem + ".prompts.json")


def _coerce_pick(raw: dict, *, index: int) -> dict:
    """Project a renderer pick onto the sidecar pick contract (`_PICK_FIELDS`).

    Only the contract fields are carried (a renderer pick holds far more
    internal state — `anchors`, `audit`, `one_hop_metric`, … — that the worker
    launch does not need). `n` defaults to the 1-based position so a pick that
    omitted it still numbers correctly. `prompt_text` is taken verbatim from the
    caller — this module does NOT render it (that is the host renderer's job via
    its own template); the kernel only serializes and verifies what it is given.
    """
    out: dict[str, Any] = {}
    for f in _PICK_FIELDS:
        if f in raw:
            out[f] = raw[f]
    out.setdefault("n", index)
    # Normalize the load-bearing body to a string (never None) so the reader's
    # `len(p.get("prompt_text") or "")` and our own empty-check agree.
    out["prompt_text"] = str(out.get("prompt_text") or "")
    return out


def build_sidecar_payload(picks: list[dict]) -> dict:
    """The full sidecar document: `{schema, picks}` — what gets written to disk.

    Separated from `write_packet_sidecar` so a caller (and a test) can build the
    exact payload without touching the filesystem. Each pick is projected onto
    `_PICK_FIELDS`; `prompt_text` is carried verbatim.
    """
    return {
        "schema": SIDECAR_SCHEMA,
        "picks": [_coerce_pick(p, index=i) for i, p in enumerate(picks, start=1)],
    }


def write_packet_sidecar(packet_path: Path, picks: list[dict]) -> Path:
    """Write `<packet>.prompts.json` beside the packet `.md` and return its path.

    The canonical serializer the host renderer calls. `dos.preflight.load_packet_sidecar`
    reads exactly this shape (same schema token, same per-pick `prompt_text`
    field), so a packet written here loads as `SIDECAR_PRESENT` with non-empty
    bodies — the write/read contract is closed by construction (a test asserts
    the round-trip).

    Does NOT validate shippability — a caller that wants the producer-side
    guarantee calls `assert_packet_shippable` after writing (the renderer does
    both: write, then assert, then exit). Writing is kept separate from
    verifying so the verify can also run standalone against a packet written by
    an older renderer.
    """
    payload = build_sidecar_payload(picks)
    side = sidecar_path_for(packet_path)
    side.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return side


# ---------------------------------------------------------------------------
# Producer-side shippability verify — the kernel does not believe the renderer.
# ---------------------------------------------------------------------------

# `assert_packet_shippable` outcome reasons. These are the structured causes a
# refuse carries; the host renderer maps a refuse onto the `RENDERER_SIDECAR_DROPPED`
# WedgeReason for the `.verdict` envelope it writes.
SHIPPABLE_OK = "ok"
SHIPPABLE_ABSENT = "sidecar_absent"            # the renderer never wrote the sidecar
SHIPPABLE_CORRUPT = "sidecar_corrupt"          # sidecar on disk but bad JSON / wrong shape
SHIPPABLE_EMPTY_BODIES = "sidecar_empty_bodies"  # sidecar present but ≥1 pick body is empty


@dataclass(frozen=True)
class ShippableVerdict:
    """The result of the producer-side sidecar verify.

    `refuse` is the single load-bearing bool the renderer branches on before
    `Saved:`/exit-0. `reason_code` is one of the `SHIPPABLE_*` constants
    (machine-readable, stable). `reason` is the operator-facing string.
    `empty_body_picks` lists the 1-based pick numbers whose `prompt_text` was
    empty (so the renderer can name them, the same way the downstream gate names
    `body_empty_picks`). `rendered_pick_count` echoes the input so the envelope
    can record what the packet claimed.
    """

    refuse: bool
    reason_code: str
    reason: str | None = None
    empty_body_picks: list[int] = field(default_factory=list)
    rendered_pick_count: int = 0

    def envelope(self) -> dict:
        """A small JSON-able dict for the renderer's `.verdict`/stderr envelope."""
        return {
            "refuse": self.refuse,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "empty_body_picks": self.empty_body_picks,
            "rendered_pick_count": self.rendered_pick_count,
        }


def assert_packet_shippable(
    packet_path: Path, *, rendered_pick_count: int
) -> ShippableVerdict:
    """Re-open the just-written sidecar and verify the prompt bodies are real.

    The DOS thesis at the producer: the renderer's exit-0 `Saved:` is a
    self-report the kernel does not trust. This re-reads the artifact from disk
    (not from the in-memory picks the renderer *thinks* it wrote) and refuses if:

      * `rendered_pick_count > 0` and the sidecar is **absent** — the renderer
        rendered picks but never serialized their bodies (the FQ-420 root drop);
      * the sidecar is **corrupt** — on disk but unreadable / wrong shape;
      * the sidecar is **present** but one or more picks have an **empty
        `prompt_text`** — a half-built payload that would launch empty workers.

    Does NOT refuse when `rendered_pick_count <= 0`: a genuine empty DRAIN packet
    legitimately has no sidecar and no bodies (refusing it would mislabel a true
    drain as a renderer drop — the same carve-out `_sidecar_dropped_refusal`
    makes downstream).

    Reads from disk via `sidecar_path_for(packet_path)`. Pure (no git / network);
    the only I/O is the single sidecar read.
    """
    if rendered_pick_count <= 0:
        return ShippableVerdict(
            refuse=False, reason_code=SHIPPABLE_OK, rendered_pick_count=rendered_pick_count
        )

    side = sidecar_path_for(packet_path)
    if not side.exists():
        return ShippableVerdict(
            refuse=True,
            reason_code=SHIPPABLE_ABSENT,
            reason=(
                f"sidecar_dropped:absent rendered_picks={rendered_pick_count} "
                f"(renderer rendered picks but never wrote {side.name} — every "
                f"worker prompt body would be empty)"
            ),
            rendered_pick_count=rendered_pick_count,
        )

    try:
        doc = json.loads(side.read_text(encoding="utf-8"))
        picks = doc.get("picks", []) if isinstance(doc, dict) else None
        if not isinstance(picks, list):
            raise ValueError("sidecar has no picks list")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return ShippableVerdict(
            refuse=True,
            reason_code=SHIPPABLE_CORRUPT,
            reason=(
                f"sidecar_dropped:corrupt rendered_picks={rendered_pick_count} "
                f"({side.name} exists but is unreadable/bad-shape: {exc})"
            ),
            rendered_pick_count=rendered_pick_count,
        )

    empty = [
        int(p.get("n", i))
        for i, p in enumerate(picks, start=1)
        if not str(p.get("prompt_text") or "").strip()
    ]
    if empty:
        return ShippableVerdict(
            refuse=True,
            reason_code=SHIPPABLE_EMPTY_BODIES,
            reason=(
                f"sidecar_empty_bodies picks={','.join(str(n) for n in empty)} "
                f"({side.name} was written but those picks carry no prompt_text — "
                f"a half-built payload)"
            ),
            empty_body_picks=empty,
            rendered_pick_count=rendered_pick_count,
        )

    return ShippableVerdict(
        refuse=False, reason_code=SHIPPABLE_OK, rendered_pick_count=rendered_pick_count
    )
