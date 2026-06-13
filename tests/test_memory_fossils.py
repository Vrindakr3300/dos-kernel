"""docs/314 P4 (issue #100) — verification-memory fossils.

The kernel remembering its own memory adjudications: `memory recall/verify/
admit` journal their verdicts to the verdict WAL (docs/262); a sweep consults
the journal FIRST, so a memory already adjudicated STALE and byte-unchanged
since is reported from the fossil instead of re-probed (the cooldown
analogue); a verdict history that RESURRECTED on unchanged bytes
(STALE → later FRESH, same sha) is surfaced as a flap — claim history is
itself evidence.

Pins the issue's done-condition: two consecutive sweeps probe once (the
second answers the STALE row from the journal), the rows ride the versioned
verdict-journal schema, and a flap fixture surfaces the suspect. Plus the
fail-safe direction: a malformed fossil falls back to a live re-probe, FRESH
is never replayed, an edited memory always re-probes, and `--reprobe` /
`consult_fossils=False` forces the full pass.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dos import verdict_journal
from dos.config import default_config
from dos.drivers import memory_recall as mr


# ---------------------------------------------------------------------------
# Fixtures — a real throwaway repo + a file store with one stale, one fresh.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir(parents=True, exist_ok=True)
    _git(d, "init")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    (d / "app.py").write_text("from os import path\n", encoding="utf-8")
    _git(d, "add", "app.py")
    _git(d, "commit", "-q", "-m", "init")
    return d


_FM = "---\nname: {name}\ndescription: t\nmetadata:\n  type: project\n---\n\n"
_STALE_BODY = _FM.format(name="liar") + \
    "app.py:1 does `from os import gone_widget` now."
_FRESH_BODY = _FM.format(name="honest") + \
    "app.py:1 does `from os import path` today."


def _store(tmp_path: Path) -> Path:
    s = tmp_path / "memory"
    s.mkdir(exist_ok=True)
    (s / "liar.md").write_text(_STALE_BODY, encoding="utf-8")
    (s / "honest.md").write_text(_FRESH_BODY, encoding="utf-8")
    return s


def _setup(tmp_path: Path):
    repo = _repo(tmp_path)
    return default_config(repo), _store(tmp_path)


def _rows(cfg):
    return verdict_journal.read_events(cfg.paths.verdict_journal)


# ---------------------------------------------------------------------------
# Journaling — schema-tagged rows, change-only.
# ---------------------------------------------------------------------------


def test_sweep_journals_schema_tagged_rows(tmp_path: Path):
    cfg, store = _setup(tmp_path)
    mr.sweep(cfg=cfg, store=str(store))
    rows = _rows(cfg)
    by_name = {r.subject: r for r in rows if r.syscall == mr.FOSSIL_SYSCALL_RECALL}
    assert set(by_name) == {"liar", "honest"}
    assert by_name["liar"].verdict == "RECALL_STALE"
    assert by_name["honest"].verdict == "RECALL_FRESH"
    assert len(by_name["liar"].detail["content_sha256"]) == 64
    assert by_name["liar"].detail["culprit"]["claim"]["raw"] == "from os import gone_widget"
    # the durable-schema tag rides every raw record (docs/262)
    raw = verdict_journal.read_all(cfg.paths.verdict_journal)
    assert all(r.get("schema_family") == "verdict-journal" for r in raw)


def test_unchanged_resweep_appends_no_duplicate_rows(tmp_path: Path):
    """Change-only journaling: the journal holds TRANSITIONS, not sweep copies."""
    cfg, store = _setup(tmp_path)
    mr.sweep(cfg=cfg, store=str(store))
    n1 = len(_rows(cfg))
    mr.sweep(cfg=cfg, store=str(store))
    assert len(_rows(cfg)) == n1


def test_admit_journals_an_admission_row(tmp_path: Path):
    cfg, _ = _setup(tmp_path)
    v = mr.admit_text(_STALE_BODY, cfg=cfg)
    assert v.admission is mr.Admission.REJECT_POISON
    rows = [r for r in _rows(cfg) if r.syscall == mr.FOSSIL_SYSCALL_ADMIT]
    assert len(rows) == 1
    assert rows[0].verdict == "REJECT_POISON"
    assert rows[0].subject == "liar"


def test_journal_false_writes_nothing(tmp_path: Path):
    cfg, store = _setup(tmp_path)
    mr.sweep(cfg=cfg, store=str(store), journal=False)
    mr.admit_text(_FRESH_BODY, cfg=cfg, journal=False)
    assert _rows(cfg) == []


# ---------------------------------------------------------------------------
# Consult-before-re-probe — the issue's headline done-condition.
# ---------------------------------------------------------------------------


def _counting_gather(monkeypatch):
    calls: list[str] = []
    orig = mr.gather_text

    def wrapper(text, *, fallback_name, cfg, now_ms):
        calls.append(fallback_name)
        return orig(text, fallback_name=fallback_name, cfg=cfg, now_ms=now_ms)

    monkeypatch.setattr(mr, "gather_text", wrapper)
    return calls


def test_second_sweep_answers_stale_from_the_fossil(tmp_path: Path, monkeypatch):
    cfg, store = _setup(tmp_path)
    calls = _counting_gather(monkeypatch)
    v1 = mr.sweep(cfg=cfg, store=str(store))
    assert len(calls) == 2  # both memories probed live
    assert v1[0].evidence.mem_name == "liar" and v1[0].fossil_ts == ""

    calls.clear()
    v2 = mr.sweep(cfg=cfg, store=str(store))
    # the STALE memory answered from the journal; only FRESH re-probed
    assert calls == ["honest"]
    stale = next(v for v in v2 if v.evidence.mem_name == "liar")
    assert stale.verdict is mr.Recall.RECALL_STALE
    assert stale.fossil_ts != ""
    assert "fossil" in stale.reason
    # the replayed culprit still carries the ground-truth proof
    assert stale.culprit is not None
    assert stale.culprit.claim.raw == "from os import gone_widget"


def test_fresh_is_never_replayed_from_a_fossil(tmp_path: Path, monkeypatch):
    """A fresh claim can age into a lie while the memory sits still — FRESH
    always re-probes; only STALE is sticky."""
    cfg, store = _setup(tmp_path)
    mr.sweep(cfg=cfg, store=str(store))
    calls = _counting_gather(monkeypatch)
    mr.sweep(cfg=cfg, store=str(store))
    assert "honest" in calls


def test_edited_memory_reprobes_despite_a_stale_fossil(tmp_path: Path, monkeypatch):
    cfg, store = _setup(tmp_path)
    mr.sweep(cfg=cfg, store=str(store))
    # the repair path: fix the claim → bytes change → fossil no longer binds
    (store / "liar.md").write_text(
        _FM.format(name="liar") + "app.py:1 does `from os import path` today.",
        encoding="utf-8")
    calls = _counting_gather(monkeypatch)
    v = mr.sweep(cfg=cfg, store=str(store))
    assert "liar" in calls
    fixed = next(x for x in v if x.evidence.mem_name == "liar")
    assert fixed.verdict is mr.Recall.RECALL_FRESH and fixed.fossil_ts == ""


def test_reprobe_forces_the_full_pass(tmp_path: Path, monkeypatch):
    cfg, store = _setup(tmp_path)
    mr.sweep(cfg=cfg, store=str(store))
    calls = _counting_gather(monkeypatch)
    v = mr.sweep(cfg=cfg, store=str(store), consult_fossils=False)
    assert sorted(calls) == ["honest", "liar"]
    assert all(x.fossil_ts == "" for x in v)


def test_malformed_fossil_falls_back_to_a_live_probe(tmp_path: Path, monkeypatch):
    """Fail-toward-re-probing: a fossil can SKIP work, never mint a bad verdict."""
    cfg, store = _setup(tmp_path)
    mr.sweep(cfg=cfg, store=str(store))
    # corrupt the culprit's closed-enum token in the newest liar row
    rows = verdict_journal.read_all(cfg.paths.verdict_journal)
    for r in rows:
        if r.get("subject") == "liar":
            r["detail"]["culprit"]["claim"]["kind"] = "BOGUS_KIND"
    p = Path(cfg.paths.verdict_journal)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    calls = _counting_gather(monkeypatch)
    v = mr.sweep(cfg=cfg, store=str(store))
    assert "liar" in calls  # re-probed, not replayed
    stale = next(x for x in v if x.evidence.mem_name == "liar")
    assert stale.verdict is mr.Recall.RECALL_STALE and stale.fossil_ts == ""


def test_recall_one_always_reprobes_but_journals_change_only(tmp_path: Path, monkeypatch):
    cfg, store = _setup(tmp_path)
    mr.recall_one("liar", cfg=cfg, store=str(store))
    n1 = len(_rows(cfg))
    assert n1 == 1
    calls = _counting_gather(monkeypatch)
    v = mr.recall_one("liar", cfg=cfg, store=str(store))
    assert calls == ["liar"]  # a deliberate one-memory recall re-probes
    assert v.fossil_ts == ""
    assert len(_rows(cfg)) == n1  # …but an unchanged verdict appends nothing


# ---------------------------------------------------------------------------
# Flap detection — resurrection on UNCHANGED bytes is suspicious; repair is not.
# ---------------------------------------------------------------------------


def _ev(subject: str, verdict: str, sha: str):
    return verdict_journal.VerdictEvent(
        syscall=mr.FOSSIL_SYSCALL_RECALL, verdict=verdict, subject=subject,
        detail={"content_sha256": sha})


def test_flap_suspects_flags_resurrection_on_unchanged_bytes():
    rows = [_ev("m", "RECALL_FRESH", "aa"), _ev("m", "RECALL_STALE", "aa"),
            _ev("m", "RECALL_FRESH", "aa")]
    flagged = mr.flap_suspects(rows)
    assert flagged == {"m": ("RECALL_FRESH", "RECALL_STALE", "RECALL_FRESH")}


def test_flap_suspects_ignores_the_repair_path():
    """STALE → (edit) → FRESH with a NEW sha is the documented fix flow."""
    rows = [_ev("m", "RECALL_STALE", "aa"), _ev("m", "RECALL_FRESH", "bb")]
    assert mr.flap_suspects(rows) == {}


def test_flap_suspects_ignores_monotone_histories():
    rows = [_ev("a", "RECALL_FRESH", "aa"), _ev("a", "RECALL_STALE", "aa"),
            _ev("b", "RECALL_FRESH", "cc")]
    assert mr.flap_suspects(rows) == {}


def test_flap_surfaces_through_the_live_journal(tmp_path: Path):
    """Integration: ground truth oscillates under an unchanged memory → the
    sweep's flap surface names it."""
    cfg, store = _setup(tmp_path)
    repo = cfg.paths.root
    mr.sweep(cfg=cfg, store=str(store))  # liar → STALE
    # ground truth moves TOWARD the claim: the missing import appears
    (repo / "app.py").write_text(
        "from os import path\nfrom os import gone_widget\n", encoding="utf-8")
    v = mr.recall_one("liar", cfg=cfg, store=str(store))  # re-probes → FRESH
    assert v.verdict is mr.Recall.RECALL_FRESH
    flaps = mr.flap_suspects_for(cfg)
    assert "liar" in flaps


# ---------------------------------------------------------------------------
# CLI — fossil provenance + flap history ride the JSON; --reprobe forces.
# ---------------------------------------------------------------------------


def _cli_verify(repo: Path, store: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", "memory", "verify",
         "--workspace", str(repo), "--store", str(store), *argv],
        capture_output=True, text=True,
    )


def test_cli_second_verify_carries_fossil_ts(tmp_path: Path):
    cfg, store = _setup(tmp_path)
    repo = cfg.paths.root
    p1 = _cli_verify(repo, store, "--json")
    assert p1.returncode == 0, p1.stderr
    first = {d["memory"]: d for d in json.loads(p1.stdout)}
    assert first["liar"]["fossil_ts"] == ""
    p2 = _cli_verify(repo, store, "--json")
    second = {d["memory"]: d for d in json.loads(p2.stdout)}
    assert second["liar"]["verdict"] == "RECALL_STALE"
    assert second["liar"]["fossil_ts"] != ""
    # and --reprobe forces the live pass again
    p3 = _cli_verify(repo, store, "--json", "--reprobe")
    third = {d["memory"]: d for d in json.loads(p3.stdout)}
    assert third["liar"]["fossil_ts"] == ""
    # the text renderer marks the fossil row
    p4 = _cli_verify(repo, store)
    assert "[fossil]" in p4.stdout
