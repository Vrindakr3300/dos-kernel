"""docs/164 F1.5 — the `dos rewind` human actuator + the `rewind_evidence` boundary reader.

`dos rewind --run-id RID --fire SIGNAL` replays the run's intent ledger for the minted
`(turn_index, transcript_digest)` checkpoint, reads the run's transcript turns off disk
(hashing each), and PROPOSES a truncation back to the anchor + a byte-clean no-good note.
It NEVER truncates — the kernel proposes; the host owns the transcript (docs/164 P1.5, the
docs/99 advisory floor on the conversation axis).

These pin the verb END-TO-END through the boundary reader (`rewind_evidence`), which the
588-line pure-verdict suite (`test_rewind.py`) does NOT exercise — that suite is frozen
fixtures only. The gap this closes (the usefulness-audit finding): the pure `rewind_plan`
was a fixture-only island; here it fires against a real on-disk ledger + transcript.

Verdict → exit-code map (the `cmd_resume` idiom): REWIND/NO_REWIND = 0, UNANCHORED = 3,
a bad --run-id = contract-error 2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dos import cli
from dos import config as _config
from dos import intent_ledger as il
from dos import rewind_evidence
from dos.rewind import digest_turn, SuspendCheckpoint


def _rewind_args(tmp_path: Path, **kw) -> argparse.Namespace:
    base = dict(workspace=str(tmp_path), run_id="RID-W", fire="", json=True, output=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _seed_run(tmp_path: Path, *, turns: list[str], checkpoint_turn: int,
              checkpoint_digest: str | None = None, run_id: str = "RID-W") -> None:
    """A run with an INTENT + a SUSPEND that stamps a conversation checkpoint, plus a
    transcript on disk. `checkpoint_digest=None` → digest the real turn (a matching
    anchor); pass a wrong digest to force the UNANCHORED floor."""
    cfg = _config.default_config(tmp_path)
    run_dir = il.run_dir_for(run_id, cfg=cfg)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / rewind_evidence.TRANSCRIPT_JSONL_NAME).write_text(
        "\n".join(turns), encoding="utf-8")
    digest = (checkpoint_digest if checkpoint_digest is not None
              else digest_turn(turns[checkpoint_turn]))
    ckpt = SuspendCheckpoint(turn_index=checkpoint_turn,
                             transcript_digest=digest, present=True)
    il.append(run_id, il.intent_entry(goal="demo", plan="d", phase="x",
                                      declared_steps=["s1"]), cfg=cfg)
    il.append(run_id, il.suspend_entry(reason="t", checkpoint=ckpt), cfg=cfg)


# ── the four verdicts, end-to-end through the boundary ───────────────────────
def test_no_fire_is_no_rewind(tmp_path: Path, capsys):
    """No ground-truth stop signal → NO_REWIND (exit 0), transcript untouched."""
    _seed_run(tmp_path, turns=["t0", "t1", "t2", "t3"], checkpoint_turn=1)
    rc = cli.cmd_rewind(_rewind_args(tmp_path, fire=""))
    assert rc == cli._REWIND_EXIT_CODES["NO_REWIND"]
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "NO_REWIND"
    assert out["dropped_turns"] == []  # nothing excised


def test_thrashing_fire_with_matching_checkpoint_rewinds(tmp_path: Path, capsys):
    """THRASHING + a minted anchor that digest-matches → REWIND (exit 0), drops the
    turns strictly after the anchor."""
    _seed_run(tmp_path, turns=["t0", "t1", "t2", "t3", "t4"], checkpoint_turn=2)
    rc = cli.cmd_rewind(_rewind_args(tmp_path, fire="THRASHING"))
    assert rc == cli._REWIND_EXIT_CODES["REWIND"]
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "REWIND"
    assert out["rewind_to_turn"] == 2
    assert out["dropped_turns"] == [3, 4]  # subtraction-only: strictly after the anchor


def test_diverged_fire_rewinds(tmp_path: Path, capsys):
    """DIVERGED is the git-axis stop signal; the conversation axis honors it too."""
    _seed_run(tmp_path, turns=["a", "b", "c"], checkpoint_turn=0)
    rc = cli.cmd_rewind(_rewind_args(tmp_path, fire="DIVERGED"))
    assert rc == cli._REWIND_EXIT_CODES["REWIND"]
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "REWIND"
    assert out["rewind_to_turn"] == 0
    assert out["dropped_turns"] == [1, 2]


def test_rewritten_turn_under_checkpoint_is_unanchored(tmp_path: Path, capsys):
    """The non-forgeable-anchor floor: a stop fired, but the live turn at the
    checkpoint's index no longer digests to the stamp → UNANCHORED (exit 3). The kernel
    refuses to rewind to a turn it did not stamp (the §6 conversation-axis litmus)."""
    # Stamp a checkpoint over a digest that does NOT match the live turn 1.
    _seed_run(tmp_path, turns=["t0", "t1", "t2"], checkpoint_turn=1,
              checkpoint_digest="deadbeef" * 8)  # a wrong (non-matching) digest
    rc = cli.cmd_rewind(_rewind_args(tmp_path, fire="THRASHING"))
    assert rc == cli._REWIND_EXIT_CODES["UNANCHORED"]
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "UNANCHORED"
    assert out["rewind_to_turn"] == -1  # rewinds to NOTHING, not to an un-stamped turn


def test_no_checkpoint_minted_is_unanchored(tmp_path: Path, capsys):
    """A SUSPEND that stamped no conversation checkpoint (an older kernel / git-only
    suspend) → UNANCHORED on a fire: there is no anchor to rewind to."""
    cfg = _config.default_config(tmp_path)
    run_dir = il.run_dir_for("RID-W", cfg=cfg)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / rewind_evidence.TRANSCRIPT_JSONL_NAME).write_text("t0\nt1", encoding="utf-8")
    il.append("RID-W", il.intent_entry(goal="g", declared_steps=["s1"]), cfg=cfg)
    il.append("RID-W", il.suspend_entry(reason="git-only"), cfg=cfg)  # no checkpoint=
    rc = cli.cmd_rewind(_rewind_args(tmp_path, fire="THRASHING"))
    assert rc == cli._REWIND_EXIT_CODES["UNANCHORED"]


def test_missing_run_id_is_contract_error(tmp_path: Path):
    rc = cli.cmd_rewind(_rewind_args(tmp_path, run_id=""))
    assert rc == cli._REWIND_EXIT_CONTRACT_ERROR


# ── the byte-clean no-good note discipline, through the verb ──────────────────
def test_diverged_note_carries_only_the_kernel_verdict_token(tmp_path: Path, capsys):
    """On a DIVERGED rewind the note carries the fieldless DIVERGED verdict token —
    a kernel-authored byte, never prose. (The §6 no-good-note litmus, verb side.)"""
    _seed_run(tmp_path, turns=["x", "y"], checkpoint_turn=0)
    cli.cmd_rewind(_rewind_args(tmp_path, fire="DIVERGED"))
    out = json.loads(capsys.readouterr().out)
    note = out["no_good_note"]
    # Exactly the DIVERGED token, rendered from the kernel template, no env excerpt.
    assert [t["kind"] for t in note["tokens"]] == ["DIVERGED"]
    assert note["env_excerpt"] is None
    assert any("DIVERGED" in ln for ln in note["lines"])


# ── the boundary reader's fail-closed posture ────────────────────────────────
def test_missing_transcript_is_unanchored(tmp_path: Path, capsys):
    """No transcript file → gather_turns yields no turns → the checkpoint matches no
    live turn → UNANCHORED (fail-closed; refuse to rewind to an unconfirmed turn)."""
    cfg = _config.default_config(tmp_path)
    ckpt = SuspendCheckpoint(turn_index=0, transcript_digest=digest_turn("t0"),
                             present=True)
    il.append("RID-W", il.intent_entry(goal="g", declared_steps=["s1"]), cfg=cfg)
    il.append("RID-W", il.suspend_entry(reason="t", checkpoint=ckpt), cfg=cfg)
    # NOTE: no transcript.jsonl written.
    rc = cli.cmd_rewind(_rewind_args(tmp_path, fire="DIVERGED"))
    assert rc == cli._REWIND_EXIT_CODES["UNANCHORED"]


def test_gather_turns_digests_each_turn_in_order(tmp_path: Path):
    """The reader hashes each transcript line into a TurnRef(index, digest) — the
    digest is the KERNEL's hash (the anchor's non-forgeable identity)."""
    cfg = _config.default_config(tmp_path)
    run_dir = il.run_dir_for("RID-W", cfg=cfg)
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = ["alpha", "beta", "gamma"]
    (run_dir / rewind_evidence.TRANSCRIPT_JSONL_NAME).write_text(
        "\n".join(lines), encoding="utf-8")
    turns = rewind_evidence.gather_turns("RID-W", cfg=cfg)
    assert [t.index for t in turns] == [0, 1, 2]
    assert [t.digest for t in turns] == [digest_turn(s) for s in lines]
