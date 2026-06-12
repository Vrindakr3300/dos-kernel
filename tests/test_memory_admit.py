"""docs/314 P1 — the memory WRITE gate: adjudicate a candidate before it
enters any store.

The recall gate (docs/103) catches a stored claim that AGED into a lie; this
gate catches the claim that was NEVER true, at the moment it is cheapest to
witness and before any future session can inherit it. The verdict is TYPING,
not censorship: only a claim contradicted by ground truth right now refuses
(REJECT_POISON, exit 3); everything else admits, typed with the authority it
may wear (WITNESSED / AS_CLAIM / OPINION, exit 0).

Pins: the pure `classify_admission` ladder on frozen evidence (every rung,
plus the write/read asymmetry — an abstained probe can never launder a
candidate into the fact tier, STRICTER than RECALL_FRESH); the `admit_text`
boundary against a real throwaway repo; and the `dos memory admit` CLI
(stdin + --text-file, exit codes, JSON shape).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dos.config import default_config
from dos.drivers.memory_recall import (
    Admission,
    ClaimEvidence,
    ClaimKind,
    MemoryClaim,
    Polarity,
    ProbeStatus,
    RecallEvidence,
    admit_text,
    classify_admission,
    interpret_admission,
)


def _claim(kind=ClaimKind.CODE_TOKEN, polarity=Polarity.ASSERTS_PRESENT,
           raw="tok", target="f.py"):
    return MemoryClaim(raw=raw, kind=kind, polarity=polarity, target_file=target)


def _ev(*evidences: ClaimEvidence, mem_type: str = "project") -> RecallEvidence:
    return RecallEvidence(mem_name="m", mem_type=mem_type, evidences=tuple(evidences))


# ---------------------------------------------------------------------------
# classify_admission — the pure ladder on frozen evidence.
# ---------------------------------------------------------------------------


def test_opinion_typed_admits_opinion_even_with_contradicted_claim():
    """Rung 0 is structural: a feedback note admits OPINION unconditionally —
    an incidental contradicted path inside a preference can't poison it."""
    bad = ClaimEvidence(_claim(), ProbeStatus.CONTRADICTS, "gone", "grep")
    v = classify_admission(_ev(bad, mem_type="feedback"))
    assert v.admission is Admission.ADMIT_OPINION


def test_any_contradiction_is_poison_worst_wins():
    """One contradicted claim among nine confirmed → POISON (no majority vote)."""
    good = [ClaimEvidence(_claim(raw=f"t{i}"), ProbeStatus.CONFIRMS, "ok", "grep")
            for i in range(9)]
    bad = ClaimEvidence(_claim(raw="liar"), ProbeStatus.CONTRADICTS, "moved", "grep")
    v = classify_admission(_ev(*good, bad))
    assert v.admission is Admission.REJECT_POISON
    assert v.culprit is not None and v.culprit.claim.raw == "liar"
    assert "refusing the write" in v.reason


def test_nothing_probeable_admits_opinion():
    v = classify_admission(_ev())  # no claims at all
    assert v.admission is Admission.ADMIT_OPINION
    only_opinion = ClaimEvidence(
        _claim(kind=ClaimKind.OPINION, polarity=Polarity.NEUTRAL), ProbeStatus.UNKNOWN)
    v = classify_admission(_ev(only_opinion))
    assert v.admission is Admission.ADMIT_OPINION


def test_all_confirmed_is_witnessed():
    good = ClaimEvidence(_claim(), ProbeStatus.CONFIRMS, "present", "grep")
    v = classify_admission(_ev(good))
    assert v.admission is Admission.ADMIT_WITNESSED
    assert v.culprit is None


def test_abstained_probe_downgrades_to_as_claim_not_witnessed():
    """The write/read asymmetry: RECALL_FRESH ignores abstentions, but fact
    authority at WRITE requires the whole probed set witnessed — an UNKNOWN
    can never launder a candidate into the fact tier."""
    good = ClaimEvidence(_claim(raw="seen"), ProbeStatus.CONFIRMS, "ok", "grep")
    dunno = ClaimEvidence(_claim(raw="maybe"), ProbeStatus.UNKNOWN, "", "none")
    v = classify_admission(_ev(good, dunno))
    assert v.admission is Admission.ADMIT_AS_CLAIM
    assert "DATED CLAIM" in v.reason


def test_all_unknown_is_as_claim():
    """Checkable referents named but nothing provable either way → AS_CLAIM
    (not OPINION — recall has something to re-probe later)."""
    dunno = ClaimEvidence(_claim(), ProbeStatus.UNKNOWN, "", "none")
    v = classify_admission(_ev(dunno))
    assert v.admission is Admission.ADMIT_AS_CLAIM


def test_interpret_admission_covers_every_verdict():
    for adm, must_contain in [
        (Admission.ADMIT_WITNESSED, "fact authority"),
        (Admission.ADMIT_AS_CLAIM, "DATED CLAIM"),
        (Admission.ADMIT_OPINION, "never dress it as verified"),
        (Admission.REJECT_POISON, "Do not store it"),
    ]:
        line = interpret_admission({"admission": adm.value})
        assert must_contain in line, (adm, line)


# ---------------------------------------------------------------------------
# admit_text — the boundary, against a real throwaway repo.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    _git_dir = tmp_path
    _git_dir.mkdir(parents=True, exist_ok=True)
    _git(_git_dir, "init")
    _git(_git_dir, "config", "user.email", "t@t")
    _git(_git_dir, "config", "user.name", "t")
    (_git_dir / "app.py").write_text("from os import path\n", encoding="utf-8")
    _git(_git_dir, "add", "app.py")
    _git(_git_dir, "commit", "-q", "-m", "init")
    return _git_dir


_FM = "---\nname: cand\ndescription: t\nmetadata:\n  type: project\n---\n\n"


def test_admit_text_witnessed_on_a_true_claim(tmp_path: Path):
    """`app.py:1` is the file anchor the extraction grammar binds a backticked
    token to (`_FILE_REF` wants `file:line`; the line is advisory, never probed)."""
    cfg = default_config(_repo(tmp_path))
    v = admit_text(_FM + "app.py:1 does `from os import path` today.", cfg=cfg)
    assert v.admission is Admission.ADMIT_WITNESSED


def test_admit_text_poison_on_a_false_claim(tmp_path: Path):
    """The headline case: a candidate asserting code that is not there — the
    over-claim a hosted memory pipeline would auto-extract — refuses at birth."""
    cfg = default_config(_repo(tmp_path))
    v = admit_text(_FM + "app.py:1 does `from os import nonexistent_widget` now.", cfg=cfg)
    assert v.admission is Admission.REJECT_POISON
    assert v.culprit is not None
    assert "nonexistent_widget" in v.culprit.claim.raw


def test_admit_text_opinion_on_uncheckable_prose(tmp_path: Path):
    cfg = default_config(_repo(tmp_path))
    v = admit_text(_FM + "Prefer short sentences over long ones.", cfg=cfg)
    assert v.admission is Admission.ADMIT_OPINION


# ---------------------------------------------------------------------------
# The CLI surface — stdin + --text-file, exit codes, JSON.
# ---------------------------------------------------------------------------


def _cli_admit(repo: Path, *argv: str, stdin: str = "") -> subprocess.CompletedProcess:
    # `--workspace` lives on the SUBparser, so it follows `admit`.
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "memory", "admit",
         "--workspace", str(repo), *argv],
        input=stdin, capture_output=True, text=True,
    )


def test_cli_admit_stdin_witnessed_exits_zero(tmp_path: Path):
    repo = _repo(tmp_path)
    proc = _cli_admit(repo, "--json",
                      stdin=_FM + "app.py:1 does `from os import path` today.")
    assert proc.returncode == 0, proc.stderr
    d = json.loads(proc.stdout)
    assert d["admission"] == "ADMIT_WITNESSED"


def test_cli_admit_poison_exits_three_with_culprit(tmp_path: Path):
    repo = _repo(tmp_path)
    proc = _cli_admit(repo, "--json",
                      stdin=_FM + "app.py:1 does `from os import gone_widget` now.")
    assert proc.returncode == 3, (proc.stdout, proc.stderr)
    d = json.loads(proc.stdout)
    assert d["admission"] == "REJECT_POISON"
    assert d["culprit"]["claim"]["raw"] == "from os import gone_widget"


def test_cli_admit_text_file(tmp_path: Path):
    repo = _repo(tmp_path)
    cand = tmp_path / "cand.md"
    cand.write_text(_FM + "Prefer plain words.", encoding="utf-8")
    proc = _cli_admit(repo, "--text-file", str(cand), "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["admission"] == "ADMIT_OPINION"


def test_cli_admit_empty_candidate_is_a_usage_error(tmp_path: Path):
    repo = _repo(tmp_path)
    proc = _cli_admit(repo, stdin="")
    assert proc.returncode == 2
    assert "empty candidate" in proc.stderr
