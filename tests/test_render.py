"""RND — the renderer seam (Axis 4): pluggable output, byte-faithful built-ins.

Output used to be hardcoded `print` in `cli.py` / `render_text`/`render_json` in
`timeline.py`. RND routes it through a `Renderer` resolved by name, so a
workspace selects `--output terse` for its own format without forking. The
load-bearing property these tests pin is **byte-faithfulness**: the built-in
`text`/`json` renderers reproduce each command's current default output
character-for-character, so routing through the seam changed nothing for the
default path.

  * Phase 1 — the protocol + built-ins behind a resolver (built-ins only).
  * Phase 2 — entry-point discovery + the `--output` flag; built-ins can't be
    shadowed; an unknown name fails loud.
  * Phase 3 — the protocol grown to timeline/man, with a partial renderer
    falling back to text for the surfaces it doesn't implement.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dos import render
from dos.oracle import ShipVerdict
from dos.arbiter import LaneDecision


def _cli(repo: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dos.cli", *argv, "--workspace", str(repo)],
        capture_output=True, text=True,
    )


# ---------------------------------------------------------------------------
# Phase 1 — protocol + built-ins
# ---------------------------------------------------------------------------
class TestPhase1Builtins:
    def test_text_renderer_byte_identical_verdict(self):
        """TextRenderer.render_verdict equals cmd_verify's old non-json line,
        char-for-char, on a frozen ShipVerdict."""
        v = ShipVerdict(plan="AUTH", phase="2", shipped=True, sha="abc123",
                        source="grep")
        expected = "SHIPPED AUTH 2 abc123 (via grep)"
        assert render.TEXT.render_verdict(v) == expected

    def test_text_renderer_not_shipped_no_sha(self):
        v = ShipVerdict(plan="P", phase="1", shipped=False, source="none")
        assert render.TEXT.render_verdict(v) == "NOT_SHIPPED P 1 (via none)"

    def test_text_renderer_no_source_omits_via(self):
        v = ShipVerdict(plan="P", phase="1", shipped=False, source="")
        assert render.TEXT.render_verdict(v) == "NOT_SHIPPED P 1"

    def test_json_renderer_roundtrips_verdict(self):
        v = ShipVerdict(plan="AUTH", phase="2", shipped=True, sha="abc123",
                        source="registry")
        assert json.loads(render.JSON.render_verdict(v)) == v.to_dict()

    def test_json_renderer_is_sorted_keys(self):
        """The machine form is sorted-keys compact JSON — byte-identical to the
        old `cmd_verify --json` branch."""
        v = ShipVerdict(plan="AUTH", phase="2", shipped=True, source="grep")
        assert render.JSON.render_verdict(v) == json.dumps(v.to_dict(),
                                                           sort_keys=True)

    def test_text_decision_is_compact_sorted_json(self):
        """Arbitrate has no human form today — it prints compact sorted JSON. So
        the `text` renderer's decision form IS that JSON, keeping `dos
        arbitrate` (default renderer) byte-identical."""
        d = LaneDecision("acquire", lane="api", tree=["src/api/**"])
        assert render.TEXT.render_decision(d) == json.dumps(d.to_dict(),
                                                            sort_keys=True)
        assert render.JSON.render_decision(d) == json.dumps(d.to_dict(),
                                                           sort_keys=True)

    def test_resolve_builtin_names(self):
        assert render.resolve_renderer("text") is render.TEXT
        assert render.resolve_renderer("json") is render.JSON

    def test_resolve_unknown_raises_with_known_list(self):
        try:
            render.resolve_renderer("nope")
        except render.UnknownRenderer as e:
            assert e.name == "nope"
            assert "text" in e.known and "json" in e.known
            assert "nope" in str(e)
        else:  # pragma: no cover
            raise AssertionError("expected UnknownRenderer")

    def test_known_renderers_lists_builtins_first(self):
        names = render.known_renderers()
        assert names[:2] == ["text", "json"]


class TestPhase1CmdVerifyRouted:
    """cmd_verify now routes through the seam — its default + --json output is
    byte-identical to before (proven via the CLI subprocess)."""

    def _bare_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       cwd=repo, check=True)
        return repo

    def test_default_text_output(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        proc = _cli(repo, "verify", "SOMEPLAN", "PH1")
        assert proc.returncode == 1, proc.stderr
        assert proc.stdout.strip() == "NOT_SHIPPED SOMEPLAN PH1 (via none)"

    def test_json_flag_still_works(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        proc = _cli(repo, "verify", "SOMEPLAN", "PH1", "--json")
        assert proc.returncode == 1, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["shipped"] is False
        assert payload["plan"] == "SOMEPLAN"
        assert payload["source"] == "none"


# ---------------------------------------------------------------------------
# Phase 2 — entry-point discovery + the --output flag
# ---------------------------------------------------------------------------
class _StubEP:
    """A minimal importlib.metadata.EntryPoint stand-in (name + load())."""

    def __init__(self, name: str, obj) -> None:
        self.name = name
        self._obj = obj

    def load(self):
        return self._obj


class _StubTerse:
    name = "terse"

    def render_verdict(self, verdict) -> str:
        return f"terse:{verdict.plan}/{verdict.phase}"

    def render_decision(self, decision) -> str:
        return f"terse:{decision.outcome}/{decision.lane}"


class TestPhase2Discovery:
    def test_entrypoint_renderer_discovered(self, monkeypatch):
        """A stub `dos.renderers` entry point is resolved by its name."""
        monkeypatch.setattr(
            render, "_discover_entry_point_renderers",
            lambda *, _stderr=None: {"terse": _StubTerse()},
        )
        r = render.resolve_renderer("terse")
        assert r.name == "terse"
        v = ShipVerdict(plan="AUTH", phase="2", shipped=True, source="grep")
        assert r.render_verdict(v) == "terse:AUTH/2"

    def test_builtin_cannot_be_shadowed_by_plugin(self, monkeypatch):
        """A plugin claiming name=json does NOT displace the built-in JsonRenderer
        — built-ins resolve first, and discovery drops the collision."""
        captured = {}

        def fake_eps(group=None):
            assert group == render.RENDERER_ENTRY_POINT_GROUP

            class _Evil:
                name = "json"

                def render_verdict(self, verdict):  # would corrupt machine output
                    return "HIJACKED"

            return [_StubEP("json", _Evil)]

        import importlib.metadata as md
        monkeypatch.setattr(md, "entry_points", fake_eps)
        # resolve_renderer('json') must still return the built-in JSON renderer.
        assert render.resolve_renderer("json") is render.JSON
        # And the collision is reported (ignored, not silently captured): the
        # discovery routine writes a stderr note and returns it filtered out.
        import io
        buf = io.StringIO()
        discovered = render._discover_entry_point_renderers(_stderr=buf)
        assert "json" not in discovered
        assert "collides with a built-in" in buf.getvalue()

    def test_unknown_renderer_lists_known(self, monkeypatch):
        monkeypatch.setattr(
            render, "_discover_entry_point_renderers",
            lambda *, _stderr=None: {"terse": _StubTerse()},
        )
        try:
            render.resolve_renderer("bogus")
        except render.UnknownRenderer as e:
            assert "bogus" in str(e)
            assert "text" in e.known and "json" in e.known and "terse" in e.known
        else:  # pragma: no cover
            raise AssertionError("expected UnknownRenderer")

    def test_unknown_name_does_not_double_warn_on_collision(self, monkeypatch):
        """An unknown `--output` combined with a name-colliding plugin must emit
        the collision note ONCE — resolve_renderer reuses its discovered dict for
        the error's known-list instead of re-discovering (which would re-warn)."""
        import io

        def fake_eps(group=None):
            class _Evil:
                name = "json"

                def render_verdict(self, verdict):
                    return "X"

            return [_StubEP("json", _Evil)]

        import importlib.metadata as md
        monkeypatch.setattr(md, "entry_points", fake_eps)
        buf = io.StringIO()
        try:
            render.resolve_renderer("bogus", _stderr=buf)
        except render.UnknownRenderer:
            pass
        assert buf.getvalue().count("collides with a built-in") == 1


class TestPhase2CliFlag:
    def _bare_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       cwd=repo, check=True)
        return repo

    def test_output_json_matches_json_flag(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        a = _cli(repo, "verify", "P", "1", "--output", "json")
        b = _cli(repo, "verify", "P", "1", "--json")
        assert a.stdout == b.stdout

    def test_output_text_is_default(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        a = _cli(repo, "verify", "P", "1")
        b = _cli(repo, "verify", "P", "1", "--output", "text")
        assert a.stdout == b.stdout == "NOT_SHIPPED P 1 (via none)\n"

    def test_output_bogus_fails_loud(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        proc = _cli(repo, "verify", "P", "1", "--output", "bogus")
        assert proc.returncode == 2, (proc.stdout, proc.stderr)
        assert "unknown renderer 'bogus'" in proc.stderr
        assert "text" in proc.stderr and "json" in proc.stderr

    def test_arbitrate_default_is_compact_json(self, tmp_path):
        """`dos arbitrate` (no --output) stays byte-identical: compact sorted
        JSON parseable by the existing WCR tests."""
        repo = self._bare_repo(tmp_path)
        proc = _cli(repo, "arbitrate", "--lane", "main", "--kind", "cluster",
                    "--leases", "[]")
        assert proc.returncode == 0, proc.stderr
        decision = json.loads(proc.stdout)
        assert decision["outcome"] == "acquire"
        # Compact (single line) — no pretty indent by default.
        assert proc.stdout.count("\n") == 1

    def test_arbitrate_pretty_still_indents(self, tmp_path):
        repo = self._bare_repo(tmp_path)
        proc = _cli(repo, "arbitrate", "--lane", "main", "--kind", "cluster",
                    "--leases", "[]", "--pretty")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["outcome"] == "acquire"
        assert proc.stdout.count("\n") > 1  # indented multi-line

    def test_arbitrate_bad_leases_json_is_a_clean_error(self, tmp_path):
        # A malformed --leases value is operator error: a clean message + the
        # contract-error exit code (2), NOT an uncaught JSONDecodeError traceback.
        repo = self._bare_repo(tmp_path)
        proc = _cli(repo, "arbitrate", "--lane", "main", "--kind", "cluster",
                    "--leases", "[not json")
        assert proc.returncode == 2, (proc.stdout, proc.stderr)
        assert "not valid JSON" in proc.stderr
        assert "Traceback" not in proc.stderr

    def test_arbitrate_non_array_leases_rejected(self, tmp_path):
        # --leases must be a JSON ARRAY of lease objects, not a bare object/scalar.
        repo = self._bare_repo(tmp_path)
        proc = _cli(repo, "arbitrate", "--lane", "main", "--kind", "cluster",
                    "--leases", '{"lane": "x"}')
        assert proc.returncode == 2, (proc.stdout, proc.stderr)
        assert "must be a JSON array" in proc.stderr


# ---------------------------------------------------------------------------
# Phase 3 — the protocol grown to timeline / man, with text fallback
# ---------------------------------------------------------------------------
def _make_timeline(tmp_path: Path):
    """A minimal Timeline whose run_dir is under a workspace root, so
    render_text's `run_dir.relative_to(_repo())` resolves."""
    from dos import config as _config
    from dos.timeline import Timeline, Stage, HandoffCheck
    _config.set_active(_config.default_config(tmp_path))
    run_dir = tmp_path / ".dos" / "runs" / "20260601T000000Z"
    t = Timeline(run_ts="20260601T000000Z", run_dir=run_dir)
    t.stages.append(Stage(order=0, stage="invoke", actor="upper", status="ok",
                          detail="x"))
    t.checks.append(HandoffCheck(boundary="b", expected="e", observed="o",
                                 verdict="OK"))
    return t


class TestPhase3Timeline:
    def test_text_renderer_timeline_byte_identical(self, tmp_path):
        from dos import timeline as _timeline
        t = _make_timeline(tmp_path)
        assert render.TEXT.render_timeline(t) == _timeline.render_text(t)

    def test_json_renderer_timeline_byte_identical(self, tmp_path):
        from dos import timeline as _timeline
        t = _make_timeline(tmp_path)
        assert render.JSON.render_timeline(t) == _timeline.render_json(t)

    def test_partial_renderer_falls_back_to_text_for_timeline(self, tmp_path):
        """A renderer implementing only render_verdict/decision still produces
        the canonical TEXT form for render_timeline (BaseRenderer fallback)."""
        from dos import timeline as _timeline

        class OnlyVerdict(render.BaseRenderer):
            name = "onlyverdict"

            def render_verdict(self, verdict):
                return "v"

            def render_decision(self, decision):
                return "d"

        r = OnlyVerdict()
        t = _make_timeline(tmp_path)
        assert r.render_timeline(t) == _timeline.render_text(t)


class TestPhase3Man:
    def test_text_man_joins_lines(self):
        e = render.ManEntry(["NAME x", "CATEGORY y"], {"key": "x"})
        assert render.TEXT.render_man(e) == "NAME x\nCATEGORY y"

    def test_json_man_emits_fields(self):
        e = render.ManEntry(["NAME x"], {"key": "x", "category": "y"})
        assert json.loads(render.JSON.render_man(e)) == {"key": "x",
                                                        "category": "y"}

    def test_cmd_man_default_text_byte_identical(self, tmp_path):
        """`dos man wedge LANE_DRAINED` default output is the same line block as
        before the seam (proven by re-deriving it from the registry)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        proc = _cli(repo, "man", "wedge", "LANE_DRAINED")
        assert proc.returncode == 0, proc.stderr
        # The detail page starts with the NAME line and contains CATEGORY/REFUSAL.
        assert proc.stdout.startswith("NAME        LANE_DRAINED")
        assert "CATEGORY    TRUE_DRAIN" in proc.stdout
        assert "REFUSAL?    yes" in proc.stdout

    def test_cmd_man_json_is_structured(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        proc = _cli(repo, "man", "wedge", "LANE_DRAINED", "--output", "json")
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["key"] == "LANE_DRAINED"
        assert payload["category"] == "TRUE_DRAIN"
        assert payload["section"] == "wedge"


class TestPhase3Decisions:
    def test_text_decisions_byte_identical(self):
        """TEXT.render_decisions IS decisions.render_list_plain (byte-identical)."""
        from dos import decisions as _decisions
        assert render.TEXT.render_decisions([]) == _decisions.render_list_plain([])

    def test_json_decisions_matches_legacy_indent(self):
        """JSON.render_decisions matches cmd_decisions' legacy --json bytes
        (indent=2), so `--output json` and `--json` coincide for decisions."""
        rows = []
        assert render.JSON.render_decisions(rows) == json.dumps(
            [d.to_dict() for d in rows], indent=2, default=str)

    def test_cmd_decisions_list_routes_through_seam(self, tmp_path):
        """`dos decisions --no-tui` (no pending) renders via the seam, byte-equal
        to render_list_plain([])."""
        from dos import decisions as _decisions
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        proc = _cli(repo, "decisions", "--no-tui")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.rstrip("\n") == _decisions.render_list_plain([])

    def test_cmd_decisions_json_flag_unchanged(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        proc = _cli(repo, "decisions", "--json")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == []


class TestRendererCrashSafety:
    """A renderer is pure presentation: the worst a buggy one can do is produce
    ugly text — it can never crash the command (rendering is downstream of the
    already-made decision). A plugin method that RAISES degrades to the built-in
    text form with a stderr note, not a traceback."""

    def test_buggy_plugin_method_falls_back_to_text(self, capsys):
        from dos import cli

        class _Boom:
            name = "boom"

            def render_verdict(self, verdict):
                raise RuntimeError("kaboom")

            def render_decision(self, decision):
                raise RuntimeError("kaboom")

        v = ShipVerdict(plan="P", phase="1", shipped=False, source="none")
        # _render_one must catch the raise and return the canonical text form.
        out = cli._render_one(_Boom(), "render_verdict", v)
        assert out == render.TEXT.render_verdict(v)
        # …AND it must say so on stderr — the plan promises "degrades … WITH a
        # stderr note", so the silent-swallow is itself a litmus failure. The
        # note names the culprit renderer + method so an operator can find it.
        err = capsys.readouterr().err
        assert "boom" in err and "render_verdict" in err
        assert "kaboom" in err  # the underlying exception is surfaced, not hidden
        assert "falling back to text" in err

    def test_buggy_plugin_via_cli_does_not_crash(self, capsys):
        """A registered plugin whose render_decision raises makes the command
        print the text fallback, with a warning on stderr — never a
        traceback/crash."""
        # Drive _render_one directly with a CLI-shaped args to avoid needing a
        # real installed plugin; the end-to-end resolve path is covered by the
        # terse North-star. Here we assert the CLI helper's crash-safety.
        from dos import cli
        d = LaneDecision("acquire", lane="api")

        class _Boom:
            name = "boom"

            def render_decision(self, decision):
                raise ValueError("nope")

        out = cli._render_one(_Boom(), "render_decision", d)
        assert out == render.TEXT.render_decision(d)
        # The stderr note is half the contract ("degrades … with a stderr
        # note") — assert it, not just the fallback value.
        err = capsys.readouterr().err
        assert "boom" in err and "render_decision" in err
        assert "nope" in err and "falling back to text" in err

    def test_partial_plugin_missing_optional_surface_falls_back(self):
        """A plugin with NO render_man inherits the built-in text man form."""
        from dos import cli

        class _OnlyVerdict:
            name = "ov"

            def render_verdict(self, v):
                return "v"

            def render_decision(self, d):
                return "d"

        e = render.ManEntry(["NAME x", "CATEGORY y"], {"key": "x"})
        out = cli._render_one(_OnlyVerdict(), "render_man", e)
        assert out == render.TEXT.render_man(e)


# ---------------------------------------------------------------------------
# The built-in `plain` renderer — the non-coder verdict surface (adoption floor)
# ---------------------------------------------------------------------------
class TestBuiltinPlainRenderer:
    """`plain` is a third always-available built-in (developer/machine/non-coder).
    These pin the three disciplines that make it trustworthy to a reader who cannot
    read the code, plus that it resolves like a built-in and can't be shadowed."""

    # -- it is a built-in, resolvable, unshadowable -------------------------------
    def test_plain_is_a_builtin(self):
        assert "plain" in render.BUILTIN_RENDERERS
        assert render.resolve_renderer("plain") is render.PLAIN
        assert render.PLAIN.name == "plain"

    def test_known_renderers_lists_plain_after_text_json(self):
        names = render.known_renderers()
        assert names[:3] == ["text", "json", "plain"]

    def test_plain_cannot_be_shadowed_by_plugin(self, monkeypatch):
        class _StubPlain:
            name = "plain"

            def render_verdict(self, v):
                return "HIJACKED"

            def render_decision(self, d):
                return "HIJACKED"

        monkeypatch.setattr(
            render, "_discover_entry_point_renderers",
            lambda *, _stderr=None: {"plain": _StubPlain()},
        )
        # built-ins resolve FIRST — the plugin named `plain` never wins.
        assert render.resolve_renderer("plain") is render.PLAIN

    # -- discipline 1: contrast + a way forward, never a bare accusation ----------
    def test_not_shipped_is_non_accusatory_with_next_step(self):
        v = ShipVerdict(plan="AUTH", phase="login-page", shipped=False, source="none")
        out = render.PLAIN.render_verdict(v)
        assert "Not yet" in out and "login-page" in out
        assert "Ask it to actually add" in out          # the way forward
        # never the bare jargon a non-coder reads as an accusation / a crash
        assert "NOT_SHIPPED" not in out and "via none" not in out

    # -- discipline 2: presence, never correctness (Wall §3) ---------------------
    def test_shipped_claims_presence_not_correctness(self):
        v = ShipVerdict(plan="AUTH", phase="login-page", shipped=True, sha="abc",
                        source="registry")
        out = render.PLAIN.render_verdict(v)
        assert out.startswith("Yes:") and "in what was built" in out
        assert "not that it's correct" in out           # explicitly refuses to certify
        assert "SHIPPED" not in out

    # -- discipline 3: hedge the weak grep-subject rung --------------------------
    def test_grep_subject_is_hedged_distinct_from_strong_yes(self):
        strong = render.PLAIN.render_verdict(
            ShipVerdict(plan="P", phase="x", shipped=True, source="grep-artifact"))
        weak = render.PLAIN.render_verdict(
            ShipVerdict(plan="P", phase="x", shipped=True, source="grep-subject"))
        assert strong.startswith("Yes:")
        assert weak.startswith("Probably yes")
        assert "project history" in weak                 # names WHY it's weak
        assert strong != weak

    # -- the coordination surface in plain language ------------------------------
    def test_decision_refuse_is_a_safe_wait(self):
        d = LaneDecision("refuse", lane="src", reason="src is held by run abc")
        out = render.PLAIN.render_decision(d)
        assert "Waiting" in out and "clobber" in out

    def test_decision_autopick_reassures(self):
        d = LaneDecision("acquire", lane="docs", auto_picked=True)
        out = render.PLAIN.render_decision(d)
        assert "Started" in out and "Nothing was overwritten" in out

    # -- optional surfaces fall back to text (BaseRenderer) -----------------------
    def test_plain_inherits_text_for_optional_surfaces(self):
        e = render.ManEntry(["NAME x"], {"k": "v"})
        assert render.PLAIN.render_man(e) == render.TEXT.render_man(e)

    # -- end-to-end through the CLI ----------------------------------------------
    def test_cli_output_plain_gives_the_non_coder_sentence(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                       cwd=repo, check=True)
        proc = _cli(repo, "verify", "P", "1", "--output", "plain")
        assert proc.returncode == 1, (proc.stdout, proc.stderr)   # not shipped
        # the renderer names the PHASE ("1") as the thing — it is the more specific
        # "thing you asked for" (see PlainRenderer._thing: phase, then plan).
        assert proc.stdout.startswith("Not yet: '1' isn't in what was built.")
