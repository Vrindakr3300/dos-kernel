"""Pin the `examples/hermes_integration/` worked example against the real `dos` CLI.

docs/278 ships that example and claims its two headline numbers are *non-forgeable*
(witnessed off the filesystem / the store's own log, never the agent's self-report).
But the example is package-DATA that nothing imports, so nothing in the suite caught
it if a kernel change broke the CLI CONTRACT the adapter shells:

  * `dos exec-capability --command "<cmd>"` → exit 0 (BOUNDED/EMPTY) vs 3
    (GRANTS_ARBITRARY_EXEC), with the capability token first on stdout.
  * `dos arbitrate --lane R --tree R --leases <json> --output json` → an
    `{"outcome": "acquire"|"refuse", ...}` decision.
  * `dos lease-lane acquire/release …` → the durable WAL path, last-JSON-line verdict.

This test runs the adapter (`hermes_adapter`) and the demo arms (`run_safety_demo`,
`run_coord_demo`) THROUGH that real subprocess path and asserts the exact verdicts —
so a contract drift (a renamed flag, a changed exit code, a different JSON key)
reddens here instead of silently turning the example into a no-op. It is the
"a claim isn't shipped until a witness pins it" discipline (CLAUDE.md) applied to the
example itself.

The example shells the `dos` console script if it is on PATH, else falls back to
`python -m dos.cli`; in CI neither the console script nor an editable install is
guaranteed, so we make the fallback resolve by putting `src/` on `PYTHONPATH` for the
whole process (the same `_env()` shape the other CLI tests use). We import the demo
modules from the example dir (they use sibling imports), run their `main()`s, and
also exercise the adapter functions directly for the SHAPE-not-word + collision
properties.
"""

from __future__ import annotations

import importlib
import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "hermes_integration"
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(scope="module")
def example_env():
    """Make the example's `dos` CLI fallback (`python -m dos.cli`) resolve, and put
    the example dir on `sys.path` so its sibling imports work — both undone on exit.

    The adapter runs `python -m dos.cli` in a CHILD process, so the child needs `dos`
    importable: we prepend `src/` to this process's `PYTHONPATH`, which the child
    inherits. We also force UTF-8 + NO_COLOR so the parsed stdout is stable across
    platforms (the example parses the capability token / JSON off stdout)."""
    old_path = list(sys.path)
    old_environ = {k: os.environ.get(k) for k in ("PYTHONPATH", "NO_COLOR", "PYTHONIOENCODING")}

    sys.path.insert(0, str(_EXAMPLE_DIR))
    sep = os.pathsep
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(_SRC_DIR) + (sep + existing if existing else "")
    os.environ["NO_COLOR"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    yield

    sys.path[:] = old_path
    for key, val in old_environ.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val
    # Drop the example modules so a re-import in another test starts clean.
    for name in ("hermes_adapter", "shared_resource", "swarm_agent",
                 "run_safety_demo", "run_coord_demo", "run_demo"):
        sys.modules.pop(name, None)


def _run_main(module_name: str, *argv: str) -> tuple[int, str]:
    """Import an example module fresh, set argv, run its `main()`, capture stdout."""
    sys.argv = [module_name + ".py", *argv]
    mod = importlib.import_module(module_name)
    mod = importlib.reload(mod)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main()
    return rc, buf.getvalue()


# ===========================================================================
# AXIS 2 — safety: the exec-capability CLI contract, end to end.
# ===========================================================================
def test_safety_demo_blocks_every_arbitrary_exec_command(example_env):
    """`run_safety_demo.main()` must report `guarded = 0` (DOS blocks every
    arbitrary-exec command before it runs) and `naive > 0` (the hazards actually fire
    when ungated — else the demo proves nothing).

    The exact naive count is platform-dependent and deliberately NOT pinned: the
    three stand-in hazards are `bash -c`, `sh -c`, and `sudo bash -c`. POSIX fires
    all 3; Windows with a Git-style bash fires 2 (its native `sudo` does not wrap
    `bash -c` the way the POSIX one does); Windows where only the System32
    WSL-launcher bash resolves fires 1 (`sh` resolves to nothing there, witnessed
    2026-06-10 on the dev box that redded the v0.21.0 release verify). The
    invariant under test is the SECURITY property (guarded=0, naive>0), not the
    incidental host count.

    Precondition: the host must HAVE a working shell to fire the stand-ins —
    probed by RUNNING `bash -c "echo ok"` (then `sh`), never by PATH inspection.
    ANY working bash counts, including Windows' System32 WSL launcher: the
    stand-ins address the sentinel by bare filename + cwd, a shape every dialect
    resolves. Only a host with no working POSIX shell at all skips, instead of
    failing on `naive = 0`."""
    import swarm_agent

    if not swarm_agent.hazards_can_fire():
        pytest.skip("no working POSIX shell to fire the stand-in hazards "
                    "(both the bash and sh `echo ok` probes failed)")
    rc, out = _run_main("run_safety_demo")
    assert rc == 0, f"safety demo failed:\n{out}"
    assert "guarded = 0" in out, f"guarded arm let an unsafe command through:\n{out}"
    # naive must be > 0 — parse the witnessed count off the demo's scoreboard line.
    naive_line = [ln for ln in out.splitlines() if "naive =" in ln and "guarded =" in ln]
    assert naive_line, f"no scoreboard line found:\n{out}"
    naive_count = int(naive_line[0].split("naive =")[1].split("guarded")[0].strip())
    assert naive_count >= 1, f"no ungated hazard executed (naive={naive_count}):\n{out}"
    # SHAPE-not-word: the innocent `cat python.txt` is NOT blocked in the guarded arm.
    guarded_section = out.split("GUARDED arm", 1)[-1]
    assert "[BLOCKED]" in guarded_section, "guarded arm blocked nothing"
    cat_line = [ln for ln in guarded_section.splitlines() if "cat python.txt" in ln]
    assert cat_line and "BLOCKED" not in cat_line[0], (
        f"SHAPE-not-word violated: `cat python.txt` was blocked:\n{cat_line}")


def test_guard_action_classifies_shape_not_word(example_env):
    """The adapter's `guard_action` (shelling `dos exec-capability`) must DENY an
    arbitrary-exec shape and ALLOW an innocent command that merely NAMES a program."""
    import hermes_adapter

    danger = hermes_adapter.guard_action("bash -c 'rm -rf ~'")
    assert not danger.allowed, "arbitrary-exec `bash -c` was not denied"
    assert danger.capability == "GRANTS_ARBITRARY_EXEC", danger
    assert danger.message, "a deny must carry an operator-facing message"

    # SHAPE-not-word: a file *named* python is not a python invocation.
    innocent = hermes_adapter.guard_action("cat python.txt")
    assert innocent.allowed, "`cat python.txt` was wrongly denied (word-match, not shape)"
    assert innocent.capability in ("BOUNDED", "EMPTY"), innocent

    # The policy knob belongs to the host: with deny_on_arbitrary_exec=False, the
    # SAME dangerous command is reported but ALLOWED (advisory, docs/143).
    advisory = hermes_adapter.guard_action("bash -c 'rm -rf ~'", deny_on_arbitrary_exec=False)
    assert advisory.allowed, "advisory mode must not hard-block"
    assert advisory.capability == "GRANTS_ARBITRARY_EXEC", advisory


# ===========================================================================
# AXIS 1 — coordination: the arbitrate / lease-lane CLI contract, end to end.
# ===========================================================================
def test_coord_demo_k1_is_the_honest_falsifier(example_env):
    """At K=1 the coordination demo MUST show 0 lost updates in BOTH arms — one
    agent cannot collide with itself (Wall §1, the benchmark's own falsifier)."""
    rc, out = _run_main("run_coord_demo", "1")
    assert rc == 0, f"K=1 demo failed:\n{out}"
    assert "naive = 0   guarded = 0" in out, (
        f"K=1 must be 0/0 (the honest falsifier); got:\n{out}")


def test_coord_demo_k4_serializes_writes(example_env):
    """At K=4 the naive arm loses K-1=3 updates; the guarded arm (DOS's real WAL)
    serializes the writes to 0 lost updates."""
    rc, out = _run_main("run_coord_demo", "4")
    assert rc == 0, f"K=4 demo failed:\n{out}"
    assert "guarded = 0" in out, f"guarded arm did not prevent the lost updates:\n{out}"
    assert "naive = 3" in out, (
        f"naive arm should lose K-1=3 updates under maximal contention; got:\n{out}")
    # Exactly one guarded agent acquired; the rest were refused (the serialization).
    acquired = out.count("ACQUIRED region")
    refused = out.count("REFUSED by DOS")
    assert acquired == 1, f"expected exactly one ACQUIRE, got {acquired}:\n{out}"
    assert refused == 3, f"expected K-1=3 REFUSE, got {refused}:\n{out}"


def test_claim_region_refuses_a_held_region(example_env, tmp_path: Path):
    """The pure `claim_region` (shelling `dos arbitrate --output json`) must REFUSE a
    request whose region collides with a live lease, and ACQUIRE a disjoint one."""
    import hermes_adapter

    held = hermes_adapter.lease_dict("reservations/42/**")

    # Same region as the held lease → refuse.
    collision = hermes_adapter.claim_region(
        "reservations/42/**", [held], workspace=str(tmp_path))
    assert not collision.acquired, f"a held region was double-booked: {collision}"
    assert collision.outcome == "refuse", collision

    # A disjoint region → acquire (proves the refuse above is contention, not a
    # blanket deny).
    disjoint = hermes_adapter.claim_region(
        "reservations/99/**", [held], workspace=str(tmp_path))
    assert disjoint.acquired, f"a free disjoint region was refused: {disjoint}"
    assert disjoint.outcome == "acquire", disjoint


def test_durable_lease_round_trip_through_the_wal(example_env, tmp_path: Path):
    """`acquire_lease` (the durable path) journals the grant to the WAL; a second
    agent asking for the SAME region is refused while it is held, then ACQUIREs after
    a release. This is the cross-process serialization the coord demo rides."""
    import hermes_adapter

    region = "reservations/7/**"
    ws = str(tmp_path)

    a = hermes_adapter.acquire_lease(region, owner="agent-a", loop_ts="ts-a", workspace=ws)
    assert a.acquired, f"first acquire should win the free region: {a}"

    # Held by A → B is refused.
    b = hermes_adapter.acquire_lease(region, owner="agent-b", loop_ts="ts-b", workspace=ws)
    assert not b.acquired, f"region held by A was handed to B too: {b}"

    # A releases → B can now take it.
    assert hermes_adapter.release_lease(region, owner="agent-a", loop_ts="ts-a", workspace=ws)
    c = hermes_adapter.acquire_lease(region, owner="agent-b", loop_ts="ts-b", workspace=ws)
    assert c.acquired, f"region should be free after A released it: {c}"
