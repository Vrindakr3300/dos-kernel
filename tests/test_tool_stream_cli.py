"""CLI tests for `dos tool-stream-eval` — the net-recovery operator surface (docs/145 §9).

The stall-reader eval is the loop-economics twin of `intervention-eval`: it scores a
`StreamPolicy` not on whether a stall was *detected* but on whether FIRING a re-surface on a
REPEATING stream recovers stuck tasks more often than it false-fires on a legitimate poller —
the calibration question the §3 honest hole (eventual-consistency polling) makes decisive.
These tests drive the verb end-to-end through `cli.main` (the `test_intervention_cli` idiom:
`cli.main([...])` returns the exit code, `capsys` captures stdout), pinning both the wiring AND
the contract the exit code rides:

  * the verdict-IS-the-exit-code rule — **0 iff the policy is net-positive** (recovers more
    stuck streams than it false-fires on pollers), the `intervention-eval` CI-gate analogue
    inverted to the friendly direction;
  * the compact `repeat` case shape (N identical steps) AND the full `steps` list;
  * the calibration story — `--ignore-tools` exempting the poller flips the SAME corpus from
    NET-NEGATIVE to net-positive (the "calibrate the thresholds from data" instrument, runnable);
  * the `--repeat-n` sweep — raising the firing threshold past the run-length stops it firing;
  * fail-loud loading — a malformed cases line exits 2 (a usage error), never a silent skip.
"""
from __future__ import annotations

import json
from pathlib import Path

from dos import cli


def _write_cases(tmp_path: Path, lines: list[str], name: str = "cases.jsonl") -> str:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


# A corpus where the DEFAULT policy is net-NEGATIVE: one stuck stream that recovers (a useful
# fire) and one legit poller on `poll_status` that ALSO fires (the false-resurface) — so
# recovered (1) is NOT > false-resurfaced (1) → net-negative until the poller is exempted.
_MIXED = [
    '{"repeat":4,"tool":"get_incident","actually_stuck":true,"legit_polling":false,'
    '"recovered_if_fired":true,"label":"stuck"}',
    '{"repeat":4,"tool":"poll_status","actually_stuck":false,"legit_polling":true,'
    '"recovered_if_fired":false,"label":"poller"}',
]


class TestNetVerdictExit:
    def test_default_policy_is_net_negative_on_mixed(self, tmp_path, capsys):
        """The mixed corpus: 1 recover vs 1 false-resurface → NET-NEGATIVE, exit 1."""
        cases = _write_cases(tmp_path, _MIXED)
        code = cli.main(["tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases])
        out = capsys.readouterr().out
        assert code == 1
        assert "NET-NEGATIVE" in out

    def test_ignore_tools_exempts_the_poller_and_flips_to_net_positive(self, tmp_path, capsys):
        """The calibration story: exempting the poller drops false-resurface to 0 → net-positive,
        exit 0, on the SAME corpus. The 'calibrate from data' instrument, runnable."""
        cases = _write_cases(tmp_path, _MIXED)
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases,
            "--ignore-tools", "poll_status",
        ])
        out = capsys.readouterr().out
        assert code == 0
        assert "net-positive" in out
        assert "0.000" in out  # the false-resurface rate dropped to 0

    def test_raising_repeat_n_stops_firing(self, tmp_path, capsys):
        """Sweep: --repeat-n above the run-length means nothing fires → 0 recovery (timid floor)."""
        cases = _write_cases(tmp_path, _MIXED)
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases,
            "--repeat-n", "9", "--stall-n", "10",
        ])
        out = capsys.readouterr().out
        # 0 recovered, 0 false-resurface → net_positive is False (0 > 0 is False) → exit 1
        assert code == 1
        assert "FIRED=0" in out


class TestCaseShapes:
    def test_full_steps_shape(self, tmp_path, capsys):
        """A full `steps` list round-trips: 3 identical steps fire REPEATING and recover."""
        cases = _write_cases(tmp_path, [
            '{"steps":[["get_user","a","r"],["get_user","a","r"],["get_user","a","r"]],'
            '"actually_stuck":true,"legit_polling":false,"recovered_if_fired":true}',
        ])
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases, "--json"])
        out = capsys.readouterr().out
        rep = json.loads(out)
        assert rep["firing"]["fired"] == 1
        assert rep["firing"]["recovered"] == 1
        assert rep["net_positive"] is True
        assert code == 0

    def test_too_short_stream_does_not_fire(self, tmp_path, capsys):
        """A 2-step stream (< default repeat_n 3) does NOT fire — the too-short floor."""
        cases = _write_cases(tmp_path, [
            '{"repeat":2,"actually_stuck":true,"legit_polling":false,"recovered_if_fired":true}',
        ])
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases, "--json"])
        rep = json.loads(capsys.readouterr().out)
        assert rep["firing"]["fired"] == 0
        assert rep["rates"]["recovered_rate"] == 0.0
        # 0 recovered, 0 false-resurface → not net-positive → exit 1
        assert code == 1


class TestExitCodes:
    def test_malformed_line_exits_2(self, tmp_path, capsys):
        """A line missing a required ground-truth label is a usage error → exit 2 (fail-loud)."""
        cases = _write_cases(tmp_path, ['{"repeat":4,"actually_stuck":true}'])
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases])
        err = capsys.readouterr().err
        assert code == 2
        assert "error" in err.lower()

    def test_not_json_exits_2(self, tmp_path, capsys):
        cases = _write_cases(tmp_path, ["this is not json"])
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases])
        assert code == 2

    def test_missing_file_exits_2(self, tmp_path, capsys):
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path),
            "--cases", str(tmp_path / "nope.jsonl")])
        assert code == 2

    def test_empty_corpus_exits_2(self, tmp_path, capsys):
        cases = _write_cases(tmp_path, ["# only a comment", ""])
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases])
        assert code == 2


class TestJsonReport:
    def test_json_carries_policy_and_rates(self, tmp_path, capsys):
        cases = _write_cases(tmp_path, _MIXED)
        code = cli.main([
            "tool-stream-eval", "--workspace", str(tmp_path), "--cases", cases, "--json"])
        rep = json.loads(capsys.readouterr().out)
        assert rep["policy"]["repeat_n"] == 3
        assert rep["policy"]["stall_n"] == 5
        assert "recovered_rate" in rep["rates"]
        assert "false_resurface_rate" in rep["rates"]
        assert rep["grid"]["stuck"] == 1
        assert rep["grid"]["polling"] == 1
        assert code == 1  # net-negative on the mixed corpus
