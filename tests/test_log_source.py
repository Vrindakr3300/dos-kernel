"""Tests for the log-source seam (docs/117) + the paste_log floor driver.

Pins the disciplines that make an *open* set of log adapters safe — the same ones
`test_judges` / `test_overlap_policy` pin for their seams, re-aimed at logs:

  * the fail-safe runner (`gather_log`) converts a raising source and a wrong-return
    source to an unreachable NO_SIGNAL, never a fabricated read (fail-safe-never-fail-open);
  * the two-constructor reachability discipline (only `reached` sets reachable=True);
  * the inversion law made structural — the floor source (`paste`) is hard-tagged
    AGENT_AUTHORED and the routing predicate (`is_agent_authored`) is correct;
  * the resolver finds built-ins first and fails LOUD on an unknown name;
  * the litmus: the kernel imports no log driver (the log analogue of
    kernel-imports-no-host), the `test_ci_status` template.
"""

from __future__ import annotations

import pathlib

import pytest

from dos import log_source as ls
from dos.log_source import (
    Accountability,
    LogEvidence,
    LogSource,
    NullLogSource,
    gather_log,
    resolve_log_source,
)


# ── the value types: the two-constructor reachability discipline ────────────
class TestLogEvidence:
    def test_default_is_unreachable(self):
        # The fail-safe zero: a bare LogEvidence nobody populated is NOT reachable, so
        # a consumer reads it as NO_SIGNAL, never an empty-but-trusted log.
        ev = LogEvidence(source_name="x", accountability=Accountability.THIRD_PARTY)
        assert ev.reachable is False
        assert ev.lines == ()

    def test_reached_is_the_only_reachable_constructor(self):
        ev = LogEvidence.reached("paste", Accountability.AGENT_AUTHORED, ("a", "b"))
        assert ev.reachable is True
        assert ev.lines == ("a", "b")

    def test_no_signal_is_unreachable(self):
        ev = LogEvidence.no_signal("cw", Accountability.THIRD_PARTY, detail="auth fail")
        assert ev.reachable is False
        assert ev.lines == ()
        assert "auth fail" in ev.detail

    def test_to_dict_round_trips_the_tag(self):
        ev = LogEvidence.reached("paste", Accountability.AGENT_AUTHORED, ("x",))
        d = ev.to_dict()
        assert d["accountability"] == "AGENT_AUTHORED"
        assert d["reachable"] is True
        assert d["lines"] == ["x"]


# ── the inversion law: the floor tag routes to a judge ──────────────────────
class TestAccountability:
    def test_agent_authored_is_the_floor_predicate(self):
        assert Accountability.AGENT_AUTHORED.is_agent_authored is True
        assert Accountability.OS_RECORDED.is_agent_authored is False
        assert Accountability.THIRD_PARTY.is_agent_authored is False

    def test_str_round_trips(self):
        assert str(Accountability.OS_RECORDED) == "OS_RECORDED"


# ── gather_log: fail-safe, never fail-open (the run_judge discipline) ────────
class _Raises:
    name = "boom"
    accountability = Accountability.THIRD_PARTY

    def gather(self, subject, config):
        raise RuntimeError("provider exploded")


class _WrongReturn:
    name = "liar"
    accountability = Accountability.OS_RECORDED

    def gather(self, subject, config):
        return {"lines": ["pretend", "I", "read"]}  # not a LogEvidence


class _Good:
    name = "good"
    accountability = Accountability.THIRD_PARTY

    def gather(self, subject, config):
        return LogEvidence.reached(self.name, self.accountability, ("real", "line"))


class TestGatherLogFailSafe:
    def test_raising_source_degrades_to_no_signal(self):
        ev = gather_log(_Raises(), "subj", None)
        assert ev.reachable is False
        assert ev.lines == ()
        assert "raised" in ev.detail
        # the declared tag is PRESERVED on the failure path, so routing stays correct
        assert ev.accountability is Accountability.THIRD_PARTY

    def test_wrong_return_type_degrades_to_no_signal(self):
        ev = gather_log(_WrongReturn(), "subj", None)
        assert ev.reachable is False
        assert ev.lines == ()
        assert "not a" in ev.detail.lower()
        assert ev.accountability is Accountability.OS_RECORDED

    def test_malformed_tag_falls_to_the_floor_not_a_higher_rung(self):
        # A source object whose accountability is garbage must degrade to the FLOOR on
        # the failure path — never escape to a higher (more-trusted) rung.
        class _BadTag:
            name = "badtag"
            accountability = "not-an-enum"

            def gather(self, subject, config):
                raise ValueError("nope")

        ev = gather_log(_BadTag(), "subj", None)
        assert ev.accountability is Accountability.AGENT_AUTHORED

    def test_good_source_passes_through(self):
        ev = gather_log(_Good(), "subj", None)
        assert ev.reachable is True
        assert ev.lines == ("real", "line")


# ── NullLogSource: the unshadowable honest zero ─────────────────────────────
class TestNullSource:
    def test_null_reaches_nothing(self):
        ev = gather_log(NullLogSource(), "subj", None)
        assert ev.reachable is False
        assert ev.accountability is Accountability.AGENT_AUTHORED  # even absence is floor

    def test_null_is_a_log_source(self):
        assert isinstance(NullLogSource(), LogSource)


# ── resolver: built-in first, unknown fails LOUD ────────────────────────────
class TestResolve:
    def test_built_in_null_resolves(self):
        src = resolve_log_source("null")
        assert isinstance(src, NullLogSource)

    def test_unknown_name_raises_with_known_list(self):
        with pytest.raises(ValueError) as ei:
            resolve_log_source("does-not-exist")
        assert "null" in str(ei.value)  # the known list is surfaced, not a silent null

    def test_active_names_include_null(self):
        assert "null" in ls.active_log_source_names()


# ── the paste_log driver: the deliberate floor ──────────────────────────────
class TestPasteLogDriver:
    def test_paste_is_agent_authored_and_unpromotable(self):
        from dos.drivers.paste_log import PasteLogSource

        src = PasteLogSource(text="tests passed\nexit 0")
        # class-level tag, fixed — there is no path to a higher rung
        assert src.accountability is Accountability.AGENT_AUTHORED
        assert PasteLogSource.accountability is Accountability.AGENT_AUTHORED

    def test_paste_gather_returns_lines_as_judge_hint(self):
        from dos.drivers.paste_log import PasteLogSource

        ev = gather_log(PasteLogSource(text="line a\nline b"), "run-1", None)
        assert ev.reachable is True
        assert ev.lines == ("line a", "line b")
        # reachable on a floor source still routes to a judge — the tag is the ceiling
        assert ev.accountability.is_agent_authored is True

    def test_empty_paste_is_no_signal(self):
        from dos.drivers.paste_log import PasteLogSource

        ev = gather_log(PasteLogSource(text=""), "run-1", None)
        assert ev.reachable is False

    def test_paste_keeps_the_tail_when_capped(self):
        from dos.drivers import paste_log

        big = "\n".join(str(i) for i in range(paste_log._MAX_LINES + 50))
        ev = gather_log(paste_log.PasteLogSource(text=big), "s", None)
        # the tail (recent output / the error / the exit line) is what a judge wants
        assert ev.lines[-1] == str(paste_log._MAX_LINES + 49)
        assert len(ev.lines) == paste_log._MAX_LINES


# ── the litmus: the kernel imports no log driver ────────────────────────────
class TestLayering:
    def test_kernel_does_not_import_a_log_driver(self):
        # The one-way arrow (the test_ci_status template): grep the kernel source
        # (everything under src/dos except drivers/) for a reference to a log driver
        # module — there must be none. The log analogue of "kernel imports no host."
        import dos

        root = pathlib.Path(dos.__file__).parent
        offenders = []
        for p in root.rglob("*.py"):
            if "drivers" in p.parts:
                continue
            text = p.read_text(encoding="utf-8")
            if "paste_log" in text:
                offenders.append(p.name)
        assert offenders == [], f"kernel modules reference a log driver: {offenders}"

    def test_seam_has_no_io_surface(self):
        # The seam is pure: no subprocess / network / open() inside log_source.py.
        # (Backends do I/O; the seam does not — the judges/overlap_policy discipline.)
        src = pathlib.Path(ls.__file__).read_text(encoding="utf-8")
        for forbidden in ("subprocess", "urllib", "requests", "socket.socket"):
            assert forbidden not in src, f"log_source.py must not reference {forbidden!r}"
