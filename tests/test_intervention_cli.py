"""CLI tests for `dos intervention-eval` — the net-task-delta operator surface (docs/143 §13.2).

The intervention eval is the actuation twin of `overlap-eval`: it scores an `InterventionPolicy`
not on whether the *verdict* was right (that is `arg-provenance`'s eval) but on whether ACTING
on it helped or hurt the run — the orthogonal property the live −9 pp proved is decisive. These
tests drive the verb end-to-end through `cli.main` (the `test_enterpriseops_harness` idiom:
`cli.main([...])` returns the exit code, `capsys` captures stdout), so they pin both the
command's wiring AND the contract the exit code rides:

  * the verdict-IS-the-exit-code rule — **1 iff the policy is a net regression** (`net_harmful`),
    the `overlap-eval.leaked` CI-gate analogue, so a disruptive policy fails CI;
  * the compact hand-authorable case shape (`confidence` + `unsupported`) the loader synthesizes
    a real `ProvenanceVerdict` from, so a seed corpus is writable without hand-rolling verdicts;
  * the §13.3 contrast on the COMMITTED seed corpus — the default confidence-gating policy is
    net-POSITIVE (exit 0) while `--ceiling DEFER` (turn-spending on every HIGH mint) is
    net-HARMFUL (exit 1) on the SAME cases — the whole point of the double-down, made runnable;
  * fail-loud loading — a malformed cases line exits 2 (a usage error), never a silent skip.

Organised as:
  * `TestSeedCorpus`     — the shipped fixture scores; default vs --ceiling DEFER exit contrast.
  * `TestCompactShape`   — a hand-authored compact corpus round-trips through the synthesizer.
  * `TestExitCodes`      — net-harmful → 1, net-positive → 0, malformed → 2, missing → 2.
  * `TestJsonReport`     — --json emits the net_task_delta-bearing machine report.
"""
from __future__ import annotations

import json
from pathlib import Path

from dos import cli

# The committed seed corpus the contract examples in CLAUDE.md / docs/143 run against.
SEED = (Path(__file__).resolve().parents[1]
        / "benchmark" / "enterpriseops" / "intervention_cases.jsonl")


def _write_cases(tmp_path: Path, lines: list[str], name: str = "cases.jsonl") -> str:
    """Write JSONL `lines` to a tmp file and return its path (str) — the corpus on disk."""
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


# A compact, hand-authored corpus: 3 true-relevant HIGH mints that recover under a
# turn-preserving BLOCK, and one false-flag — so the default (HIGH→BLOCK) is net-positive.
_GOOD = [
    '{"confidence":"HIGH","unsupported":["a"],"truly_minted":true,"mattered_to_score":true,'
    '"recovered_if_blocked":true,"recovered_if_deferred":true,"label":"rel-1"}',
    '{"confidence":"HIGH","unsupported":["b"],"truly_minted":true,"mattered_to_score":true,'
    '"recovered_if_blocked":true,"recovered_if_deferred":false,"label":"rel-2"}',
    '{"confidence":"HIGH","unsupported":["c"],"truly_minted":true,"mattered_to_score":true,'
    '"recovered_if_blocked":true,"recovered_if_deferred":false,"label":"rel-3"}',
    '{"confidence":"NONE","unsupported":[],"truly_minted":false,"mattered_to_score":false,'
    '"recovered_if_blocked":false,"recovered_if_deferred":false,"label":"clean"}',
]


# ── the committed seed corpus ────────────────────────────────────────────────
class TestSeedCorpus:
    """The shipped `benchmark/enterpriseops/intervention_cases.jsonl` is the runnable
    docs/143 §13 example — it MUST load and score, or the contract's worked example rots."""

    def test_seed_corpus_scores_without_error(self, capsys):
        """The seed corpus loads (compact shape) and produces a report; the default policy
        is net-positive (exit 0) because confidence-gating shields the irrelevant LOW catches
        as WARN — the §13.3 fix, made runnable. Pins that the shipped file is well-formed."""
        rc = cli.main(["intervention-eval", "--cases", str(SEED)])
        assert rc == 0, capsys.readouterr().err
        out = capsys.readouterr().out
        assert "NET TASK DELTA" in out
        assert "net-positive-or-neutral" in out

    def test_defer_ceiling_flips_seed_corpus_net_harmful(self, capsys):
        """`--ceiling DEFER` raises HIGH mints to the turn-SPENDING rung; on the SAME corpus
        that is net-HARMFUL (exit 1). This is the whole §13 thesis in one diff: detector
        soundness is unchanged, only the intervention strength differs — and that decides the
        run. The default-vs-DEFER exit-code contrast is the load-bearing assertion."""
        rc_default = cli.main(["intervention-eval", "--cases", str(SEED)])
        capsys.readouterr()
        rc_defer = cli.main(["intervention-eval", "--cases", str(SEED), "--ceiling", "DEFER"])
        out = capsys.readouterr().out
        assert rc_default == 0
        assert rc_defer == 1
        assert "NET-HARMFUL" in out
        assert "high=DEFER" in out  # --ceiling DEFER raised on_high to DEFER (the wiring)


# ── the compact hand-authorable shape ────────────────────────────────────────
class TestCompactShape:
    """The seed corpus is authored in the COMPACT shape (`confidence` + `unsupported`), not a
    full `ProvenanceVerdict.to_dict()` — so a researcher can write a corpus by hand. The loader
    synthesizes the minimal verdict whose REAL `assess_confidence` yields the stated rung, so
    the scored action still flows through the live `choose_intervention` path (no hand-labelled
    confidence that could drift)."""

    def test_compact_corpus_scores_net_positive(self, tmp_path, capsys):
        """A compact corpus of recoverable true-relevant HIGH mints is net-positive (exit 0):
        the default maps HIGH→BLOCK, the turn-preserving rung recovers the catch, and the clean
        NONE case never disrupts."""
        path = _write_cases(tmp_path, _GOOD)
        rc = cli.main(["intervention-eval", "--cases", path])
        assert rc == 0, capsys.readouterr().err

    def test_compact_high_actually_actuates(self, tmp_path, capsys):
        """A single HIGH-confidence relevant mint must ACTUATE under the default (HIGH→BLOCK
        withholds the turn) — proving the synthesized verdict really reads as HIGH through
        `assess_confidence`, not a label we asserted."""
        line = ('{"confidence":"HIGH","unsupported":["x"],"truly_minted":true,'
                '"mattered_to_score":true,"recovered_if_blocked":true,'
                '"recovered_if_deferred":true}')
        path = _write_cases(tmp_path, [line])
        rc = cli.main(["intervention-eval", "--cases", path, "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["actuation"]["actuated"] == 1
        assert d["actuation"]["actuated_relevant"] == 1

    def test_compact_low_is_warned_not_actuated(self, tmp_path, capsys):
        """A LOW-confidence mint must map to WARN under the default — it INFORMS but does NOT
        withhold the turn. This is the §13.3 shield (a composite mint is too uncertain to spend
        a turn on), so a LOW case never actuates."""
        line = ('{"confidence":"LOW","unsupported":["x"],"truly_minted":true,'
                '"mattered_to_score":false,"recovered_if_blocked":false,'
                '"recovered_if_deferred":false}')
        path = _write_cases(tmp_path, [line])
        rc = cli.main(["intervention-eval", "--cases", path, "--json"])
        d = json.loads(capsys.readouterr().out)
        assert d["actuation"]["actuated"] == 0
        assert d["actuation"]["informed_only"] == 1


# ── the exit-code contract (the verdict IS the exit code) ────────────────────
class TestExitCodes:
    """The exit code is the CI verdict on the policy — the `overlap-eval.leaked` analogue.
    1 iff net-harmful, 0 iff net-positive-or-neutral, 2 on a usage error (bad/empty cases)."""

    def test_net_harmful_corpus_exits_1(self, tmp_path, capsys):
        """A corpus where the only disruption is a turn-SPENDING DEFER that never recovers is a
        net regression → exit 1. Built explicitly so the harmful exit code is pinned even if the
        seed corpus is later retuned."""
        # one HIGH relevant mint that recovers under BLOCK but NOT under DEFER → under --ceiling
        # DEFER it is pure cost with no recovery → net-harmful.
        line = ('{"confidence":"HIGH","unsupported":["x"],"truly_minted":true,'
                '"mattered_to_score":true,"recovered_if_blocked":true,'
                '"recovered_if_deferred":false}')
        path = _write_cases(tmp_path, [line])
        rc = cli.main(["intervention-eval", "--cases", path, "--ceiling", "DEFER"])
        assert rc == 1, capsys.readouterr().out

    def test_net_positive_corpus_exits_0(self, tmp_path, capsys):
        """The mirror: the same recoverable mint under the DEFAULT (HIGH→BLOCK, turn-preserving)
        recovers → net-positive → exit 0. Same case, different policy, opposite verdict — the
        §13 thesis as an exit-code pair."""
        line = ('{"confidence":"HIGH","unsupported":["x"],"truly_minted":true,'
                '"mattered_to_score":true,"recovered_if_blocked":true,'
                '"recovered_if_deferred":false}')
        path = _write_cases(tmp_path, [line])
        rc = cli.main(["intervention-eval", "--cases", path])
        assert rc == 0, capsys.readouterr().out

    def test_malformed_line_exits_2(self, tmp_path, capsys):
        """A non-JSON line is a fail-LOUD usage error (exit 2) carrying the offending line
        number — never a silent skip that would quietly under-count the corpus (the
        `overlap-eval`/`judge-eval` honesty discipline)."""
        path = _write_cases(tmp_path, [_GOOD[0], "{not valid json", _GOOD[3]])
        rc = cli.main(["intervention-eval", "--cases", path])
        assert rc == 2
        err = capsys.readouterr().err
        assert "error:" in err and ":2:" in err  # line 2 is the bad one

    def test_missing_required_field_exits_2(self, tmp_path, capsys):
        """A case missing a ground-truth label (here `mattered_to_score`) is a usage error
        (exit 2), not a guessed default — the labels are the researcher's ground truth and
        must be present, never inferred."""
        line = ('{"confidence":"HIGH","unsupported":["x"],"truly_minted":true,'
                '"recovered_if_blocked":true,"recovered_if_deferred":false}')
        path = _write_cases(tmp_path, [line])
        rc = cli.main(["intervention-eval", "--cases", path])
        assert rc == 2
        assert "error:" in capsys.readouterr().err

    def test_neither_verdict_nor_confidence_exits_2(self, tmp_path, capsys):
        """A case carrying the ground-truth labels but NEITHER a `confidence` nor a full
        `verdict` cannot be scored (there is no action to derive) → a fail-loud usage error."""
        line = ('{"truly_minted":true,"mattered_to_score":true,'
                '"recovered_if_blocked":true,"recovered_if_deferred":false}')
        path = _write_cases(tmp_path, [line])
        rc = cli.main(["intervention-eval", "--cases", path])
        assert rc == 2
        assert "error:" in capsys.readouterr().err

    def test_empty_corpus_exits_2(self, tmp_path, capsys):
        """A file of only comments/blanks has no cases → a usage error, not a vacuous exit 0
        (a CI gate must never read "no cases" as "policy is fine")."""
        path = _write_cases(tmp_path, ["# only a comment", ""])
        rc = cli.main(["intervention-eval", "--cases", path])
        assert rc == 2
        assert "no cases" in capsys.readouterr().err


# ── the machine-readable report ──────────────────────────────────────────────
class TestJsonReport:
    """`--json` emits the `InterventionReport.to_dict()` (+ the policy) — the headline
    `net_task_delta`, the actuation ledger, and the dangerous-cell rates a PEP author reads."""

    def test_json_carries_net_task_delta_and_policy(self, capsys):
        """The JSON report carries the headline `net_task_delta` key, the grid, the rates, and
        the policy it scored (so a CI log records WHICH policy produced the number)."""
        rc = cli.main(["intervention-eval", "--cases", str(SEED), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "net_task_delta" in d
        assert d["net_task_delta"] >= 0.0  # the default seed run is net-positive
        assert set(d["grid"]) == {"true_relevant", "true_irrelevant", "false_flag"}
        assert "wasted_disruption_rate" in d["rates"]
        assert d["policy"]["ceiling"] == "BLOCK"
        assert d["net_harmful"] is False

    def test_json_defer_reports_net_harmful_true(self, capsys):
        """Under `--ceiling DEFER` the same seed corpus reports `net_harmful: true` and a
        negative `net_task_delta` — the machine-readable form of the exit-1 verdict."""
        rc = cli.main(["intervention-eval", "--cases", str(SEED), "--ceiling", "DEFER",
                       "--json"])
        assert rc == 1
        d = json.loads(capsys.readouterr().out)
        assert d["net_harmful"] is True
        assert d["net_task_delta"] < 0.0
        assert d["policy"]["on_high_confidence"] == "DEFER"
