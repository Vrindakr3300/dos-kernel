"""Tests for the environment print — *under what* a verdict ran (docs/115 §2, primitive 1).

Proves the four properties the plan's litmus list pins for Phase 1:
  * the print is a PURE dataclass (constructible with no I/O, the test path);
  * the `digest` is deterministic, order-insensitive over tools, and tamper-proof
    (recomputed from fields, a stored digest is ignored);
  * the print rides the `durable_schema` floor (a newer print is refuse-don't-guessed);
  * gathering is boundary I/O (`gather_env_print` is the only thing that probes),
    the config carries it, and `with_root` preserves it WITHOUT re-probing;
  * stamping the print into the intent-ledger `INTENT` record is ADDITIVE — it
    round-trips and changes no existing read (a no-`env` ledger reads unchanged).
"""

from __future__ import annotations

import json

from dos import config as _config
from dos import durable_schema as _schema
from dos import env_print
from dos import intent_ledger as il
from dos.env_print import EnvPrint, ToolVersion, gather_env_print


def _p(**kw) -> EnvPrint:
    base = dict(
        kernel_version="0.8.0",
        kernel_sha="deadbeef",
        python="3.13.1",
        platform="linux-x86_64",
        tools=(ToolVersion("git", "2.43.0"),),
    )
    base.update(kw)
    return EnvPrint(**base)


# --------------------------------------------------------------------------
# The pure object — no I/O, deterministic digest.
# --------------------------------------------------------------------------

class TestEnvPrintPure:
    def test_constructible_without_io(self):
        # The WorkspaceFacts(root=…) rule: a hand-built print never touches git/sys.
        p = _p()
        assert p.kernel_version == "0.8.0"
        assert p.kernel_sha == "deadbeef"

    def test_digest_is_stable(self):
        p = _p()
        assert p.digest == p.digest
        # And equal across two independently-built equal prints (a hash, not a
        # per-process-salted Python hash()).
        assert _p().digest == _p().digest

    def test_digest_order_insensitive_over_tools(self):
        a = _p(tools=(ToolVersion("git", "2.43.0"), ToolVersion("node", "20")))
        b = _p(tools=(ToolVersion("node", "20"), ToolVersion("git", "2.43.0")))
        assert a.digest == b.digest

    def test_digest_changes_on_any_field(self):
        base = _p().digest
        assert _p(kernel_version="0.9.0").digest != base
        assert _p(kernel_sha="cafef00d").digest != base
        assert _p(python="3.12.0").digest != base
        assert _p(platform="win32-AMD64").digest != base
        assert _p(tools=(ToolVersion("git", "2.44.0"),)).digest != base

    def test_no_sha_distinct_from_empty_sha_string(self):
        # A wheel install (no SHA) and a checkout at "" are both recorded as None;
        # the digest of None is stable and distinct from a real SHA.
        assert _p(kernel_sha=None).digest == _p(kernel_sha=None).digest
        assert _p(kernel_sha=None).digest != _p(kernel_sha="deadbeef").digest


class TestEnvPrintRoundTrip:
    def test_to_from_dict(self):
        p = _p()
        assert EnvPrint.from_dict(p.to_dict()) == p

    def test_stored_digest_is_ignored(self):
        # The field is authoritative; a tampered/stale stored digest is recomputed.
        d = _p().to_dict()
        d["digest"] = "TAMPEREDXXXX"
        assert EnvPrint.from_dict(d).digest == _p().digest

    def test_malformed_yields_none_not_crash(self):
        assert EnvPrint.from_dict({}) is None              # no kernel_version
        assert EnvPrint.from_dict({"kernel_version": ""}) is None
        assert EnvPrint.from_dict("nonsense") is None      # not a mapping
        # A garbled tools list is tolerated (bad entries dropped), not fatal.
        d = _p().to_dict()
        d["tools"] = ["not-a-dict", {"name": "git", "version": "2.43.0"}]
        back = EnvPrint.from_dict(d)
        assert back is not None and len(back.tools) == 1 and back.tools[0].name == "git"

    def test_carries_schema_tag(self):
        d = _p().to_dict()
        tag = _schema.SchemaTag.from_obj(d[_schema.SCHEMA_KEY])
        assert tag is not None
        assert tag.family == env_print.SCHEMA_FAMILY
        assert tag.version == env_print.ENV_PRINT_SCHEMA


class TestEnvPrintSchemaFloor:
    def test_newer_print_is_refused_not_guessed(self):
        # A print a newer kernel wrote (higher version) must REFUSE at read — the
        # docs/115 primitive-4 floor closing on primitive 1.
        d = _p().to_dict()
        d[_schema.SCHEMA_KEY] = {"family": env_print.SCHEMA_FAMILY, "version": env_print.ENV_PRINT_SCHEMA + 1}
        v = _schema.classify(d, family=env_print.SCHEMA_FAMILY, understands=env_print.ENV_PRINT_SCHEMA)
        assert v.readability is _schema.Readability.UNREADABLE_NEWER
        assert not v.readability.is_soundly_readable

    def test_current_print_is_readable(self):
        v = _schema.classify(_p().to_dict(), family=env_print.SCHEMA_FAMILY,
                             understands=env_print.ENV_PRINT_SCHEMA)
        assert v.readability is _schema.Readability.READABLE


# --------------------------------------------------------------------------
# The boundary gatherer — the ONE I/O home (real probes).
# --------------------------------------------------------------------------

class TestGatherEnvPrint:
    def test_gather_records_runtime_facts(self):
        g = gather_env_print()
        # Kernel version is the live __version__; Python/OS always resolve.
        import dos
        assert g.kernel_version == dos.__version__
        assert g.python.count(".") == 2          # x.y.z
        assert "-" in g.platform                 # <system>-<machine>

    def test_gather_resolves_kernel_sha_in_this_checkout(self):
        # This test runs inside the DOS git tree, so the kernel SHA resolves — the
        # stale-`.pth` lie-detector has a real value to print here.
        g = gather_env_print()
        assert g.kernel_sha is not None and len(g.kernel_sha) >= 7

    def test_declared_tool_probed(self):
        g = gather_env_print(tools=["git"])
        assert len(g.tools) == 1 and g.tools[0].name == "git"
        assert g.tools[0].version  # git --version answered

    def test_undeclared_tool_recorded_absent_not_dropped(self):
        # A declared-but-missing tool is a FACT (recorded with version=""), not an
        # error and not silently dropped.
        g = gather_env_print(tools=["this-binary-does-not-exist-xyz"])
        assert len(g.tools) == 1
        assert g.tools[0].name == "this-binary-does-not-exist-xyz"
        assert g.tools[0].version == ""


# --------------------------------------------------------------------------
# The config seam carries it — gathered once, preserved on re-point.
# --------------------------------------------------------------------------

class TestConfigCarriesEnv:
    def test_default_config_gathers_env(self, tmp_path):
        cfg = _config.default_config(tmp_path)
        assert cfg.env is not None
        assert cfg.env.digest  # a real, content-addressed EnvId

    def test_job_config_gathers_env(self, tmp_path):
        cfg = _config.job_config(tmp_path)
        assert cfg.env is not None

    def test_pure_construction_leaves_env_none(self, tmp_path):
        # A hand-built SubstrateConfig (no builder) carries env=None — the pure
        # path, treated as "not recorded" everywhere (the WorkspaceFacts=None rule).
        from dos.config import SubstrateConfig, LaneTaxonomy, PathLayout
        cfg = SubstrateConfig(
            lanes=LaneTaxonomy(concurrent=("main",), exclusive=("global",),
                               autopick=("main",), trees={"main": ("**/*",), "global": ("**/*",)},
                               aliases={}),
            paths=PathLayout.for_dos_dir(tmp_path),
        )
        assert cfg.env is None

    def test_with_root_preserves_env_without_reprobing(self, tmp_path):
        # The env print describes the KERNEL, not the served tree, so a re-point
        # keeps it verbatim (and does no surprise git I/O for it).
        cfg = _config.default_config(tmp_path)
        other = tmp_path / "elsewhere"
        other.mkdir()
        moved = cfg.with_root(other)
        assert moved.env is cfg.env  # same object, not re-gathered


# --------------------------------------------------------------------------
# Performance — the print is gathered ONCE per process, and a caller that
# doesn't need it can skip the probe entirely (docs/275). These pin the two
# mechanisms that took the MCP server's per-tool-call EnvPrint cost (a
# `git rev-parse` subprocess + a platform query) from ~13ms/call to ~0.
# --------------------------------------------------------------------------
class TestEnvPrintMemoizedPerProcess:
    def test_gather_is_memoized_returns_same_object(self):
        # The print describes the running KERNEL (version/SHA/OS/tools) — constant
        # for the process — so a second gather returns the SAME frozen object, not
        # a freshly re-probed equal one. (Identity is the observable proof the git
        # subprocess + platform probe did NOT run again.)
        env_print._clear_env_print_cache()
        a = gather_env_print()
        b = gather_env_print()
        assert a is b
        # A distinct cache key (declared tools) is a distinct gather, still memoized.
        c = gather_env_print(tools=["git"])
        assert c is not a
        assert gather_env_print(tools=["git"]) is c

    def test_gather_skips_the_git_subprocess_on_a_cache_hit(self, monkeypatch):
        # The cost the memo removes is `_kernel_sha`'s `git rev-parse` subprocess.
        # Warm the cache, then make the SHA probe explode — a cache hit must never
        # reach it. (Proves the second+ call does zero git I/O, the docs/275 win.)
        env_print._clear_env_print_cache()
        gather_env_print()  # warm — the one allowed real probe

        warm = gather_env_print()  # the cached object we expect back verbatim

        def _boom(*a, **k):
            raise AssertionError("a cache hit re-ran the git-SHA subprocess")

        monkeypatch.setattr(env_print, "_kernel_sha", _boom)
        # A cache hit returns the SAME warmed object without reaching the (now
        # exploding) probe — if the memo were bypassed, `_boom` would raise here.
        assert gather_env_print() is warm

    def test_clear_cache_forces_a_fresh_gather(self, monkeypatch):
        env_print._clear_env_print_cache()
        first = gather_env_print()
        env_print._clear_env_print_cache()
        # After a clear, the probe runs again — a sentinel SHA proves a real re-gather.
        monkeypatch.setattr(env_print, "_kernel_sha", lambda *a, **k: "FRESHSHA1234")
        second = gather_env_print()
        assert second is not first
        assert second.kernel_sha == "FRESHSHA1234"
        # Don't leave the sentinel print in the per-process memo for later tests
        # (a real config build elsewhere reads cfg.env.kernel_sha) — clear it.
        env_print._clear_env_print_cache()


class TestGatherEnvFlagSkipsTheProbe:
    def test_default_config_gather_env_false_leaves_env_none(self, tmp_path):
        # `gather_env=False` → env=None (the documented "not recorded" state every
        # consumer handles), identical to the pure-construction path — what the MCP
        # server passes because no tool reads cfg.env.
        cfg = _config.default_config(tmp_path, gather_env=False)
        assert cfg.env is None
        # The default still gathers (the CLI/doctor/intent-ledger contract).
        assert _config.default_config(tmp_path).env is not None

    def test_job_config_gather_env_false_leaves_env_none(self, tmp_path):
        assert _config.job_config(tmp_path, gather_env=False).env is None
        assert _config.job_config(tmp_path).env is not None

    def test_load_workspace_config_forwards_gather_env(self, tmp_path):
        assert _config.load_workspace_config(tmp_path, gather_env=False).env is None
        assert _config.load_workspace_config(tmp_path).env is not None

    def test_gather_env_false_makes_no_env_probe(self, tmp_path, monkeypatch):
        # The STRUCTURAL guard (no timing threshold): with gather_env=False the
        # builder must not call `gather_env_print` at all — so a fan-out of config
        # builds cannot accumulate the probe cost. Make the gatherer explode and
        # prove the build still succeeds.
        def _boom(*a, **k):
            raise AssertionError("gather_env=False still probed the EnvPrint")

        monkeypatch.setattr(_config, "gather_env_print", _boom)
        cfg = _config.default_config(tmp_path, gather_env=False)
        assert cfg.env is None
        # And the MCP server's loader (which passes gather_env=False) is safe too.
        cfg2 = _config.load_workspace_config(tmp_path, gather_env=False)
        assert cfg2.env is None


# --------------------------------------------------------------------------
# The intent-ledger stamp — additive, round-trips, no read regressions.
# --------------------------------------------------------------------------

class TestIntentLedgerEnvStamp:
    def test_intent_entry_carries_env(self):
        ep = _p()
        e = il.intent_entry(goal="ship X", env=ep.to_dict())
        assert e["op"] == il.OP_INTENT
        assert EnvPrint.from_dict(e["env"]) == ep

    def test_intent_entry_without_env_is_unchanged(self):
        # The additive contract: a no-env INTENT has no `env` key (a fossil from a
        # kernel that didn't stamp prints reads back byte-identical).
        e = il.intent_entry(goal="ship X")
        assert "env" not in e

    def test_stamped_ledger_round_trips(self, tmp_path):
        run = "RUN-test"
        path = tmp_path / "intent.jsonl"
        ep = gather_env_print()
        il.append(run, il.intent_entry(goal="ship X", env=ep.to_dict()), path=path)
        rows = il.read_all(run, path=path)
        assert len(rows) == 1
        assert rows[0]["op"] == il.OP_INTENT
        assert EnvPrint.from_dict(rows[0]["env"]).digest == ep.digest

    def test_env_stamp_does_not_bump_schema(self):
        # An INTENT with an env field still carries the SAME intent-ledger schema
        # version (additive: a new optional field never bumps it).
        with_env = il.intent_entry(goal="g", env=_p().to_dict())
        without = il.intent_entry(goal="g")
        assert with_env[_schema.SCHEMA_KEY] == without[_schema.SCHEMA_KEY]


# --------------------------------------------------------------------------
# The doctor surface — the print is reported, both JSON and text.
# --------------------------------------------------------------------------

class TestDoctorSurfacesEnv:
    def test_json_doctor_includes_env(self, tmp_path):
        # Build the report shape the CLI emits and assert the env block is present
        # and parseable back to a print. (Exercised through default_config so the
        # gather actually ran.)
        cfg = _config.default_config(tmp_path)
        assert cfg.env is not None
        blob = cfg.env.to_dict()
        # The JSON path serializes this verbatim; a round-trip through json proves
        # it is JSON-clean (no non-serializable fields snuck in).
        back = EnvPrint.from_dict(json.loads(json.dumps(blob)))
        assert back == cfg.env


# --------------------------------------------------------------------------
# Phase 2a — the WAL stamp (lane_journal ACQUIRE carries the digest, additive).
# --------------------------------------------------------------------------

class TestWalEnvDigestStamp:
    def _lease(self) -> dict:
        return {"lane": "src", "lane_kind": "concurrent", "tree": ["src/**"],
                "loop_ts": "2026-06-03T10:00:00Z", "host_id": "h1", "pid": 123,
                "ttl_minutes": 30}

    def test_acquire_entry_carries_env_digest(self):
        from dos import lane_journal as lj
        ep = _p()
        e = lj.acquire_entry(self._lease(), env_digest=ep.digest)
        assert e["op"] == lj.OP_ACQUIRE
        assert e["env_digest"] == ep.digest

    def test_acquire_entry_without_digest_is_unchanged(self):
        # Additive: a no-digest ACQUIRE has no `env_digest` key (a hold from a kernel
        # that did not stamp prints replays byte-identical).
        from dos import lane_journal as lj
        e = lj.acquire_entry(self._lease())
        assert "env_digest" not in e

    def test_digest_survives_replay(self, tmp_path):
        # The digest rides the WAL and replay reconstructs the live lease without
        # tripping on the new optional field (the forward-compat fold contract).
        from dos import lane_journal as lj
        path = tmp_path / "lane-journal.jsonl"
        ep = _p()
        lj.append(lj.acquire_entry(self._lease(), env_digest=ep.digest), path=path)
        rows = lj.read_all(path=path)
        assert len(rows) == 1 and rows[0]["env_digest"] == ep.digest
        # replay (pure: entries in, leases out) still yields the live lease for the
        # lane without tripping on the new optional field.
        live = lj.replay(rows)
        assert any(l.get("lane") == "src" for l in live)


# --------------------------------------------------------------------------
# Phase 4 — SCHEMA_UNREADABLE: the refuse-don't-guess floor as a first-class
# refuse carrying the supported set (the MCP {supported, requested} shape).
# --------------------------------------------------------------------------

class TestSchemaUnreadableReason:
    def test_token_is_in_base_reasons(self):
        from dos.reasons import BASE_REASONS
        spec = BASE_REASONS.get("SCHEMA_UNREADABLE")
        assert spec is not None
        # The SELF_MODIFY sibling — a record this kernel can't parse is a MISROUTE.
        assert spec.category == "MISROUTE"
        assert spec.refusal is True

    def test_token_classifies_and_refuses(self):
        # Emittable → verifiable → refusable, the lockstep every reason rides.
        from dos.reasons import BASE_REASONS
        assert BASE_REASONS.category_for("SCHEMA_UNREADABLE") == "MISROUTE"
        assert BASE_REASONS.is_refusal("SCHEMA_UNREADABLE") is True

    def test_payload_has_mcp_supported_requested_shape(self):
        # A v3 record met by a v1-ceiling reader → refuse carrying {supported,
        # requested} so the caller can re-negotiate/migrate (MCP -32004 shape).
        d = _p().to_dict()
        d[_schema.SCHEMA_KEY] = {"family": env_print.SCHEMA_FAMILY, "version": 3}
        v = _schema.classify(d, family=env_print.SCHEMA_FAMILY, understands=1)
        assert v.readability is _schema.Readability.UNREADABLE_NEWER
        payload = _schema.unreadable_refusal_payload(v)
        assert payload["reason_class"] == "SCHEMA_UNREADABLE"
        assert payload["family"] == env_print.SCHEMA_FAMILY
        assert payload["requested"] == 3
        assert payload["supported"] == [1]      # the kernel reads v1 only
        assert payload["detail"]                # a legible one-liner rides along

    def test_payload_well_formed_without_tag(self):
        # Defensive: an untagged record yields requested == ceiling, never a crash.
        v = _schema.classify({"op": "x"}, family=env_print.SCHEMA_FAMILY, understands=2)
        payload = _schema.unreadable_refusal_payload(v)
        assert payload["requested"] == 2 and payload["supported"] == [1, 2]
