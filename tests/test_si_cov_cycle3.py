"""SI cycle-3 coverage test: exercise the in-process-only branches of
`dos.run_id` (the CID-series run-id minter, docs/64).

The shipped suite reaches `run_id` only through its happy paths: `mint()` with
INJECTED `clock_ms`/`entropy` lambdas and `ts_ms_of()` (tests/test_liveness.py,
tests/test_drivers_watchdog.py, tests/test_proc_delta.py), plus the
`dos run-id ...` CLI subprocess. coverage.py does not record subprocess-executed
lines in this repo, and the injected lambdas mean the module's DEFAULT callables
never run in-process either. So the following lines show as uncovered (verified
against `coverage report --show-missing` at this worktree's base):

  - 75              `_b32` negative-component ValueError
  - 99,114-115,
    127-131         the DEFAULT clock / counter / entropy callables (tests inject
                    lambdas, so the real defaults are never exercised in-process)
  - 182,195         `mint` empty-process ValueError + the string-parent branch
  - 209-214         `is_run_id` reject branches (non-str, no prefix, wrong len,
                    non-Crockford char)
  - 219-225         `ts_ms_of` invalid-token None branch (+ the decode loop)
  - 240-243         `lineage_env` (both with- and without-parent_id)
  - 260-263         `mint_child_from_env` (parent-present and root-fallback)
  - 287-289,
    299-300         `write_run_json` / `read_run_json` corrupt-file branch
  - 304-309,314-319,
    323-338         the `_cmd_mint` / `_cmd_show` / `main` argparse dispatch
                    (driven IN-PROCESS via `main(argv)`, no subprocess)

Every input is a frozen literal or a `tmp_path` fixture. Clock/entropy are pinned
to constants where minting is observed, so the assertions are exact and the test
is deterministic. No network, no sleeps, no writes to tracked paths (only
`tmp_path`). Each branch is asserted on its real observable behavior — this is
not a coverage-only no-op. Line 342 (`if __name__ == "__main__"`) is unreachable
from an import and is intentionally left untouched.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from dos import run_id as r


# ---------------------------------------------------------------------------
# Encoder + default callables
# ---------------------------------------------------------------------------
def test_b32_rejects_negative() -> None:
    with pytest.raises(ValueError):
        r._b32(-1, width=4)


def test_b32_zero_is_zero_padded() -> None:
    # Happy reference so the negative-reject test isn't the only b32 assertion.
    assert r._b32(0, width=r._ENTROPY_WIDTH) == "0" * r._ENTROPY_WIDTH


def test_default_clock_ms_is_positive_epoch_ms() -> None:
    # Exercises the real default clock (tests elsewhere inject a lambda).
    assert r._default_clock_ms() > 1_700_000_000_000  # well after 2023


def test_default_mint_seq_is_strictly_increasing() -> None:
    a = r._next_mint_seq()
    b = r._next_mint_seq()
    assert b > a


def test_default_entropy_in_range() -> None:
    e = r._default_entropy()
    assert 0 <= e < (1 << r._ENTROPY_BITS)


# ---------------------------------------------------------------------------
# mint() — error + string-parent branches
# ---------------------------------------------------------------------------
def test_mint_requires_process_id() -> None:
    with pytest.raises(ValueError):
        r.mint("")


def test_mint_with_string_parent_is_root_of_itself() -> None:
    # The `else` branch: parent given as a bare run_id string (not a RunId).
    run = r.mint("worker", parent="RID-PARENTSTRING0", clock_ms=lambda: 0, entropy=lambda: 0)
    assert run.parent_id == "RID-PARENTSTRING0"
    # No root supplied + string parent => the run is its own root.
    assert run.root_id == run.run_id


def test_mint_with_runid_parent_inherits_root() -> None:
    parent = r.mint("root", clock_ms=lambda: 0, entropy=lambda: 1)
    child = r.mint("child", parent=parent, clock_ms=lambda: 5, entropy=lambda: 2)
    assert child.parent_id == parent.run_id
    assert child.root_id == parent.root_id


# ---------------------------------------------------------------------------
# is_run_id() / ts_ms_of() — reject + decode branches
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [
        123,  # not a str
        "XX-abcdefghijklmno",  # wrong prefix
        "RID-short",  # wrong body length
        "RID-" + "U" * (r._TS_WIDTH + r._ENTROPY_WIDTH),  # 'U' excluded from Crockford
    ],
)
def test_is_run_id_rejects(bad: object) -> None:
    assert r.is_run_id(bad) is False


def test_is_run_id_accepts_a_minted_token() -> None:
    run = r.mint("p", clock_ms=lambda: 1234567, entropy=lambda: 7)
    assert r.is_run_id(run.run_id) is True


def test_ts_ms_of_roundtrips_and_rejects() -> None:
    run = r.mint("p", clock_ms=lambda: 987654321, entropy=lambda: 0)
    assert r.ts_ms_of(run.run_id) == 987654321
    assert r.ts_ms_of("not-a-rid") is None


# ---------------------------------------------------------------------------
# Lineage transport across a subprocess boundary
# ---------------------------------------------------------------------------
def test_lineage_env_omits_parent_for_a_root() -> None:
    root = r.mint("root", clock_ms=lambda: 0, entropy=lambda: 0)
    env = r.lineage_env(root)
    assert env[r.ENV_RUN_ID] == root.run_id
    assert env[r.ENV_ROOT_ID] == root.root_id
    assert env[r.ENV_PROCESS_ID] == root.process_id
    assert r.ENV_PARENT_ID not in env  # a root has no parent_id


def test_lineage_env_includes_parent_for_a_child() -> None:
    root = r.mint("root", clock_ms=lambda: 0, entropy=lambda: 0)
    child = r.mint("child", parent=root, clock_ms=lambda: 1, entropy=lambda: 1)
    env = r.lineage_env(child)
    assert env[r.ENV_PARENT_ID] == root.run_id


def test_mint_child_from_env_inherits_parent_and_root() -> None:
    e = {
        r.ENV_RUN_ID: "RID-AAAAAAAAAAAAAAA",
        r.ENV_ROOT_ID: "RID-ROOTROOTROOTRO",
    }
    child = r.mint_child_from_env("worker", env=e, clock_ms=lambda: 9, entropy=lambda: 3)
    assert child.parent_id == "RID-AAAAAAAAAAAAAAA"
    assert child.root_id == "RID-ROOTROOTROOTRO"


def test_mint_child_from_env_empty_is_a_root() -> None:
    child = r.mint_child_from_env("worker", env={}, clock_ms=lambda: 9, entropy=lambda: 3)
    assert child.parent_id is None
    assert child.root_id == child.run_id  # self-root fallback


# ---------------------------------------------------------------------------
# run.json write / read round-trip + corrupt-file branch
# ---------------------------------------------------------------------------
def test_write_then_read_run_json_roundtrips(tmp_path: Path) -> None:
    run = r.mint("fanout", clock_ms=lambda: 42, entropy=lambda: 5)
    run_dir = tmp_path / "rundir"
    written = r.write_run_json(run_dir, run)
    assert written == run_dir / r.RUN_JSON_NAME
    assert r.read_run_json(run_dir) == run.to_dict()


def test_read_run_json_absent_is_none(tmp_path: Path) -> None:
    assert r.read_run_json(tmp_path / "nope") is None


def test_read_run_json_corrupt_is_none(tmp_path: Path) -> None:
    run_dir = tmp_path / "rundir"
    run_dir.mkdir()
    (run_dir / r.RUN_JSON_NAME).write_text("{ not json", encoding="utf-8")
    assert r.read_run_json(run_dir) is None


# ---------------------------------------------------------------------------
# CLI dispatch — driven IN-PROCESS via main(argv); no subprocess.
# ---------------------------------------------------------------------------
def test_main_mint_prints_token_json() -> None:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = r.main(["mint", "fanout"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert out["run_id"].startswith(r.PREFIX)
    assert out["process_id"] == "PROC-fanout"
    assert out["parent_id"] is None


def test_main_mint_with_write_dir_stamps_run_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "rundir"
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = r.main(
            [
                "mint",
                "dispatch",
                "--parent",
                "RID-PPPPPPPPPPPPPPP",
                "--root",
                "RID-RRRRRRRRRRRRRRR",
                "--write-dir",
                str(run_dir),
            ]
        )
    assert rc == 0
    written = r.read_run_json(run_dir)
    assert written is not None
    assert written["parent_id"] == "RID-PPPPPPPPPPPPPPP"
    assert written["root_id"] == "RID-RRRRRRRRRRRRRRR"
    assert f"wrote {run_dir / r.RUN_JSON_NAME}" in err_buf.getvalue()


def test_main_show_resolves_a_run_dir(tmp_path: Path) -> None:
    run = r.mint("fanout", clock_ms=lambda: 7, entropy=lambda: 1)
    run_dir = tmp_path / "rundir"
    r.write_run_json(run_dir, run)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = r.main(["show", str(run_dir)])
    assert rc == 0
    assert json.loads(buf.getvalue()) == run.to_dict()


def test_main_show_missing_run_json_returns_1(tmp_path: Path) -> None:
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        rc = r.main(["show", str(tmp_path / "absent")])
    assert rc == 1
    assert err_buf.getvalue().strip()  # an explanatory message went to stderr
