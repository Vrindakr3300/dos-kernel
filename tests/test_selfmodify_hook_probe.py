"""Tests for `scripts/selfmodify_hook_probe.py` — the SAFE SELF_MODIFY hook probe.

The harness exists to kill a specific hazard: proving the pre-tool hook refuses a
self-modifying write by pointing a LIVE agent at the REAL repo and telling it to
`Write` to `src/dos/arbiter.py`. SELF_MODIFY only fires on a path that is actually a
kernel runtime file under the served workspace, so the stimulus MUST name a real
guarded path — and if the hook then misses (empty stdin, a host-ignored dialect, a
crashed subprocess), the write LANDS and the kernel is destroyed. (This happened:
`arbiter.py` was found truncated to a lone `x`, breaking the whole suite.)

These tests pin the harness's safety contract so the dangerous pattern can't return:

  1. it proves SELF_MODIFY BLOCKS for every dialect (a real, non-trivial proof);
  2. running the full fail-open simulation leaves the REAL kernel byte-identical;
  3. the stimulus names a path that is genuinely guarded (not a decoy that would
     pass vacuously) — the test that the test is honest.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

# Import the script-under-test by path (it is not an installed package).
_HELPER_PATH = Path(__file__).resolve().parent.parent / "scripts" / "selfmodify_hook_probe.py"
_spec = importlib.util.spec_from_file_location("selfmodify_hook_probe", _HELPER_PATH)
shp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shp)

_REPO = Path(__file__).resolve().parent.parent


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_every_dialect_blocks_the_self_modify_write(tmp_path):
    """The core proof: against a sacrificial workspace, the pre-tool hook DENIES a
    Write to the kernel for every dialect, in that dialect's blocking grammar."""
    from dos import hook_dialect as hd

    shp.build_sacrificial_workspace(tmp_path)
    for dialect in hd.available_dialects():
        r = shp.probe_dialect(tmp_path, dialect)
        assert r["decision"] == "deny", f"{dialect}: expected deny, got {r['decision']}"
        assert r["reason_class"] == "SELF_MODIFY", f"{dialect}: {r['reason_class']}"
        assert r["blocks"], f"{dialect}: rendered envelope carries no blocking signal: {r['rendered']}"


def test_fail_open_simulation_never_touches_the_real_kernel(tmp_path):
    """The safety contract: the harness models a fail-open by writing the agent
    payload to the SACRIFICIAL arbiter.py, and the REAL src/dos/arbiter.py is
    byte-identical before and after. This is the property whose ABSENCE truncated
    the kernel to `x`."""
    real_arbiter = _REPO / "src" / "dos" / "arbiter.py"
    real_before = _sha(real_arbiter)

    dummy_shas = shp.build_sacrificial_workspace(tmp_path)
    safety = shp.prove_real_kernel_untouched(tmp_path, dummy_shas)

    assert safety["real_untouched"], "the probe MUTATED the real kernel — the exact hazard"
    assert safety["sacrificial_clobbered"], "the fail-open simulation wrote nothing — vacuous"
    # And prove it directly, not just via the harness's own report.
    assert _sha(real_arbiter) == real_before, "real arbiter.py sha changed across the probe"


def test_stimulus_path_is_genuinely_guarded_not_a_decoy(tmp_path):
    """The test-of-the-test: the stimulus must name a path SELF_MODIFY actually
    refuses. A decoy filename (`src/dos/_not_real.py`) PASSES the guard, so a probe
    built on one would prove nothing while looking green. Assert the harness's
    stimulus is in the kernel runtime set AND that a sibling decoy would NOT block —
    so the deny we observe is real coverage, not an artifact."""
    from dos.self_modify import _DISPATCH_RUNTIME_FILES

    assert shp._STIMULUS_PATH in _DISPATCH_RUNTIME_FILES

    shp.build_sacrificial_workspace(tmp_path)
    # A decoy under src/dos/ that is NOT a runtime file must pass (no SELF_MODIFY) —
    # confirming the guard is path-specific and our stimulus's deny is meaningful.
    import dataclasses
    from dos import config as _config, pretool_sensor as prt
    from dos.self_modify import existing_runtime_files

    cfg = _config.default_config(tmp_path)
    facts = _config.WorkspaceFacts(
        root=tmp_path,
        kernel_runtime_files=tuple(existing_runtime_files(tmp_path)),
        is_kernel_repo=True,
    )
    cfg = dataclasses.replace(cfg, workspace=facts)
    decoy_event = {
        "session_id": "t", "tool_name": "Write",
        "tool_input": {"file_path": "src/dos/_not_a_runtime_file.py", "content": "x"},
        "cwd": str(tmp_path),
    }
    _, outcome = prt.decide(decoy_event, cfg)
    assert outcome.get("reason_class") != "SELF_MODIFY", (
        "a non-runtime decoy unexpectedly tripped SELF_MODIFY — the stimulus's deny "
        "may be a false positive, weakening the probe")
