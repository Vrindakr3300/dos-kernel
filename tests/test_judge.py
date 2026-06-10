"""Tests for the judge — core deterministic adjudicator + the LLM driver seam.

Two layers, with a hard boundary between them (the DSP "Bulkhead" axiom):

  * `dos judge wedge <run_ts>` (core, `cli.cmd_judge`) is DETERMINISTIC — it
    reuses `picker_oracle` to cross-check a no-pick verdict against on-disk state
    and emits a provable `oracle_disagrees`. Zero LLM-provider surface. Exit code
    IS the verdict: 1 on a provable picker bug, 0 otherwise.
  * `dos.drivers.llm_judge` (driver, OUTSIDE the kernel) adds the optional LLM
    adjudication for the `UNCLASSIFIED` residue the oracle can only abstain on.
    It is deterministic-first (the LLM never overrides a provable verdict) and
    degrades to "unadjudicated" when no provider is wired — never crashing, never
    a hard dependency. The provider is reached through one guarded env-var seam,
    which these tests exercise with a fake command.

The kernel-never-imports-a-driver rule is also asserted (the bulkhead, as a test).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dos import config as _config
from dos import cli
from dos.drivers import llm_judge


# ---------------------------------------------------------------------------
# Fixtures — seed a chained run that picker_oracle can classify.
# ---------------------------------------------------------------------------


def _seed_run(
    cfg,
    run_ts="20260531T010000Z",
    *,
    tag="next-up-2026-05-31-1",
    reason_class="LANE_DRAINED",
    verdict="DRAIN",
    scope_plan_ids=("RS",),
    picker_reason="all in-scope plans remaining:[]",
    plans_yaml="plans:\n  - id: RS\n    remaining: [RS4, RS5]\n",
):
    """Seed the run-dir + verdict envelope + execution-state the oracle reads."""
    cr = cfg.paths.chained_runs / run_ts / "result_envelopes"
    cr.mkdir(parents=True, exist_ok=True)
    (cr / "next-up.json").write_text(json.dumps({"tag": tag, "subtype": "success"}),
                                     encoding="utf-8")
    (cfg.paths.chained_runs / run_ts / "README.md").write_text(
        "- Args: --scope main\n- Picks shipped: none\n", encoding="utf-8")
    nd = cfg.paths.next_packets
    nd.mkdir(parents=True, exist_ok=True)
    (nd / f".verdict-{tag}.json").write_text(json.dumps({
        "tag": tag, "verdict": verdict, "all_clear": False,
        "reason_class": reason_class, "reason": picker_reason,
        "scope": {"plan_ids": list(scope_plan_ids)}, "picks": [],
    }), encoding="utf-8")
    es = cfg.paths.execution_state
    es.parent.mkdir(parents=True, exist_ok=True)
    es.write_text(plans_yaml, encoding="utf-8")


# ---------------------------------------------------------------------------
# Core `dos judge` — deterministic, via the CLI entrypoint.
# ---------------------------------------------------------------------------


class TestCoreJudge:
    def test_oracle_disagrees_exits_1(self, tmp_path: Path, capsys):
        # Picker claimed TRUE_DRAIN but RS has remaining work -> provable bug.
        cfg = _config.default_config(tmp_path)
        _config.set_active(cfg)
        _seed_run(cfg)
        rc = cli.main(["judge", "wedge", "20260531T010000Z",
                       "--workspace", str(tmp_path)])
        out = capsys.readouterr().out
        assert "oracle_disagrees=TRUE" in out
        assert rc == 1

    def test_oracle_agrees_exits_0(self, tmp_path: Path, capsys):
        # Picker claimed TRUE_DRAIN and RS really is drained -> agrees.
        cfg = _config.default_config(tmp_path)
        _config.set_active(cfg)
        _seed_run(cfg, plans_yaml="plans:\n  - id: RS\n    remaining: []\n")
        rc = cli.main(["judge", "wedge", "20260531T010000Z",
                       "--workspace", str(tmp_path)])
        out = capsys.readouterr().out
        assert "no picker bug" in out
        assert rc == 0

    def test_json_verdict_shape(self, tmp_path: Path, capsys):
        cfg = _config.default_config(tmp_path)
        _config.set_active(cfg)
        _seed_run(cfg)
        rc = cli.main(["judge", "wedge", "20260531T010000Z", "--json",
                       "--workspace", str(tmp_path)])
        payload = json.loads(capsys.readouterr().out)
        assert payload["oracle_disagrees"] is True
        assert payload["no_pick_cause"] == "TRUE_DRAIN"
        assert rc == 1


# ---------------------------------------------------------------------------
# The LLM driver — deterministic-first + provider seam + graceful degrade.
# ---------------------------------------------------------------------------


class TestLlmJudgeDriver:
    def test_deterministic_first_does_not_consult_llm(self, tmp_path: Path, monkeypatch):
        # When the oracle CAN classify (LANE_DRAINED), the driver must return the
        # oracle verdict and NEVER call the provider seam.
        cfg = _config.default_config(tmp_path)
        _config.set_active(cfg)
        _seed_run(cfg)  # classifiable -> oracle disagrees

        called = {"provider": False}

        def _boom(prompt):
            called["provider"] = True
            return "VERDICT: agree\nWHY: should not be reached"

        monkeypatch.setattr(llm_judge, "_call_provider", _boom)
        v = llm_judge.adjudicate("20260531T010000Z", cfg)
        assert v.engine == "oracle"
        assert v.agrees_with_picker is False  # oracle disagreed
        assert called["provider"] is False    # the LLM was NOT consulted

    def test_unclassified_with_no_provider_is_unadjudicated(self, tmp_path: Path, monkeypatch):
        cfg = _config.default_config(tmp_path)
        _config.set_active(cfg)
        # An unknown reason_class the oracle cannot verify -> UNCLASSIFIED residue.
        _seed_run(cfg, reason_class="SOME_LEGACY_HANDWAVE", verdict="WEDGE",
                  plans_yaml="plans: []\n")
        monkeypatch.setattr(llm_judge, "_call_provider", lambda prompt: None)
        v = llm_judge.adjudicate("20260531T010000Z", cfg)
        assert v.engine == "unadjudicated"
        assert v.agrees_with_picker is None
        assert "no LLM provider" in v.rationale

    def test_unclassified_with_provider_uses_llm(self, tmp_path: Path, monkeypatch):
        cfg = _config.default_config(tmp_path)
        _config.set_active(cfg)
        _seed_run(cfg, reason_class="SOME_LEGACY_HANDWAVE", verdict="WEDGE",
                  plans_yaml="plans: []\n")
        monkeypatch.setattr(
            llm_judge, "_call_provider",
            lambda prompt: "VERDICT: disagree\nWHY: reason is vague",
        )
        v = llm_judge.adjudicate("20260531T010000Z", cfg)
        assert v.engine == "llm"
        assert v.agrees_with_picker is False
        assert "vague" in v.rationale

    def test_provider_seam_honors_env_command(self, tmp_path: Path, monkeypatch):
        # The seam itself: a command set via the env var receives the prompt on
        # stdin and its stdout is returned. Use a portable echo-style command.
        monkeypatch.setenv(
            llm_judge.ENV_JUDGE_CMD,
            'python -c "import sys; sys.stdin.read(); print(\'VERDICT: agree\')"',
        )
        out = llm_judge._call_provider("any prompt")
        assert out is not None
        assert "agree" in out

    def test_provider_seam_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv(llm_judge.ENV_JUDGE_CMD, raising=False)
        assert llm_judge._call_provider("prompt") is None

    def test_reply_parser_tolerates_offformat(self):
        agrees, why = llm_judge._parse_llm_reply("totally unstructured blah")
        assert agrees is None
        assert "unstructured" in why
        agrees, why = llm_judge._parse_llm_reply("VERDICT: agree\nWHY: looks fine")
        assert agrees is True
        assert why == "looks fine"


# ---------------------------------------------------------------------------
# The bulkhead — the kernel must not import a driver.
# ---------------------------------------------------------------------------


class TestBulkhead:
    def test_kernel_modules_do_not_import_llm_driver(self):
        # The driver imports the kernel; the kernel never imports the driver.
        # We parse each top-level kernel module's AST and assert none of them has
        # an `import dos.drivers...` statement. (A driver *path* may appear as an
        # emitted command STRING — e.g. cli's `dos judge` abstain hint, or the
        # decision queue's `python -m dos.drivers.llm_judge` action — and that is
        # fine; a printed string is not a code dependency. Only a real import
        # would breach the bulkhead, so we check imports, not substrings.)
        import ast
        import dos
        core_dir = Path(dos.__file__).parent
        offenders = []
        for py in core_dir.glob("*.py"):  # top-level kernel modules only (not drivers/)
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                mods: list[str] = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                if any(m.startswith("dos.drivers") for m in mods):
                    offenders.append(f"{py.name}: {mods}")
        assert offenders == [], f"kernel modules import a driver: {offenders}"
