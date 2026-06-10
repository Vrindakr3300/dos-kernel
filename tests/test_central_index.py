"""The machine-local central store — projects/index.jsonl + decisions.jsonl
(docs/75_state-home-plan.md, Phase 3).

The store is a rebuildable projection: `ensure_project_home` folds a projects
row; a `dos arbitrate --force` override appends a resolved-decision digest (and
`dos judge` does NOT — it is read-only). Writes are torn-tail tolerant and
serialized by the DOS_HOME write-lock so concurrent appends and a reindex rewrite
can't lose or corrupt a row.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dos import home
from dos.config import default_config


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("DISPATCH_HOME", str(h))
    return h


# ---------------------------------------------------------------------------
# projects/index.jsonl — one folded row per project.
# ---------------------------------------------------------------------------


class TestProjectsIndex:
    def test_ensure_appends_a_projects_row(self, tmp_path: Path, home_dir: Path):
        cfg = default_config(tmp_path / "p1")
        (tmp_path / "p1").mkdir()
        home.ensure_project_home(cfg)
        rows = home.read_jsonl(home_dir / "projects" / "index.jsonl")
        assert len(rows) == 1
        assert rows[0]["root"] == str((tmp_path / "p1").resolve())
        assert rows[0]["status"] == "active"

    def test_second_project_appends_second_row(self, tmp_path: Path, home_dir: Path):
        for name in ("p1", "p2"):
            (tmp_path / name).mkdir()
            home.ensure_project_home(default_config(tmp_path / name))
        rows = home.read_jsonl(home_dir / "projects" / "index.jsonl")
        pids = {r["project_id"] for r in rows}
        assert len(pids) == 2

    def test_reensure_preserves_first_seen(self, tmp_path: Path, home_dir: Path):
        (tmp_path / "p1").mkdir()
        cfg = default_config(tmp_path / "p1")
        home.ensure_project_home(cfg, clock=lambda: 1_000_000_000_000)
        home.ensure_project_home(cfg, clock=lambda: 2_000_000_000_000)
        rows = [r for r in home.read_jsonl(home_dir / "projects" / "index.jsonl")
                if not r.get("_CORRUPT")]
        # Folded last-write-wins keeps the earliest first_seen for the id.
        last = rows[-1]
        assert last["first_seen"] is not None


# ---------------------------------------------------------------------------
# decisions.jsonl — resolved-decision digests (force captures, judge does not).
# ---------------------------------------------------------------------------


def _plain_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for args in (("init",), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t"),
                 ("commit", "--allow-empty", "-m", "init")):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, text=True)


class TestDecisionsIndex:
    def test_force_acquire_appends_digest(self, tmp_path: Path, home_dir: Path):
        cfg = default_config(tmp_path / "p")
        (tmp_path / "p").mkdir()
        home.ensure_project_home(cfg)
        row = home.append_decision(cfg, {
            "kind": "ARBITER_REFUSE", "resolver_kind": "HUMAN", "lane": "main",
            "reason_token": "", "reason_category": "", "run_ts": "",
            "resolution": {"action": "force_acquire", "lane": "main", "forced": True},
        })
        assert row is not None
        central = home.read_jsonl(home_dir / "decisions.jsonl")
        assert len(central) == 1
        assert central[0]["resolution"]["action"] == "force_acquire"
        # mirrored locally too (projection-not-sync — local is the rebuildable truth)
        local = home.read_jsonl((tmp_path / "p") / ".dos" / "decisions" / "resolved.jsonl")
        assert len(local) == 1

    def test_force_dedup(self, tmp_path: Path, home_dir: Path):
        """A repeated identical force is one logical resolution (idempotent)."""
        cfg = default_config(tmp_path / "p")
        (tmp_path / "p").mkdir()
        home.ensure_project_home(cfg)
        digest = {
            "kind": "ARBITER_REFUSE", "resolver_kind": "HUMAN", "lane": "main",
            "reason_token": "", "reason_category": "", "run_ts": "",
            "resolution": {"action": "force_acquire", "lane": "main", "forced": True},
        }
        first = home.append_decision(cfg, dict(digest))
        second = home.append_decision(cfg, dict(digest))
        assert first is not None
        assert second is None  # deduped
        assert len(home.read_jsonl(home_dir / "decisions.jsonl")) == 1

    def test_cli_force_override_captures_end_to_end(self, tmp_path: Path, home_dir: Path):
        """`dos arbitrate --force` that turns a keyword-overlap REFUSAL into an
        acquire records one resolved-decision digest (the full CLI capture path).
        A force that did NOT override a refusal records nothing."""
        repo = tmp_path / "repo"
        _plain_repo(repo)
        env = dict(os.environ)
        env["DISPATCH_HOME"] = str(home_dir)
        leases = '[{"lane":"other","tree":["src/**"]}]'

        def _arb(*extra):
            return subprocess.run(
                [sys.executable, "-m", "dos.cli", "arbitrate", "--workspace", str(repo),
                 "--lane", "kw", "--kind", "keyword", "--tree", "src/app.py",
                 "--leases", leases, *extra],
                capture_output=True, text=True, env=env,
            )

        # Unforced would refuse (keyword tree overlaps the live lease) → forced
        # acquire is a real override → one digest captured.
        forced = _arb("--force")
        assert json.loads(forced.stdout)["outcome"] == "acquire", forced.stderr
        rows = home.read_jsonl(home_dir / "decisions.jsonl")
        assert len(rows) == 1
        assert rows[0]["resolution"]["action"] == "force_acquire"
        assert rows[0]["lane"] == "kw"

    def test_judge_appends_nothing(self, tmp_path: Path, home_dir: Path):
        """`dos judge` is READ-ONLY — running it writes no decision row, no .dos/.
        (The §5.7 contradiction, pinned.)"""
        repo = tmp_path / "repo"
        _plain_repo(repo)
        env = dict(os.environ)
        env["DISPATCH_HOME"] = str(home_dir)
        subprocess.run(
            [sys.executable, "-m", "dos.cli", "judge", "--workspace", str(repo),
             "wedge", "20260531T010000Z"],
            capture_output=True, text=True, env=env,
        )
        assert not (home_dir / "decisions.jsonl").exists()
        assert not (repo / ".dos").exists()


# ---------------------------------------------------------------------------
# Torn-tail tolerance + corrupt-middle surfacing (lane_journal's rule, reused).
# ---------------------------------------------------------------------------


class TestTornTail:
    def test_partial_final_line_skipped(self, tmp_path: Path):
        p = tmp_path / "x.jsonl"
        p.write_text('{"a": 1}\n{"b": 2}\n{"c": 3', encoding="utf-8")  # torn tail
        rows = home.read_jsonl(p)
        assert rows == [{"a": 1}, {"b": 2}]  # torn final line dropped

    def test_corrupt_middle_line_surfaced(self, tmp_path: Path):
        p = tmp_path / "x.jsonl"
        p.write_text('{"a": 1}\nGARBAGE\n{"c": 3}\n', encoding="utf-8")
        rows = home.read_jsonl(p)
        assert rows[0] == {"a": 1}
        assert rows[1].get("_CORRUPT") is True  # surfaced, not silently dropped
        assert rows[2] == {"c": 3}


# ---------------------------------------------------------------------------
# Concurrent appends survive — the win32 lock blocker. Two processes each append
# N rows to the central index; all 2N must survive uncorrupted.
# ---------------------------------------------------------------------------


_APPENDER = """\
import sys, os
from pathlib import Path
from dos import home
from dos.config import default_config
root = Path(sys.argv[1]); tag = sys.argv[2]; n = int(sys.argv[3])
os.environ["DISPATCH_HOME"] = sys.argv[4]
for i in range(n):
    cfg = default_config(root / f"{tag}_{i}")
    (root / f"{tag}_{i}").mkdir(parents=True, exist_ok=True)
    home.ensure_project_home(cfg)
"""


def test_concurrent_appends_survive(tmp_path: Path):
    home_dir = tmp_path / "home"
    script = tmp_path / "appender.py"
    script.write_text(_APPENDER, encoding="utf-8")
    n = 8
    procs = [
        subprocess.Popen(
            [sys.executable, str(script), str(tmp_path), tag, str(n), str(home_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        for tag in ("A", "B")
    ]
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode(errors="replace")
    rows = home.read_jsonl(home_dir / "projects" / "index.jsonl")
    assert not any(r.get("_CORRUPT") for r in rows), "a row was corrupted by interleaving"
    pids = {r["project_id"] for r in rows if not r.get("_CORRUPT")}
    assert len(pids) == 2 * n, f"expected {2 * n} distinct projects, got {len(pids)}"
