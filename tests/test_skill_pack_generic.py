"""SKP Phase 2 — the generic `dos-next-up` skill is realizable on a FOREIGN repo.

A SKILL.md is a screenplay, not executable code, so this test does two things:

  1. **Drives the skill's scripted steps** (Step 0 `dos doctor --json` → Step 1
     walk the plans glob → Step 2 `dos verify` per pick → Step 3 assemble a
     packet + the gate sidecar → Step 4 `dos gate`) against a throwaway foreign
     git repo with a GENERIC `[stamp]` and no job-specific config, and asserts a
     coherent packet with verify-backed statuses and a typed gate verdict. This
     proves the screenplay composes end-to-end out of `dos` verbs alone.

  2. **Greps the shipped SKILL.md** for the job literals SKP's design law forbids
     (`docs/_plans`, `output/next-up`, `apply`/`tailor`/`discovery`,
     `docs/dispatch:`) — the skill analogue of "kernel imports no host."

The foreign repo stamps a bare `<SERIES><PHASE>:` ship (the external-repo shape)
and declares `[stamp] subject_dirs = []` so `dos verify` recognises it — the SCV
seam the skill rides without knowing it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import dos


SKILL_DIR = Path(dos.__file__).parent / "skills"
NEXT_UP_SKILL = SKILL_DIR / "dos-next-up" / "SKILL.md"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _cli(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    # Pin the subprocess to the SAME `dos` source tree this test imported, so a
    # differently-positioned editable install on PATH (e.g. a sibling worktree
    # without the SCV stamp readback) can't make `dos verify` load the wrong
    # package and report a false NOT_SHIPPED. The child inherits our PYTHONPATH.
    import os
    env = {**os.environ, "PYTHONPATH": str(Path(dos.__file__).parents[1])}
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv, "--workspace", str(repo)],
        capture_output=True, text=True, env=env,
    )


def _foreign_repo(repo: Path) -> None:
    """A foreign repo: generic stamp, plans under `planning/`, one phase shipped
    with a bare `<SERIES><PHASE>:` subject (not a job `docs/<SERIES>:` subject)."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    # Generic stamp + a non-job plans glob — both declared as data (WCR + SCV).
    _write(repo / "dos.toml",
           "[lanes]\nconcurrent=['svc']\nexclusive=['global']\nautopick=['svc']\n"
           "[lanes.trees]\nsvc=['src/**']\nglobal=['**/*']\n"
           "[paths]\nplans_glob='planning/*.md'\n"
           "[stamp]\nstyle='grep'\nsubject_dirs=[]\n")
    _write(repo / "planning" / "auth-plan.md",
           "# AUTH plan\n\n## AUTH1 — wire the token store\n## AUTH2 — refresh tokens\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init: dos.toml + auth plan")
    # Ship AUTH1 with a bare external-repo subject; AUTH2 stays unshipped.
    _git(repo, "commit", "--allow-empty", "-q", "-m", "AUTH1: ship the token store")


# ===========================================================================
# (1) the screenplay is realizable end-to-end on a foreign repo
# ===========================================================================


def test_dos_next_up_foreign_repo(tmp_path: Path):
    """Drive the dos-next-up steps against a foreign repo and assert a coherent
    packet with verify-backed statuses + a typed gate verdict."""
    repo = tmp_path / "svc"
    _foreign_repo(repo)

    # --- Step 0: discover the layout (no hardcoded paths/lanes) -------------
    doctor = _cli(repo, "doctor", "--json")
    assert doctor.returncode == 0, doctor.stderr
    report = json.loads(doctor.stdout)
    assert report["paths"]["plans_glob"] == "planning/*.md"   # the DECLARED glob
    assert report["stamp"]["subject_dirs"] == []              # the generic grammar
    next_packets = Path(report["paths"]["next_packets"])

    # --- Step 1: walk the declared plans glob → candidate (plan, phase) -----
    plan_docs = sorted((repo).glob(report["paths"]["plans_glob"]))
    assert plan_docs, "the declared glob found the foreign repo's plan"
    candidates = [("AUTH", "AUTH1"), ("AUTH", "AUTH2")]

    # --- Step 2: audit each pick against the truth syscall ------------------
    dispositions = []
    live_picks = []
    for plan, phase in candidates:
        v = _cli(repo, "verify", plan, phase, "--json")
        verdict = json.loads(v.stdout)
        if verdict["shipped"]:
            dispositions.append({"phase": phase, "live": False,
                                 "drop_reason": "shipped",
                                 "ship_via": verdict["source"],
                                 "plan_doc_stamped": False})
        else:
            dispositions.append({"phase": phase, "live": True})
            live_picks.append((plan, phase))

    # AUTH1 shipped (bare subject, recognised via the generic grammar); AUTH2 not.
    shipped = [d for d in dispositions if not d["live"]]
    assert len(shipped) == 1 and shipped[0]["phase"] == "AUTH1", dispositions
    # `grep-subject` (docs/118): the git-log SUBJECT rung under generic [stamp].
    assert shipped[0]["ship_via"] == "grep-subject"
    assert live_picks == [("AUTH", "AUTH2")]

    # --- Step 3: assemble the packet + the gate sidecar ---------------------
    next_packets.mkdir(parents=True, exist_ok=True)
    packet = next_packets / "next-up-20260601-1.md"
    packet.write_text(
        f"# next-up — {repo}\n\n## Dispatch list\n"
        + "".join(f"- {p} {ph}\n" for p, ph in live_picks)
        + "\n## Already shipped\n- AUTH AUTH1 (via grep)\n",
        encoding="utf-8")
    sidecar = next_packets / ".dispositions-test.json"
    sidecar.write_text(json.dumps({
        "schema": "oc3-dispositions-v1", "tag": "test",
        "dispositions": dispositions,
    }), encoding="utf-8")

    # --- Step 4: gate the packet (typed verdict via the kernel) -------------
    gate = _cli(repo, "gate", str(sidecar))
    assert gate.returncode == 0, (gate.stdout, gate.stderr)   # LIVE — AUTH2 is dispatchable
    assert gate.stdout.startswith("LIVE")

    # the packet names the foreign repo's plan + phase with correct status
    text = packet.read_text(encoding="utf-8")
    assert "AUTH AUTH2" in text          # the live pick
    assert "AUTH AUTH1 (via grep)" in text  # the verify-backed shipped status


def test_dos_next_up_stale_stamp_is_reachable(tmp_path: Path):
    """The skill's CORRECTED Step-2/Step-3 classification can actually produce a
    STALE-STAMP — a `grep` ship the plan doc doesn't stamp maps to
    `ship_via: "direct"` + `plan_doc_stamped: false`, which `dos gate` classifies
    as STALE-STAMP (exit 4). This pins the must-fix from the final review: the
    false-drain the typed gate exists to catch is reachable from the skill's own
    sidecar instructions (it was unreachable when `ship_via` was verify's `source`)."""
    repo = tmp_path / "svc"
    _foreign_repo(repo)  # AUTH1 shipped via a bare `grep` subject; plan doc unstamped
    report = json.loads(_cli(repo, "doctor", "--json").stdout)
    next_packets = Path(report["paths"]["next_packets"])

    # Step 2: AUTH1 verifies shipped via grep; the plan doc carries no SHIPPED
    # stamp for it → the skill's stale-stamp disposition (ship_via=direct).
    v = json.loads(_cli(repo, "verify", "AUTH", "AUTH1", "--json").stdout)
    # `grep-subject` (docs/118): a bare-subject ship grades to the forgeable rung.
    assert v["shipped"] and v["source"] == "grep-subject", v
    dispositions = [{"phase": "AUTH1", "live": False, "drop_reason": "shipped",
                     "ship_via": "direct", "plan_doc_stamped": False}]

    next_packets.mkdir(parents=True, exist_ok=True)
    sidecar = next_packets / ".dispositions-stale.json"
    sidecar.write_text(json.dumps({
        "schema": "oc3-dispositions-v1", "tag": "stale",
        "dispositions": dispositions}), encoding="utf-8")

    gate = _cli(repo, "gate", str(sidecar))
    assert gate.returncode == 4, (gate.stdout, gate.stderr)  # STALE-STAMP, not DRAIN
    assert gate.stdout.startswith("STALE-STAMP")


def test_dos_next_up_drained_when_all_shipped(tmp_path: Path):
    """When every candidate verifies as shipped, the gate is DRAIN (exit 3) — the
    skill reports a genuine empty backlog, not a packet."""
    repo = tmp_path / "svc"
    _foreign_repo(repo)
    # Ship AUTH2 too.
    _git(repo, "commit", "--allow-empty", "-q", "-m", "AUTH2: ship token refresh")
    report = json.loads(_cli(repo, "doctor", "--json").stdout)
    next_packets = Path(report["paths"]["next_packets"])

    dispositions = []
    for phase in ("AUTH1", "AUTH2"):
        v = json.loads(_cli(repo, "verify", "AUTH", phase, "--json").stdout)
        assert v["shipped"], (phase, v)
        dispositions.append({"phase": phase, "live": False,
                             "drop_reason": "shipped", "ship_via": v["source"],
                             "plan_doc_stamped": False})
    next_packets.mkdir(parents=True, exist_ok=True)
    sidecar = next_packets / ".dispositions-drain.json"
    sidecar.write_text(json.dumps({
        "schema": "oc3-dispositions-v1", "tag": "drain",
        "dispositions": dispositions}), encoding="utf-8")
    gate = _cli(repo, "gate", str(sidecar))
    assert gate.returncode == 3, (gate.stdout, gate.stderr)
    assert gate.stdout.startswith("DRAIN")


# ===========================================================================
# (2) the shipped skill names no host literal (the design-law grep guard)
# ===========================================================================


def test_next_up_skill_ships_in_package():
    """The SKILL.md ships inside the `dos` package (discoverable by a consumer)."""
    assert NEXT_UP_SKILL.exists(), f"missing {NEXT_UP_SKILL}"


def test_next_up_skill_names_no_host_literal():
    """The shipped generic skill contains none of the job literals — the skill
    analogue of `kernel imports no host`."""
    text = NEXT_UP_SKILL.read_text(encoding="utf-8")
    forbidden = ["docs/_plans", "output/next-up", "docs/dispatch:"]
    for token in forbidden:
        assert token not in text, f"generic skill must not name {token!r}"
    # Job lane names must not appear as scope literals. (They may be absent
    # entirely; assert none is hardcoded as a lane the skill names.)
    for lane in ("apply", "tailor", "discovery"):
        # allow the word inside prose only if not used as a lane literal; the
        # simplest robust guard is full absence, which the generic skill honors.
        assert lane not in text, f"generic skill must not name job lane {lane!r}"
